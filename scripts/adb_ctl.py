#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""adb 手机操控封装：把「刷 App」拆成一组可审计的原子动作。

设计原则（对应 references/android-adb-policy.md）：
1. 白名单命令：不暴露 root / remount / tcpip / backup / pm clear / settings put，
   这些命令一旦用错会不可逆地改变设备或把调试口暴露到局域网。
2. 只连 USB 单设备：多设备必须显式 --serial，避免命令随机落到另一台手机上。
3. 元素优先：能用 uiautomator 的文本/resource-id 定位，就不用坐标点击。
4. 截图走「设备端落盘 → pull → 删设备端」三步：Windows 下
   `adb exec-out screencap -p > x.png` 在 PowerShell 里会把 PNG 写坏。
5. 所有输出为 JSON，退出码 0 成功 / 1 操作失败或被规则拒绝 / 2 环境缺失。

用法:
    python scripts/adb_ctl.py status
    python scripts/adb_ctl.py devices
    python scripts/adb_ctl.py packages --search boss
    python scripts/adb_ctl.py launch --package com.hpbr.bosszhipin
    python scripts/adb_ctl.py dump [--contains 财务] [--limit 80]
    python scripts/adb_ctl.py find --text "立即沟通"
    python scripts/adb_ctl.py tap --text "立即沟通" [--index 0]
    python scripts/adb_ctl.py tap --xy 540,1800
    python scripts/adb_ctl.py swipe up [--duration 320]
    python scripts/adb_ctl.py browse --rounds 5 --interval 2.5 --out jobs/raw/boss-browse.jsonl
    python scripts/adb_ctl.py screenshot --out logs/screens/boss-01.png
    python scripts/adb_ctl.py text "hello"        # 仅 ASCII，中文会明确拒绝
    python scripts/adb_ctl.py key back|home|wake|enter
    python scripts/adb_ctl.py wait --text "职位详情" --timeout 8

本脚本不联网、不安装任何依赖。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from common import emit, now_iso, read_json, rel_path, resolve

# 这些命令一律不提供：一旦用错会不可逆地改设备，或把调试口暴露到局域网。
FORBIDDEN_SUBCOMMANDS = ("root", "unroot", "remount", "tcpip", "backup", "restore", "fastboot")
FORBIDDEN_PREFIXES = ("pm clear", "settings put", "shell rm -rf")

KEYCODES = {
    "back": 4,
    "home": 3,
    "wake": 224,  # KEYCODE_WAKEUP；不要用 26（POWER 是切换态，会把亮着的屏幕锁掉）
    "sleep": 223,
    "enter": 66,
    "delete": 67,
    "menu": 82,
}

DEFAULT_SETTINGS = os.path.join("config", "settings.json")


# ---------------------------------------------------------------------------
# adb 定位与调用
# ---------------------------------------------------------------------------
def find_adb(root=None):
    """按 环境变量 → 配置 → PATH → 常见 SDK 目录 的顺序找 adb。"""
    candidates = []
    if os.environ.get("ADB"):
        candidates.append(os.environ["ADB"])
    try:
        settings = read_json(resolve(DEFAULT_SETTINGS))
        configured = ((settings.get("executor_policy") or {}).get("mobile") or {}).get("adb_path")
        if configured:
            candidates.append(configured)
    except SystemExit:
        pass
    found = shutil.which("adb") or shutil.which("adb.exe")
    if found:
        candidates.append(found)
    local = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/AppData/Local")
    candidates.extend(
        [
            os.path.join(local, "Android", "Sdk", "platform-tools", "adb.exe"),
            os.path.join(local, "Android", "Sdk", "platform-tools", "adb"),
            "C:/Android/platform-tools/adb.exe",
            "D:/Android/platform-tools/adb.exe",
        ]
    )
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return ""


def _guard(args):
    """拦截危险 adb 子命令。只检查命令头部，避免把用户文本误判成命令。"""
    head = [str(item) for item in args[:3]]
    if head and head[0].lower() in FORBIDDEN_SUBCOMMANDS:
        return head[0]
    joined = " ".join(head).lower()
    for pattern in FORBIDDEN_PREFIXES:
        if joined.startswith(pattern):
            return pattern
    return ""


def _adb(args, serial=None, timeout=45, binary=False):
    exe = find_adb(None)
    if not exe:
        emit(
            {
                "ok": False,
                "error": "未找到 adb。请安装 Android SDK Platform-Tools 并把路径加入 PATH，"
                "或在 config/settings.json 的 executor_policy.mobile.adb_path 指定。",
                "hint": "安装属于修改系统，按规则需用户本人确认后再做。",
            },
            2,
        )
    denied = _guard(args)
    if denied:
        emit({"ok": False, "error": "该命令被手机执行器规则禁止：%s" % denied, "denied": True}, 1)
    command = [exe] + (["-s", serial] if serial else []) + [str(item) for item in args]
    try:
        proc = subprocess.run(command, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        emit({"ok": False, "error": "adb 命令超时（%ss）：%s" % (timeout, " ".join(args))}, 1)
    except OSError as exc:
        emit({"ok": False, "error": "无法执行 adb：%s" % exc}, 2)
    return {
        "code": proc.returncode,
        "stdout": proc.stdout if binary else proc.stdout.decode("utf-8", "replace"),
        "stderr": proc.stderr.decode("utf-8", "replace"),
    }


def list_devices():
    result = _adb(["devices", "-l"])
    devices = []
    for line in result["stdout"].splitlines():
        line = line.strip()
        if not line or line.startswith("List of devices"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        item = {"serial": parts[0], "state": parts[1]}
        for token in parts[2:]:
            if ":" in token:
                key, value = token.split(":", 1)
                item[key] = value
        devices.append(item)
    return devices


def pick_serial(requested):
    devices = list_devices()
    ready = [item for item in devices if item["state"] == "device"]
    if requested:
        match = [item for item in devices if item["serial"] == requested]
        if not match:
            emit({"ok": False, "error": "指定设备不存在：%s" % requested, "devices": devices}, 2)
        return requested, devices
    if not ready:
        emit(
            {
                "ok": False,
                "error": "没有可用设备。请插 USB、在手机上允许 USB 调试并解锁屏幕。",
                "devices": devices,
                "hint": "只连接一台设备；多台时用 --serial 指定。",
            },
            2,
        )
    if len(ready) > 1:
        emit(
            {
                "ok": False,
                "error": "检测到 %d 台可用设备，命令必须显式指定 --serial" % len(ready),
                "devices": devices,
            },
            2,
        )
    return ready[0]["serial"], devices


# ---------------------------------------------------------------------------
# UI 层级：dump → pull → 解析
# ---------------------------------------------------------------------------
BOUNDS_PATTERN = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def _parse_bounds(text):
    match = BOUNDS_PATTERN.search(text or "")
    if not match:
        return None
    x1, y1, x2, y2 = (int(item) for item in match.groups())
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "cx": (x1 + x2) // 2, "cy": (y1 + y2) // 2}


def dump_ui(serial):
    """返回 (nodes, raw_xml_path)。失败时抛出 RuntimeError。"""
    remote = "/sdcard/jobagent_ui.xml"
    local = os.path.join(tempfile.gettempdir(), "jobagent_ui_%d.xml" % os.getpid())
    if os.path.exists(local):
        os.remove(local)
    result = _adb(["shell", "uiautomator", "dump", remote], serial=serial)
    combined = (result["stdout"] + result["stderr"]).lower()
    if "error" in combined or "could not" in combined:
        raise RuntimeError(
            "uiautomator dump 失败：%s；常见原因：屏幕锁定、当前是系统权限弹窗、或 App 用了自绘界面"
            % (result["stdout"] + result["stderr"]).strip()[:200]
        )
    pull = _adb(["pull", remote, local], serial=serial)
    _adb(["shell", "rm", "-f", remote], serial=serial)
    if not os.path.exists(local):
        raise RuntimeError("拉取 UI 层级失败：%s" % pull["stderr"].strip()[:200])
    try:
        root = ET.parse(local).getroot()
    except ET.ParseError as exc:
        raise RuntimeError("UI 层级 XML 解析失败：%s" % exc)
    finally:
        try:
            os.remove(local)
        except OSError:
            pass

    nodes = []
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        desc = (node.get("content-desc") or "").strip()
        node_id = (node.get("resource-id") or "").strip()
        if not (text or desc or node_id):
            continue
        bounds = _parse_bounds(node.get("bounds"))
        nodes.append(
            {
                "text": text,
                "desc": desc,
                "id": node_id,
                "class": node.get("class"),
                "clickable": node.get("clickable") == "true",
                "scrollable": node.get("scrollable") == "true",
                "enabled": node.get("enabled") != "false",
                "bounds": bounds,
            }
        )
    return nodes, local


def match_nodes(nodes, text=None, node_id=None, exact=False):
    hits = []
    for node in nodes:
        if text:
            haystack = node["text"] or node["desc"]
            if exact:
                if haystack != text:
                    continue
            elif text not in haystack:
                continue
        if node_id and node_id not in (node["id"] or ""):
            continue
        hits.append(node)
    return [node for node in hits if node["bounds"]]


def screen_size(serial):
    result = _adb(["shell", "wm", "size"], serial=serial)
    match = re.search(r"(\d+)x(\d+)", result["stdout"])
    if not match:
        return None
    return {"width": int(match.group(1)), "height": int(match.group(2))}


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def cmd_devices(args):
    devices = list_devices()
    emit({"ok": True, "count": len(devices), "devices": devices, "checked_at": now_iso()}, 0)


def cmd_status(args):
    exe = find_adb(None)
    if not exe:
        emit(
            {
                "ok": False,
                "adb": "",
                "error": "未找到 adb（PATH、ADB 环境变量、config/settings.json 的 mobile.adb_path、常见 SDK 目录都没有）",
                "checked_at": now_iso(),
            },
            2,
        )
    version = _adb(["version"])
    devices = list_devices()
    ready = [item for item in devices if item["state"] == "device"]
    payload = {
        "ok": bool(ready),
        "adb": exe,
        "version": version["stdout"].splitlines()[0] if version["stdout"] else "",
        "devices": devices,
        "checked_at": now_iso(),
    }
    if ready:
        payload["screen"] = screen_size(ready[0]["serial"])
        payload["model"] = _adb(["shell", "getprop", "ro.product.model"], serial=ready[0]["serial"])["stdout"].strip()
        payload["android"] = _adb(["shell", "getprop", "ro.build.version.release"], serial=ready[0]["serial"])["stdout"].strip()
    else:
        payload["error"] = "adb 可用，但没有处于 device 状态的设备"
    emit(payload, 0 if ready else 2)


def cmd_packages(args):
    serial, _devices = pick_serial(args.serial)
    result = _adb(["shell", "pm", "list", "packages"], serial=serial)
    packages = [line.strip().replace("package:", "") for line in result["stdout"].splitlines() if line.startswith("package:")]
    if args.search:
        packages = [item for item in packages if args.search.lower() in item.lower()]
    emit({"ok": True, "count": len(packages), "packages": sorted(packages)}, 0)


def cmd_launch(args):
    serial, _devices = pick_serial(args.serial)
    result = _adb(
        ["shell", "monkey", "-p", args.package, "-c", "android.intent.category.LAUNCHER", "1"],
        serial=serial,
    )
    output = result["stdout"] + result["stderr"]
    if "No activities found" in output or "monkey aborted" in output.lower():
        emit({"ok": False, "error": "无法启动 %s：包名可能不对或应用未安装" % args.package, "raw": output.strip()[:300]}, 1)
    emit({"ok": True, "package": args.package, "serial": serial, "at": now_iso()}, 0)


def cmd_dump(args):
    serial, _devices = pick_serial(args.serial)
    try:
        nodes, _local = dump_ui(serial)
    except RuntimeError as exc:
        emit({"ok": False, "error": str(exc)}, 1)
    if args.contains:
        nodes = [node for node in nodes if args.contains in (node["text"] or node["desc"])]
    limited = nodes[: args.limit]
    emit(
        {
            "ok": True,
            "serial": serial,
            "count": len(nodes),
            "returned": len(limited),
            "nodes": limited,
            "at": now_iso(),
        },
        0,
    )


def cmd_find(args):
    serial, _devices = pick_serial(args.serial)
    try:
        nodes, _local = dump_ui(serial)
    except RuntimeError as exc:
        emit({"ok": False, "error": str(exc)}, 1)
    hits = match_nodes(nodes, text=args.text, node_id=args.id, exact=args.exact)
    emit({"ok": bool(hits), "count": len(hits), "matches": hits[: args.limit]}, 0 if hits else 1)


def cmd_tap(args):
    serial, _devices = pick_serial(args.serial)
    if args.xy:
        match = re.match(r"^(\d+)\s*,\s*(\d+)$", args.xy)
        if not match:
            emit({"ok": False, "error": "--xy 格式应为 x,y"}, 2)
        x, y = int(match.group(1)), int(match.group(2))
        target = {"x": x, "y": y, "by": "coordinate"}
    else:
        if not (args.text or args.id):
            emit({"ok": False, "error": "需要 --text / --id / --xy 之一"}, 2)
        try:
            nodes, _local = dump_ui(serial)
        except RuntimeError as exc:
            emit({"ok": False, "error": str(exc)}, 1)
        hits = match_nodes(nodes, text=args.text, node_id=args.id, exact=args.exact)
        if not hits:
            emit({"ok": False, "error": "界面上找不到目标元素：%r" % (args.text or args.id), "hint": "先 dump 看看当前页面结构"}, 1)
        node = hits[args.index]
        target = {
            "x": node["bounds"]["cx"],
            "y": node["bounds"]["cy"],
            "by": "text" if args.text else "id",
            "text": node["text"],
            "id": node["id"],
        }
    _adb(["shell", "input", "tap", target["x"], target["y"]], serial=serial)
    emit({"ok": True, "serial": serial, "tap": target, "at": now_iso()}, 0)


def cmd_swipe(args):
    serial, _devices = pick_serial(args.serial)
    size = screen_size(serial) or {"width": 1080, "height": 2400}
    width, height = size["width"], size["height"]
    margin_x, margin_y = int(width * 0.5), int(height * 0.25)
    coords = {
        "up": (margin_x, int(height * 0.75), margin_x, int(height * 0.30)),
        "down": (margin_x, int(height * 0.30), margin_x, int(height * 0.75)),
        "left": (int(width * 0.8), margin_y * 2, int(width * 0.2), margin_y * 2),
        "right": (int(width * 0.2), margin_y * 2, int(width * 0.8), margin_y * 2),
    }
    if args.direction not in coords:
        emit({"ok": False, "error": "方向只能是 %s" % "/".join(coords)}, 2)
    x1, y1, x2, y2 = coords[args.direction]
    _adb(["shell", "input", "swipe", x1, y1, x2, y2, args.duration], serial=serial)
    emit({"ok": True, "serial": serial, "direction": args.direction, "duration": args.duration, "from": [x1, y1], "to": [x2, y2]}, 0)


def cmd_screenshot(args):
    serial, _devices = pick_serial(args.serial)
    out_path = resolve(args.out)
    directory = os.path.dirname(out_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    remote = "/sdcard/jobagent_shot.png"
    _adb(["shell", "screencap", "-p", remote], serial=serial)
    pull = _adb(["pull", remote, out_path], serial=serial)
    _adb(["shell", "rm", "-f", remote], serial=serial)
    if not os.path.exists(out_path) or os.path.getsize(out_path) == 0:
        emit({"ok": False, "error": "截图失败：%s" % pull["stderr"].strip()[:200]}, 1)
    emit(
        {
            "ok": True,
            "serial": serial,
            "saved": rel_path(out_path),
            "bytes": os.path.getsize(out_path),
            "note": "截图可能含手机号/身份信息，只允许放 logs/screens/（已被 .gitignore 排除）",
        },
        0,
    )


def cmd_text(args):
    serial, _devices = pick_serial(args.serial)
    if not all(ord(char) < 128 for char in args.value):
        emit(
            {
                "ok": False,
                "error": "adb shell input text 只支持 ASCII，中文会变成乱码或直接失败",
                "options": [
                    "1) 由你在手机上手动输入（默认，最稳）",
                    "2) 改用 ASCII 关键词搜索",
                    "3) 安装 ADBKeyboard 并切换输入法（会改系统输入法，需单独授权）",
                ],
            },
            1,
        )
    escaped = args.value.replace(" ", "%s")
    _adb(["shell", "input", "text", escaped], serial=serial)
    emit({"ok": True, "serial": serial, "text": args.value, "at": now_iso()}, 0)


def cmd_key(args):
    serial, _devices = pick_serial(args.serial)
    if args.name not in KEYCODES:
        emit({"ok": False, "error": "按键只能是 %s" % "/".join(KEYCODES)}, 2)
    _adb(["shell", "input", "keyevent", KEYCODES[args.name]], serial=serial)
    emit({"ok": True, "serial": serial, "key": args.name, "keycode": KEYCODES[args.name]}, 0)


def cmd_wait(args):
    serial, _devices = pick_serial(args.serial)
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        try:
            nodes, _local = dump_ui(serial)
        except RuntimeError:
            nodes = []
        if match_nodes(nodes, text=args.text, node_id=args.id):
            emit({"ok": True, "serial": serial, "found": args.text or args.id, "waited": round(args.timeout - max(0, deadline - time.time()), 1)}, 0)
        time.sleep(args.interval)
    emit({"ok": False, "error": "等待超时：界面上没有出现 %r" % (args.text or args.id)}, 1)


def cmd_browse(args):
    """连续下滑浏览并记录每屏文本（只读，不点击任何按钮）。"""
    serial, _devices = pick_serial(args.serial)
    out_path = resolve(args.out)
    directory = os.path.dirname(out_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    records = []
    for index in range(args.rounds):
        try:
            nodes, _local = dump_ui(serial)
        except RuntimeError as exc:
            records.append({"round": index + 1, "error": str(exc), "at": now_iso()})
            break
        texts = []
        seen = set()
        for node in nodes:
            value = node["text"] or node["desc"]
            if value and value not in seen:
                seen.add(value)
                texts.append(value)
        records.append(
            {
                "round": index + 1,
                "at": now_iso(),
                "text_count": len(texts),
                "texts": texts[: args.max_texts],
            }
        )
        if index < args.rounds - 1:
            _swipe_quiet(serial, args.direction, args.duration)
            time.sleep(args.interval)
    with open(out_path, "w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    emit(
        {
            "ok": True,
            "serial": serial,
            "rounds": len(records),
            "interval": args.interval,
            "saved": rel_path(out_path),
            "note": "只记录屏幕文本，未点击任何元素；文本内容由 Skill 侧解析成岗位卡片",
        },
        0,
    )


def _swipe_quiet(serial, direction, duration):
    size = screen_size(serial) or {"width": 1080, "height": 2400}
    width, height = size["width"], size["height"]
    mid = width // 2
    if direction == "up":
        _adb(["shell", "input", "swipe", mid, int(height * 0.75), mid, int(height * 0.30), duration], serial=serial)
    else:
        _adb(["shell", "input", "swipe", mid, int(height * 0.30), mid, int(height * 0.75), duration], serial=serial)


def build_parser():
    parser = argparse.ArgumentParser(description="adb 手机操控封装（白名单）")
    parser.add_argument("--root", help="项目根，默认自动查找")
    parser.add_argument("--serial", help="指定设备序列号（多设备必填）")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("devices", help="列出设备")
    sub.add_parser("status", help="adb 版本 + 设备 + 屏幕信息")

    p = sub.add_parser("packages", help="列出已安装包名")
    p.add_argument("--search", help="按关键字过滤，如 boss")

    p = sub.add_parser("launch", help="启动应用")
    p.add_argument("--package", required=True)

    p = sub.add_parser("dump", help="导出当前界面的可读元素")
    p.add_argument("--contains", help="只看包含该文字的元素")
    p.add_argument("--limit", type=int, default=120)

    p = sub.add_parser("find", help="查找元素并返回坐标")
    p.add_argument("--text")
    p.add_argument("--id")
    p.add_argument("--exact", action="store_true")
    p.add_argument("--limit", type=int, default=10)

    p = sub.add_parser("tap", help="点击元素或坐标")
    p.add_argument("--text")
    p.add_argument("--id")
    p.add_argument("--xy")
    p.add_argument("--exact", action="store_true")
    p.add_argument("--index", type=int, default=0)

    p = sub.add_parser("swipe", help="滑动")
    p.add_argument("direction", choices=["up", "down", "left", "right"])
    p.add_argument("--duration", type=int, default=320)

    p = sub.add_parser("screenshot", help="截图到本地")
    p.add_argument("--out", required=True)

    p = sub.add_parser("text", help="输入 ASCII 文本")
    p.add_argument("value")

    p = sub.add_parser("key", help="发送按键")
    p.add_argument("name")

    p = sub.add_parser("wait", help="等待某元素出现")
    p.add_argument("--text")
    p.add_argument("--id")
    p.add_argument("--timeout", type=float, default=10)
    p.add_argument("--interval", type=float, default=0.8)

    p = sub.add_parser("browse", help="连续下滑浏览并记录每屏文本（只读）")
    p.add_argument("--rounds", type=int, default=5)
    p.add_argument("--interval", type=float, default=2.5)
    p.add_argument("--duration", type=int, default=320)
    p.add_argument("--direction", choices=["up", "down"], default="up")
    p.add_argument("--max-texts", type=int, default=120)
    p.add_argument("--out", default="jobs/raw/mobile-browse.jsonl")

    return parser


HANDLERS = {
    "devices": cmd_devices,
    "status": cmd_status,
    "packages": cmd_packages,
    "launch": cmd_launch,
    "dump": cmd_dump,
    "find": cmd_find,
    "tap": cmd_tap,
    "swipe": cmd_swipe,
    "screenshot": cmd_screenshot,
    "text": cmd_text,
    "key": cmd_key,
    "wait": cmd_wait,
    "browse": cmd_browse,
}


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.root:
        os.environ["JOBAGENT_ROOT"] = os.path.abspath(args.root)
    HANDLERS[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
