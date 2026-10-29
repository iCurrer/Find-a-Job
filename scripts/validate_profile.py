#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验个人档案结构，列出缺失字段、待确认事实和过期资料。

用法:
    python scripts/validate_profile.py [--profile profile/profile.json] [--report reports/profile-report.md]

退出码:
    0 结构合法（可能仍有 warnings / pending_facts）
    1 存在结构错误（例如缺少必填字段、枚举值非法）
    2 参数或文件缺失
"""

import argparse
import re
import sys

from common import (
    emit,
    now_iso,
    read_json,
    rel_path,
    resolve,
)

STATUS_ENUM = {"confirmed", "pending", "expired"}
DEGREE_ENUM = {"不限", "大专", "本科", "硕士", "博士"}
SKILL_LEVEL_ENUM = {"了解", "使用过", "熟练"}
CERT_STATE_ENUM = {"已取得", "备考中", "未通过", "计划中"}
KIND_ENUM = {"internship", "project", "parttime", "fulltime"}
SALARY_PERIOD_ENUM = {"month", "year", "day"}

TOP_REQUIRED = {
    "schema_version": str,
    "profile_id": str,
    "updated_at": str,
    "basics": dict,
    "education": list,
    "experience": list,
    "skills": list,
    "certifications": list,
    "preferences": dict,
    "career_goals": dict,
    "constraints": dict,
    "facts_sources": list,
    "open_questions": list,
}

ITEM_RULES = {
    "education": {
        "required": ["id", "school", "major", "degree", "start", "end", "status"],
        "enums": {"degree": DEGREE_ENUM, "status": STATUS_ENUM},
    },
    "experience": {
        "required": ["id", "kind", "org", "role", "start", "end", "highlights", "status"],
        "enums": {"kind": KIND_ENUM, "status": STATUS_ENUM},
    },
    "skills": {
        "required": ["name", "level", "evidence", "status"],
        "enums": {"level": SKILL_LEVEL_ENUM, "status": STATUS_ENUM},
    },
    "certifications": {
        "required": ["name", "state", "date", "status"],
        "enums": {"state": CERT_STATE_ENUM, "status": STATUS_ENUM},
    },
    "facts_sources": {
        "required": ["fact_id", "fact", "source", "confirmed_by", "confirmed_at"],
        "enums": {},
    },
}

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?([+-]\d{2}:?\d{2}|Z)?)?$")


def check_type(value, expected):
    if expected is str:
        return isinstance(value, str)
    if expected is dict:
        return isinstance(value, dict)
    if expected is list:
        return isinstance(value, list)
    if expected is (int, float):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def build_parser():
    parser = argparse.ArgumentParser(
        description="校验 JobAgent 个人档案结构，输出缺失字段与待确认事实。"
    )
    parser.add_argument("--profile", default="profile/profile.json", help="档案 JSON 路径")
    parser.add_argument("--report", default=None, help="可选：输出 Markdown 校验报告路径")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    profile_path = resolve(args.profile)
    profile = read_json(profile_path)
    if not isinstance(profile, dict):
        emit({"ok": False, "error": "档案顶层必须是 JSON 对象"}, 1)

    errors = []
    warnings = []
    missing_fields = []
    pending_facts = []

    for key, expected in TOP_REQUIRED.items():
        if key not in profile:
            errors.append("缺少顶层字段: %s" % key)
            missing_fields.append(key)
        elif not check_type(profile[key], expected):
            errors.append("字段类型错误: %s 应为 %s" % (key, expected.__name__))

    updated_at = profile.get("updated_at", "")
    if updated_at and not ISO_RE.match(str(updated_at)):
        warnings.append("updated_at 不是 ISO 8601 时间: %s" % updated_at)

    # 逐条检查教育 / 经历 / 技能 / 证书 / 事实来源
    for section, rule in ITEM_RULES.items():
        items = profile.get(section)
        if not isinstance(items, list):
            continue
        if not items:
            warnings.append("%s 为空，生成材料前需要补充" % section)
        for index, item in enumerate(items):
            where = "%s[%d]" % (section, index)
            if not isinstance(item, dict):
                errors.append("%s 必须是对象" % where)
                continue
            for field in rule["required"]:
                if field not in item:
                    errors.append("%s 缺少字段: %s" % (where, field))
                    missing_fields.append("%s.%s" % (where, field))
            for field, allowed in rule["enums"].items():
                value = item.get(field)
                if value is not None and value not in allowed:
                    errors.append(
                        "%s.%s 取值非法: %r，允许值 %s"
                        % (where, field, value, "/".join(sorted(allowed)))
                    )
            status = item.get("status")
            if status == "pending":
                label = item.get("name") or item.get("role") or item.get("fact") or item.get("school")
                scope = section[:-1] if section.endswith("s") else section
                pending_facts.append(
                    {"path": where, "kind": scope, "label": label, "reason": "待确认，不得写入对外材料"}
                )
            elif status == "expired":
                warnings.append("%s 状态为 expired（过期资料），需要重新确认" % where)
            if section == "experience":
                highlights = item.get("highlights")
                if highlights is not None and not isinstance(highlights, list):
                    errors.append("%s.highlights 必须是字符串列表" % where)

    # 偏好与约束
    preferences = profile.get("preferences") or {}
    salary_min = preferences.get("salary_min")
    if salary_min is not None and not isinstance(salary_min, (int, float)):
        errors.append("preferences.salary_min 必须是数字或 null")
    period = preferences.get("salary_period")
    if period is not None and period not in SALARY_PERIOD_ENUM:
        errors.append("preferences.salary_period 取值非法: %r" % period)
    if not preferences.get("cities"):
        warnings.append("preferences.cities 为空，无法判断地点是否符合")
    if salary_min is None:
        warnings.append("preferences.salary_min 未填写，薪资维度将只能给默认分")

    constraints = profile.get("constraints") or {}
    commute = constraints.get("max_commute_minutes")
    if commute is not None and not isinstance(commute, (int, float)):
        errors.append("constraints.max_commute_minutes 必须是数字或 null")

    basics = profile.get("basics") or {}
    for field in ("name", "phone", "email", "city"):
        if not str(basics.get(field) or "").strip():
            warnings.append("basics.%s 未填写（对外材料提交前必须补全）" % field)

    # 事实可追溯性
    facts = profile.get("facts_sources") or []
    confirmed_count = 0
    for section in ("education", "experience", "skills", "certifications"):
        for item in profile.get(section) or []:
            if isinstance(item, dict) and item.get("status") == "confirmed":
                confirmed_count += 1
    if confirmed_count and not facts:
        warnings.append("存在 confirmed 事实但 facts_sources 为空：关键事实缺少来源登记")
    if any(item.get("status") == "pending" for item in profile.get("skills") or [] if isinstance(item, dict)):
        warnings.append("存在待确认技能（pending），不得在简历中写成熟练或已掌握")

    if profile.get("open_questions"):
        warnings.append("仍有 %d 个待确认问题，见 profile.open_questions" % len(profile["open_questions"]))

    result = {
        "ok": not errors,
        "checked_at": now_iso(),
        "profile": rel_path(profile_path),
        "errors": errors,
        "warnings": warnings,
        "missing_fields": missing_fields,
        "pending_facts": pending_facts,
        "confirmed_facts": confirmed_count,
        "open_questions": profile.get("open_questions") or [],
    }

    if args.report:
        report_path = resolve(args.report)
        lines = [
            "# 个人档案校验报告",
            "",
            "- 档案：`%s`" % rel_path(profile_path),
            "- 校验时间：%s" % result["checked_at"],
            "- 结论：%s" % ("通过" if result["ok"] else "存在结构错误"),
            "",
            "## 结构错误（%d）" % len(errors),
        ]
        lines += ["- " + err for err in errors] or ["- 无"]
        lines += ["", "## 警告（%d）" % len(warnings)]
        lines += ["- " + item for item in warnings] or ["- 无"]
        lines += ["", "## 待确认事实（%d）" % len(pending_facts)]
        lines += ["- `%s` %s" % (fact["path"], fact["label"]) for fact in pending_facts] or ["- 无"]
        lines += ["", "## 待确认问题（%d）" % len(result["open_questions"])]
        lines += ["- " + question for question in result["open_questions"]] or ["- 无"]
        lines += ["", "> 说明：pending 事实只能出现在“待确认清单”中，不能写入简历、求职信或网申答案。"]
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        result["report"] = rel_path(report_path)

    emit(result, 0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
