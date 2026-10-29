#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""jobagent：JobAgent 的统一入口（能力盘点 / 全流程 / 状态查看）。

为什么需要它
------------
Skill 被装进 WorkBuddy 后，当前工作目录通常不是 JobAgent 项目根，四条长命令
很容易因为 cwd 不对而整体失败。本入口把「找到项目根 → 探测能力 → 按顺序跑流程」
收在一处，Skill 只需要调用这三条短命令。

用法:
    python scripts/jobagent.py doctor [--write] [--root PATH]
    python scripts/jobagent.py run    [--root PATH] [--profile PATH] [--raw PATH]
    python scripts/jobagent.py status [--root PATH]

子命令:
    doctor  探测文件读写、脚本执行、目录完整性等能力，输出能力矩阵（P0 环境盘点）。
            --write 时把结果写回 config/settings.json 的 verified_capabilities。
    run     依次执行 档案校验 → 标准化去重 → 规则评分，汇总退出码与产物路径。
    status  读取投递记录与评分结果，输出各状态计数与待跟进项。

退出码: 0 成功；1 存在失败步骤/数据规则不通过；2 参数或文件缺失。

本脚本不联网、不发邮件、不操作浏览器（回归测试 T12 会静态检查）。
"""

import argparse
import json
import os
import platform
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from common import emit, find_root, now_iso, read_json, rel_path, save_json  # noqa: E402

REQUIRED_DIRS = [
    "config",
    "profile",
    "jobs/raw",
    "applications",
    "resumes",
    "reports",
    "logs",
    "scripts",
    "tests",
    "skills/job-agent/references",
]

# doctor 不去猜这两个能力：只有真实跑过一次目标场景（P4/P5）才算数。
# 默认文案即指向对应规范文件，避免写回时丢失「该按什么标准验证」这一关键信息。
EXTERNAL_CAPABILITIES = {
    "browser_exec": "需在 P4 阶段按 references/browser-policy.md 实测「A 路径只读」后由用户确认",
    "mobile_exec": "需在 P5 阶段按 references/android-adb-policy.md 接入设备并完成只读闭环后由用户确认",
    "email_exec": "需按 references/email-policy.md 连接用户本人邮箱（QQ 邮箱 qq-mail）并成功发出一封邮件后由用户确认",
}


def _stdlib_report(root):
    """静态检查 scripts/ 下的导入是否全部来自标准库。"""
    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib is None:  # Python < 3.10
        return {"ok": True, "evidence": "解释器低于 3.10，跳过标准库比对", "third_party": []}

    local = {name[:-3] for name in os.listdir(os.path.join(root, "scripts")) if name.endswith(".py")}
    third_party = []
    for name in sorted(os.listdir(os.path.join(root, "scripts"))):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(root, "scripts", name), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line.startswith("import "):
                    module = line[7:].split()[0].split(".")[0].split(",")[0]
                elif line.startswith("from ") and " import " in line:
                    module = line[5:].split()[0].split(".")[0]
                else:
                    continue
                if module and module not in stdlib and module not in local:
                    third_party.append({"file": name, "module": module})
    return {
        "ok": not third_party,
        "evidence": "scripts/ 全部导入均来自标准库（无需 pip 安装）" if not third_party else "存在非标准库依赖",
        "third_party": third_party,
    }


def cmd_doctor(root, write):
    checked_at = now_iso()
    missing = [item for item in REQUIRED_DIRS if not os.path.isdir(os.path.join(root, item))]

    capabilities = {}

    # 脚本执行：本进程能跑起来本身就是证据
    capabilities["script_exec"] = {
        "state": "verified",
        "evidence": "%s %s（脚本自身已执行）" % (os.path.basename(sys.executable), platform.python_version()),
        "checked_at": checked_at,
    }

    # 文件读取
    settings_path = os.path.join(root, "config", "settings.json")
    try:
        settings = read_json(settings_path)
        capabilities["file_read"] = {
            "state": "verified",
            "evidence": "成功读取 config/settings.json（%d 个顶层键）" % len(settings),
            "checked_at": checked_at,
        }
    except SystemExit:
        settings = {}
        capabilities["file_read"] = {
            "state": "unavailable",
            "evidence": "无法读取 config/settings.json",
            "checked_at": checked_at,
        }

    # 文件写入：只在 logs/ 下写探针文件，随即删除，不触碰业务数据
    probe_dir = os.path.join(root, "logs")
    probe_path = os.path.join(probe_dir, ".doctor-probe")
    try:
        os.makedirs(probe_dir, exist_ok=True)
        with open(probe_path, "w", encoding="utf-8") as fh:
            fh.write(checked_at)
        os.remove(probe_path)
        capabilities["file_write"] = {
            "state": "verified",
            "evidence": "logs/ 下写入并删除探针文件成功",
            "checked_at": checked_at,
        }
    except OSError as exc:
        capabilities["file_write"] = {
            "state": "unavailable",
            "evidence": "logs/ 写入失败：%s" % exc,
            "checked_at": checked_at,
        }

    # 标准库自检
    stdlib = _stdlib_report(root)
    capabilities["stdlib_only"] = {
        "state": "verified" if stdlib["ok"] else "unavailable",
        "evidence": stdlib["evidence"],
        "checked_at": checked_at,
    }

    # 外部能力：不猜，保持未验证。
    # 若 settings 中已登记过更具体的原因（含实测发现、规范路径等），保留它，只刷新 checked_at，
    # 避免 doctor --write 把用户/维护者写下的证据冲成通用文案。
    existing_caps = (settings or {}).get("verified_capabilities") or {}
    for name, reason in EXTERNAL_CAPABILITIES.items():
        prev = existing_caps.get(name) or {}
        keep = prev.get("state") == "unverified" and prev.get("evidence")
        capabilities[name] = {
            "state": "unverified",
            "evidence": prev["evidence"] if keep else reason,
            "checked_at": checked_at,
        }

    result = {
        "ok": not missing and capabilities["file_read"]["state"] == "verified",
        "checked_at": checked_at,
        "generated_by": "scripts/jobagent.py doctor",
        "root": rel_path(root) if root == find_root() else root,
        "run_mode": settings.get("run_mode", "semi_auto"),
        "missing_dirs": missing,
        "stdlib": stdlib,
        "capabilities": capabilities,
        "notes": [
            "verified 表示本次已取得可复现证据；unverified 表示尚未实测，一律按「未接入」处理。",
            "browser_exec / mobile_exec 只有用户完成 P4/P5 实测并确认后才可改为 verified。",
        ],
    }

    if write:
        if not settings:
            result["ok"] = False
            result["notes"].append("config/settings.json 不可读，未写回能力矩阵")
        else:
            settings["verified_capabilities"] = capabilities
            settings["capability_checked_at"] = checked_at
            settings["updated_at"] = checked_at
            save_json(settings, settings_path)
            result["written_to"] = rel_path(settings_path)

    emit(result, 0 if result["ok"] else 1)


def _run_step(root, script, args):
    proc = subprocess.run(
        [sys.executable, os.path.join(root, "scripts", script)] + [str(item) for item in args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        payload = json.loads(proc.stdout.strip())
    except (json.JSONDecodeError, AttributeError):
        payload = None
    return {"script": script, "code": proc.returncode, "json": payload, "stderr": proc.stderr.strip()}


def cmd_run(root, profile, raw):
    profile = profile or "profile/profile.json"
    raw = raw or "jobs/raw/raw_jobs.json"

    steps = []
    steps.append(
        _run_step(root, "validate_profile.py", ["--profile", profile, "--report", "reports/profile-report.md"])
    )
    steps.append(
        _run_step(
            root,
            "normalize_jobs.py",
            ["--input", raw, "--output", "jobs/jobs.normalized.json", "--report", "reports/dedupe-report.md"],
        )
    )
    if steps[-1]["code"] == 0:
        steps.append(
            _run_step(
                root,
                "score_jobs.py",
                [
                    "--jobs", "jobs/jobs.normalized.json",
                    "--profile", profile,
                    "--config", "config/scoring.json",
                    "--output", "jobs/jobs.scored.json",
                    "--report", "reports/scored-report.md",
                ],
            )
        )
    else:
        steps.append({"script": "score_jobs.py", "code": None, "json": None, "stderr": "前置标准化失败，已跳过"})

    failed = [item for item in steps if item["code"] not in (0,)]
    summary = {
        "ok": not failed,
        "generated_at": now_iso(),
        "generated_by": "scripts/jobagent.py run",
        "profile": profile,
        "raw": raw,
        "steps": [
            {
                "script": item["script"],
                "code": item["code"],
                "outputs": {
                    key: item["json"].get(key)
                    for key in ("output", "report", "counts", "count", "confirmed_facts", "warnings")
                    if item["json"] and key in item["json"]
                },
                "stderr": item["stderr"][:400],
            }
            for item in steps
        ],
        "next": "打开 reports/scored-report.md 查看评分明细；选定岗位后再走材料生成与显式确认。",
    }
    emit(summary, 0 if summary["ok"] else 1)


def cmd_status(root):
    apps_path = os.path.join(root, "applications", "applications.json")
    scored_path = os.path.join(root, "jobs", "jobs.scored.json")

    applications = []
    if os.path.exists(apps_path):
        try:
            applications = read_json(apps_path).get("applications") or []
        except SystemExit:
            applications = []

    counts = {}
    for item in applications:
        status = item.get("status") or "未知"
        counts[status] = counts.get(status, 0) + 1

    pending_followups = [
        {
            "application_id": item.get("application_id"),
            "company": item.get("company"),
            "title": item.get("title"),
            "status": item.get("status"),
            "follow_up_at": item.get("follow_up_at"),
        }
        for item in applications
        if item.get("follow_up_at") and item.get("status") not in {"已关闭", "Offer"}
    ]

    ranking = []
    if os.path.exists(scored_path):
        try:
            ranking = read_json(scored_path).get("jobs") or []
        except SystemExit:
            ranking = []

    by_status = {}
    for item in ranking:
        status = item.get("status") or "未知"
        by_status[status] = by_status.get(status, 0) + 1

    emit(
        {
            "ok": True,
            "generated_at": now_iso(),
            "generated_by": "scripts/jobagent.py status",
            "applications_total": len(applications),
            "applications_by_status": counts,
            "follow_ups": pending_followups,
            "scored_total": len(ranking),
            "scored_by_status": by_status,
            "stores": {
                "applications": rel_path(apps_path) if os.path.exists(apps_path) else None,
                "scored": rel_path(scored_path) if os.path.exists(scored_path) else None,
            },
        },
        0,
    )


def main():
    parser = argparse.ArgumentParser(
        description="JobAgent 统一入口：doctor 能力盘点 / run 全流程 / status 状态查看"
    )
    parser.add_argument("--root", help="项目根目录；缺省时按 JOBAGENT_ROOT → 向上查找 → 脚本上级目录解析")
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="探测文件读写/脚本执行等能力（P0 环境盘点）")
    p_doctor.add_argument("--write", action="store_true", help="把能力矩阵写回 config/settings.json")

    p_run = sub.add_parser("run", help="依次执行 校验 → 标准化去重 → 评分")
    p_run.add_argument("--profile", help="档案路径，默认 profile/profile.json")
    p_run.add_argument("--raw", help="原始岗位路径，默认 jobs/raw/raw_jobs.json")

    sub.add_parser("status", help="查看投递状态与评分结果概览")

    args = parser.parse_args()

    if args.root:
        os.environ["JOBAGENT_ROOT"] = os.path.abspath(args.root)

    root = find_root()
    if not os.path.isdir(os.path.join(root, "scripts")):
        emit(
            {
                "ok": False,
                "error": "未找到项目根：%s 下没有 scripts/。请用 --root 指定，或设置环境变量 JOBAGENT_ROOT。" % root,
            },
            2,
        )

    if args.command == "doctor":
        cmd_doctor(root, args.write)
    elif args.command == "run":
        cmd_run(root, args.profile, args.raw)
    elif args.command == "status":
        cmd_status(root)
    else:  # pragma: no cover - argparse 已拦截
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
