#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公共工具：路径解析、JSON 读写、时间、文本归一化。

本模块不直接运行，被 4 个入口脚本导入。
约定：脚本只读输入、写新文件；不联网；不发送任何外部请求。
"""

import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone

# Windows 控制台默认编码可能是 cp936，统一为 UTF-8，避免中文输出乱码。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # pragma: no cover - 非标准 stream
        pass

CST = timezone(timedelta(hours=8))
PUBLISHED_AT_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


def now_iso():
    """当前时间，ISO 8601 带 +08:00 时区。"""
    return datetime.now(CST).replace(microsecond=0).isoformat()


def now_date():
    return datetime.now(CST).strftime("%Y-%m-%d")


def find_root(start=None):
    """定位项目根（数据工作区），供 Skill 从任意工作目录调用。

    解析优先级：
    1. 环境变量 `JOBAGENT_ROOT`（显式指定，最高优先级）；
    2. 从 `start`（默认当前工作目录）向上逐级查找，命中同时含
       `config/settings.json` 与 `scripts/` 的目录；
    3. 兜底：本文件所在目录的上一级（即随脚本一起分发时的项目根）。

    这样把 `skills/job-agent/` 装进 WorkBuddy 后，即使当前工作目录不是项目根，
    脚本仍能靠自己找到数据目录，不会把相对路径拼到错误位置。
    """
    env_root = os.environ.get("JOBAGENT_ROOT")
    if env_root and os.path.isdir(env_root):
        return os.path.abspath(env_root)

    cursor = os.path.abspath(start or os.getcwd())
    while True:
        if os.path.isfile(os.path.join(cursor, "config", "settings.json")) and os.path.isdir(
            os.path.join(cursor, "scripts")
        ):
            return cursor
        parent = os.path.dirname(cursor)
        if parent == cursor:
            break
        cursor = parent

    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def project_root():
    """项目根目录（即数据工作区 JobAgent/）。"""
    return find_root()


def resolve(path):
    """相对路径按项目根解析；绝对路径原样返回。"""
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(project_root(), path))


def rel_path(path):
    """把路径转成相对项目根的 POSIX 形式，用于写入产物与报告。

    产物里的路径不得暴露执行机器的绝对路径（含用户名）：项目内的路径输出为
    `jobs/raw/raw_jobs.json` 这类相对形式，项目外的路径只保留文件名。
    """
    raw = str(path)
    try:
        abs_path = os.path.abspath(raw)
        rel = os.path.relpath(abs_path, project_root())
    except (OSError, ValueError):  # 跨盘符或非法路径
        return os.path.basename(raw)
    if rel.startswith(".."):
        return os.path.basename(raw)
    return rel.replace(os.sep, "/")


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def read_json(path):
    """读取 JSON；文件缺失退出码 2，解析失败退出码 1。"""
    if not os.path.exists(path):
        die("文件不存在: %s" % path, 2)
    try:
        return load_json(path)
    except json.JSONDecodeError as exc:
        die("JSON 解析失败: %s (%s)" % (path, exc), 1)
    except OSError as exc:
        die("读取失败: %s (%s)" % (path, exc), 2)


def save_json(data, path):
    """原子写入：先写 .tmp 再 replace，避免半截文件。"""
    path = str(path)
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def emit(payload, code=0):
    """输出 JSON 结果并按退出码退出。"""
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    sys.exit(code)


def die(message, code=1, **extra):
    payload = {"ok": False, "error": message}
    payload.update(extra)
    emit(payload, code)


def warn(message):
    print("[warn] %s" % message, file=sys.stderr)


def text_of(value):
    """把字符串 / 列表 / 嵌套字典压平成一段文本。"""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(text_of(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(text_of(item) for item in value.values())
    return str(value)


def norm_text(value):
    """用于匹配的归一化文本：NFKC + 小写 + 去掉所有空白。"""
    text = unicodedata.normalize("NFKC", text_of(value)).lower()
    return re.sub(r"\s+", "", text)


def norm_key(value):
    """用于去重键的归一化：NFKC + 小写 + 去掉空白。"""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", "", text)
    return text.lower()


def split_city(location):
    """取地点中的城市部分：'上海·徐汇区'/'上海市浦东新区' -> '上海'。"""
    text = unicodedata.normalize("NFKC", str(location or "")).strip()
    if not text:
        return ""
    text = re.sub(r"[·\-—–－/\\、,，;；()（）\[\]\s]+", "·", text)
    first = re.sub(r"^(中国|中华人民共和国)", "", text.split("·")[0].strip())
    match = re.match(r"^(.{2,4}?市)", first)
    if match:
        return match.group(1)[:-1]
    match = re.match(r"^(.{2,3}?)(?:区|县)", first)
    if match:
        return match.group(1)
    return first


def iso_date(value):
    """把常见日期写法归一成 YYYY-MM-DD；无法识别时返回原值。"""
    text = str(value or "").strip()
    for pattern, fmt in (
        (r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", "%Y-%m-%d"),
        (r"^(\d{4})年(\d{1,2})月(\d{1,2})日$", "%Y-%m-%d"),
        (r"^(\d{4})[-/.](\d{1,2})$", "%Y-%m"),
    ):
        match = re.match(pattern, text)
        if match:
            try:
                parts = [int(g) for g in match.groups()]
                if len(parts) == 3:
                    return datetime(parts[0], parts[1], parts[2]).strftime(fmt)
                return datetime(parts[0], parts[1], 1).strftime(fmt)
            except ValueError:
                return text
    return text
