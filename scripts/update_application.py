#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""投递状态机：唯一允许修改 applications/*.json 的入口。

规则：
- 只允许 status 迁移表中列出的迁移；
- 状态改为“已提交”必须有可验证证据（--evidence）；
- 同一岗位已有提交类记录时，再次提交会被拒绝（防止重复申请）；
- 写入前生成 applications.json.bak，并追加 logs/applications.jsonl 审计日志。

用法:
    python scripts/update_application.py --job-id job-xxx --status 待准备 \
        [--notes "..."] [--evidence "..."] [--resume-version v1] \
        [--store applications/applications.json]

退出码:
    0 成功
    1 状态迁移非法 / 缺少证据 / 重复提交风险
    2 参数或文件缺失
"""

import argparse
import json
import os
import shutil

from common import emit, now_date, now_iso, read_json, rel_path, resolve, save_json

TRANSITIONS = {
    "待准备": {"待确认", "已关闭"},
    "待确认": {"执行中", "待准备", "已关闭"},
    "执行中": {"已提交", "需人工介入", "失败"},
    "需人工介入": {"执行中", "失败", "已关闭"},
    "失败": {"执行中", "已关闭"},
    "已提交": {"笔试", "面试", "拒绝", "Offer", "已关闭"},
    "笔试": {"面试", "拒绝", "已关闭"},
    "面试": {"Offer", "拒绝", "已关闭"},
}
INITIAL_STATUS = "待准备"
SUBMITTED_STATES = {"已提交", "笔试", "面试", "Offer"}
ALL_STATUSES = set(TRANSITIONS) | set(TRANSITIONS["已提交"])


def build_parser():
    parser = argparse.ArgumentParser(description="投递记录状态更新（唯一写入口，可审计）。")
    parser.add_argument("--job-id", required=True, help="关联岗位 job_id")
    parser.add_argument("--status", required=True, help="目标状态，见状态机迁移表")
    parser.add_argument("--notes", default=None, help="人工备注")
    parser.add_argument("--evidence", default=None, help="提交证据（确认页面/邮件引用），改为已提交时必填")
    parser.add_argument("--resume-version", default=None, help="实际使用的简历版本")
    parser.add_argument("--cover-letter-version", default=None, help="求职信版本")
    parser.add_argument("--next-action", default=None, help="下一步行动")
    parser.add_argument("--follow-up-at", default=None, help="跟进时间（ISO 8601）")
    parser.add_argument("--company", default=None, help="岗位公司（缺省时从岗位库查找）")
    parser.add_argument("--title", default=None, help="岗位名称（缺省时从岗位库查找）")
    parser.add_argument("--store", default="applications/applications.json", help="投递记录文件")
    parser.add_argument(
        "--log",
        default="logs/applications.jsonl",
        help="审计日志路径（JSONL，追加写入；测试时指向临时目录）",
    )
    return parser


def find_job(job_id):
    """从已评分/标准化岗位中补齐公司、岗位名。"""
    for candidate in ("jobs/jobs.scored.json", "jobs/jobs.normalized.json"):
        path = resolve(candidate)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        jobs = data.get("jobs") if isinstance(data, dict) else data
        for job in jobs or []:
            if isinstance(job, dict) and job.get("job_id") == job_id:
                return job.get("company") or "", job.get("title") or ""
    return "", ""


def next_application_id(applications):
    prefix = "app-%s-" % now_date().replace("-", "")
    existing = [item.get("application_id") or "" for item in applications]
    sequence = 0
    for application_id in existing:
        if application_id.startswith(prefix):
            try:
                sequence = max(sequence, int(application_id.rsplit("-", 1)[-1]))
            except ValueError:
                continue
    return "%s%04d" % (prefix, sequence + 1)


def _append_line(path, record):
    """追加一行 JSONL 并 fsync，保证崩溃前已落盘。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def append_audit(record, log_path):
    _append_line(resolve(log_path), record)


def _preflight(path):
    """写入前确认目录可创建且可写，返回错误文本（空串表示通过）。

    先检查再动手：如果日志目录不可写，宁可在改状态之前失败，
    也不要出现「状态已更新、审计写不进去」的不可核对状态。
    """
    directory = os.path.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as exc:
        return "无法创建目录 %s：%s" % (directory, exc)
    probe = os.path.join(directory, ".write_probe")
    try:
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("probe")
        os.remove(probe)
    except OSError as exc:
        return "目录不可写 %s：%s" % (directory, exc)
    return ""


def _new_event_id():
    return "%s-%s" % (now_iso().replace(":", "").replace("-", "").replace("+", "")[:15], os.urandom(3).hex())


def _pending_events(log_path):
    """找出有 intent 但没有 committed/aborted 的事件（上次写入中途中断）。"""
    if not os.path.exists(log_path):
        return []
    intents, closed = {}, set()
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, dict):
                    continue
                event = record.get("event_id")
                if not event:
                    continue
                if record.get("phase") == "intent":
                    intents[event] = record
                elif record.get("phase") in ("committed", "aborted"):
                    closed.add(event)
    except OSError:
        return []
    return [
        {"event_id": key, "at": (value or {}).get("at"), "job_id": (value or {}).get("job_id")}
        for key, value in intents.items()
        if key not in closed
    ]


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.status not in ALL_STATUSES:
        emit({"ok": False, "error": "未知状态: %s，允许值: %s" % (args.status, "/".join(sorted(ALL_STATUSES)))}, 1)
    if args.status == "已提交" and not (args.evidence or "").strip():
        emit(
            {
                "ok": False,
                "error": "改为“已提交”必须提供 --evidence（确认页面、邮件引用等可验证证据）",
                "hint": "仅点击提交按钮不算提交成功；没有平台确认前保持“执行中”或改为“需人工介入”",
            },
            1,
        )

    store_path = resolve(args.store)
    if os.path.exists(store_path):
        store = read_json(store_path)
    else:
        store = {"schema_version": "1.0", "updated_at": now_iso(), "applications": []}
    applications = store.get("applications")
    if not isinstance(applications, list):
        emit({"ok": False, "error": "投递记录结构错误：applications 必须是数组"}, 1)

    current = None
    for item in applications:
        if isinstance(item, dict) and item.get("job_id") == args.job_id:
            current = item
    previous_status = current.get("status") if current else None

    if current is None:
        if args.status != INITIAL_STATUS:
            emit(
                {
                    "ok": False,
                    "error": "该岗位还没有投递记录，首次记录状态必须为“%s”" % INITIAL_STATUS,
                    "hint": "请先创建记录，再按状态机推进",
                },
                1,
            )
        submitted = [
            item
            for item in applications
            if isinstance(item, dict) and item.get("job_id") == args.job_id and item.get("status") in SUBMITTED_STATES
        ]
        if submitted:
            emit({"ok": False, "error": "该岗位已有提交记录，拒绝重复申请"}, 1)
        company, title = args.company or "", args.title or ""
        if not company or not title:
            looked_company, looked_title = find_job(args.job_id)
            company = company or looked_company
            title = title or looked_title
        current = {
            "application_id": next_application_id(applications),
            "job_id": args.job_id,
            "company": company,
            "title": title,
            "status": INITIAL_STATUS,
            "resume_version": "",
            "cover_letter_version": "",
            "prepared_at": "",
            "submitted_at": "",
            "submission_evidence": "",
            "next_action": "",
            "follow_up_at": "",
            "notes": "",
            "outcome": "",
            "history": [],
        }
        applications.append(current)
        previous_status = None
    else:
        if args.status == INITIAL_STATUS and previous_status in SUBMITTED_STATES:
            emit(
                {
                    "ok": False,
                    "error": "该岗位已有提交记录（当前状态：%s），拒绝重复申请" % previous_status,
                    "hint": "如需确认是否已投递，查看记录中的 submission_evidence；不要重复提交",
                },
                1,
            )
        allowed = TRANSITIONS.get(previous_status, set())
        if args.status not in allowed:
            emit(
                {
                    "ok": False,
                    "error": "非法状态迁移：%s -> %s" % (previous_status, args.status),
                    "allowed_next": sorted(allowed),
                },
                1,
            )
        if args.status == "已提交":
            duplicate = [
                item
                for item in applications
                if isinstance(item, dict)
                and item.get("job_id") == args.job_id
                and item.get("status") in SUBMITTED_STATES
                and item is not current
            ]
            if duplicate:
                emit({"ok": False, "error": "同一岗位已存在提交记录，拒绝重复提交"}, 1)

    at = now_iso()
    current["status"] = args.status
    if args.evidence is not None:
        current["submission_evidence"] = args.evidence.strip()
    if args.resume_version is not None:
        current["resume_version"] = args.resume_version
    if args.cover_letter_version is not None:
        current["cover_letter_version"] = args.cover_letter_version
    if args.next_action is not None:
        current["next_action"] = args.next_action
    if args.follow_up_at is not None:
        current["follow_up_at"] = args.follow_up_at
    if args.notes is not None:
        current["notes"] = args.notes
    if args.status == "已提交":
        current["submitted_at"] = current.get("submitted_at") or at
    if args.status == "待确认":
        current["prepared_at"] = current.get("prepared_at") or at

    history = current.setdefault("history", [])
    history.append({"at": at, "from": previous_status or "", "to": args.status, "note": args.notes or ""})
    store["schema_version"] = store.get("schema_version") or "1.0"
    store["updated_at"] = at

    event_id = _new_event_id()
    log_path = resolve(args.log)
    pending_before = _pending_events(log_path)

    preflight_error = _preflight(log_path)
    if preflight_error:
        emit(
            {
                "ok": False,
                "event_id": event_id,
                "error": "审计日志不可写，已中止，状态未做任何修改：%s" % preflight_error,
            },
            1,
        )

    # 先写 intent，再改状态。顺序反了就可能在第二步失败时留下「状态已改、无记录」，
    # 而 intent 先行最坏只留下「有意图、无结果」的痕迹，可被 _pending_events 检出。
    try:
        _append_line(
            log_path,
            {
                "at": at,
                "phase": "intent",
                "event_id": event_id,
                "job_id": args.job_id,
                "application_id": current.get("application_id"),
                "from": previous_status or "",
                "to": args.status,
                "note": args.notes or "",
                "store": rel_path(store_path),
            },
        )
    except OSError as exc:
        emit(
            {
                "ok": False,
                "event_id": event_id,
                "error": "审计日志写入失败，已中止，状态未做任何修改：%s" % exc,
            },
            1,
        )

    backup_path = None
    try:
        if os.path.exists(store_path):
            backup_path = store_path + ".bak"
            shutil.copy2(store_path, backup_path)
        save_json(store, store_path)
    except OSError as exc:
        try:
            _append_line(
                log_path,
                {"at": now_iso(), "phase": "aborted", "event_id": event_id, "job_id": args.job_id, "error": str(exc)},
            )
        except OSError:
            pass
        emit(
            {
                "ok": False,
                "event_id": event_id,
                "error": "状态写入失败，业务状态未改变（备份保留原文件），审计已记 aborted：%s" % exc,
            },
            1,
        )

    audit_committed = True
    try:
        _append_line(
            log_path,
            {"at": now_iso(), "phase": "committed", "event_id": event_id, "job_id": args.job_id},
        )
    except OSError:
        # 业务状态已落盘、intent 已存在，可追溯；只缺一个收尾标记。
        audit_committed = False

    result = {
        "ok": True,
        "event_id": event_id,
        "application_id": current.get("application_id"),
        "job_id": args.job_id,
        "previous_status": previous_status or "",
        "status": args.status,
        "history_count": len(history),
        "backup": rel_path(backup_path) if backup_path else "",
        "store": rel_path(store_path),
        "audit": {
            "log": rel_path(log_path),
            "intent": True,
            "committed": audit_committed,
        },
        "warnings": [],
    }
    if not audit_committed:
        result["warnings"].append(
            "业务状态已更新，但审计收尾标记写入失败；日志中该事件的 intent 行（%s）仍可追溯" % event_id
        )
    if pending_before:
        result["warnings"].append(
            "检测到 %d 条历史未完成事件（有 intent 无 committed/aborted），建议核对：%s"
            % (len(pending_before), "、".join(item["event_id"] for item in pending_before[:5]))
        )
    if not current.get("company") or not current.get("title"):
        result["warnings"].append("岗位公司/名称缺失，建议补全后再生成材料")
    if args.status == "已提交" and not current.get("resume_version"):
        result["warnings"].append("未登记简历版本，材料可追溯性不足")
    emit(result, 0)


if __name__ == "__main__":
    main()
