#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""岗位标准化与去重。

读取原始岗位（手输 / 采集 / 用户提供的链接），统一字段、解析薪资、生成去重键，
合并已有标准化结果后输出 jobs/jobs.normalized.json。原始文件不会被修改。

用法:
    python scripts/normalize_jobs.py --input jobs/raw/raw_jobs.json \
        --output jobs/jobs.normalized.json [--report reports/dedupe-report.md] [--merge]

退出码:
    0 成功
    1 输入没有可处理岗位 / 数据格式错误
    2 参数或文件缺失
"""

import argparse
import hashlib
import json
import os
import re
import unicodedata

from common import (
    emit,
    iso_date,
    now_iso,
    read_json,
    rel_path,
    resolve,
    save_json,
    split_city,
    text_of,
    warn,
)

JOB_STATUS_ENUM = {"待评估", "优先投递", "暂缓", "不匹配", "已过期"}

FIELD_ALIASES = {
    "company": ["company", "employer", "公司", "公司名称"],
    "title": ["title", "position", "job_title", "岗位", "职位", "岗位名称"],
    "location": ["location", "city", "place", "workplace", "地点", "城市", "工作地点"],
    "source_url": ["source_url", "url", "link", "apply_url", "链接"],
    "source": ["source", "channel", "来源"],
    "salary_text": ["salary", "salary_text", "pay", "薪资", "薪水"],
    "requirements": ["requirements", "requirement", "要求", "任职要求"],
    "responsibilities": ["responsibilities", "job_description", "description", "职责", "岗位职责"],
    "degree": ["degree", "education_required", "学历", "学历要求"],
    "experience": ["experience", "experience_required", "经验", "经验要求"],
    "language_requirements": ["language_requirements", "language", "语言要求"],
    "posted_at": ["posted_at", "publish_time", "发布时间"],
    "industry": ["industry", "行业"],
    "job_type": ["job_type", "type", "类型"],
}


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def pick(raw, field):
    for key in FIELD_ALIASES[field]:
        value = raw.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def parse_salary(value):
    """解析薪资文本为数值区间。

    返回 {"salary_min", "salary_max", "salary_period", "salary_month_equivalent"}，
    无法解析时返回 {}。period 取值 month / year / day，金额单位为元。
    """
    if value in (None, "", [], {}):
        return {}
    raw = unicodedata.normalize("NFKC", text_of(value)).strip()
    if not raw:
        return {}
    if re.search(r"面议|保密|待定|competitive|negotiable", raw, re.I):
        return {"salary_text": raw, "salary_unparsed": True}

    cleaned = re.sub(r"\d+(?:\.\d+)?\s*薪", "", raw)  # 去掉“13薪”里的数字
    endpoints = _salary_endpoints(cleaned)
    if not endpoints:
        return {"salary_text": raw, "salary_unparsed": True}

    if re.search(r"(元|块)?\s*/\s*(天|日)|每\s*(天|日)|日薪", cleaned):
        period = "day"
    elif re.search(r"年薪|万\s*/\s*年|/\s*年|每年", cleaned):
        period = "year"
    else:
        period = "month"

    resolved = _resolve_salary_scales(endpoints)
    if len(resolved) > 2:  # 只取区间两端，避免中间的修饰数字干扰
        resolved = [resolved[0], resolved[-1]]
    values = [amount * scale for amount, scale in resolved]
    salary_min, salary_max = int(round(min(values))), int(round(max(values)))
    result_extra = {}
    if salary_min > 0 and salary_max / salary_min > 30:
        # 「8千-1.2万」这类混合单位若解析错，跨度会离谱；不静默采信。
        result_extra["salary_warning"] = "薪资区间跨度异常（%d–%d），需人工核对原文" % (salary_min, salary_max)

    if period == "year":
        month_min, month_max = round(salary_min / 12), round(salary_max / 12)
        basis = "年薪按 12 个月折算，未含年终奖"
    elif period == "day":
        month_min, month_max = round(salary_min * 21), round(salary_max * 21)
        basis = "按每月 21 个工作日折算"
    else:
        month_min, month_max = salary_min, salary_max
        basis = "按月折算"
    monthly = {"min": month_min, "max": month_max, "basis": basis}
    result = {
        "salary_text": raw,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "salary_period": period,
        "salary_month_equivalent": monthly,
    }
    result.update(result_extra)
    return result


# 「万 / 千 / K / W」四种写法都要认；单位必须跟着数字走。
SALARY_TOKEN = re.compile(r"(\d+(?:\.\d+)?)\s*([万wW]|[kK千])?")


def _salary_endpoints(text):
    """按出现顺序返回 [(金额, 倍率或 None)]，倍率为 None 表示原文本没写单位。"""
    items = []
    for match in SALARY_TOKEN.finditer(text):
        amount = float(match.group(1))
        unit = (match.group(2) or "").lower()
        if unit in ("万", "w"):
            scale = 10000
        elif unit in ("千", "k"):
            scale = 1000
        else:
            scale = None
        items.append((amount, scale))
    return items


def _resolve_salary_scales(items):
    """补齐缺失的倍率。

    关键规则：缺失单位时，**数值 ≥ 1000 一律按「元」处理**。
    「8千-1.2万」两端都有单位，各算各的；「8000-1.2万」里的 8000 本来就是元，
    不能因为另一段有“万”就乘一万 —— 那会把 8000 放大成 8000 万。
    """
    explicit = [scale for _amount, scale in items if scale]
    resolved = []
    for amount, scale in items:
        if scale:
            resolved.append((amount, scale))
        elif amount >= 1000:
            resolved.append((amount, 1))
        elif explicit:
            resolved.append((amount, explicit[0]))
        else:
            resolved.append((amount, 1))
    return resolved


def normalize_job(raw, index, default_collected):
    company = unicodedata.normalize("NFKC", text_of(pick(raw, "company"))).strip()
    title = unicodedata.normalize("NFKC", text_of(pick(raw, "title"))).strip()
    location = unicodedata.normalize("NFKC", text_of(pick(raw, "location"))).strip()
    source_url = str(pick(raw, "source_url") or "").strip()
    source = str(pick(raw, "source") or "unknown").strip() or "unknown"
    requirements = text_of(pick(raw, "requirements")).strip()
    responsibilities = text_of(pick(raw, "responsibilities")).strip()
    degree = str(pick(raw, "degree") or "").strip()
    experience = str(pick(raw, "experience") or "").strip()
    language = str(pick(raw, "language_requirements") or "").strip()
    industry = str(pick(raw, "industry") or "").strip()
    job_type = str(pick(raw, "job_type") or "").strip()
    posted_at = iso_date(pick(raw, "posted_at") or "")
    collected_at = str(raw.get("collected_at") or default_collected)

    city = split_city(location)
    dedupe_key = sha1("|".join([company, title, city]).lower())[:10]
    suffix = sha1(source_url)[:4] if source_url else "n%03d" % index
    job_id = "job-%s-%s" % (dedupe_key, suffix)

    missing_info = []
    risk_flags = []
    if not company:
        missing_info.append("公司名称缺失")
    if not title:
        missing_info.append("岗位名称缺失")
    if not location:
        missing_info.append("工作地点缺失")
    if not source_url:
        missing_info.append("原始来源链接缺失")
        risk_flags.append("缺少来源链接，岗位真实性未验证")
    salary = parse_salary(pick(raw, "salary_text"))
    if not salary or salary.get("salary_unparsed"):
        missing_info.append("薪资未标注或无法解析，薪资维度只能给默认分")

    job = {
        "job_id": job_id,
        "dedupe_key": dedupe_key,
        "source": source,
        "source_url": source_url,
        "company": company,
        "title": title,
        "location": location,
        "city": city,
        "industry": industry,
        "job_type": job_type,
        "requirements": requirements,
        "responsibilities": responsibilities,
        "degree": degree,
        "experience": experience,
        "language_requirements": language,
        "posted_at": posted_at,
        "collected_at": collected_at,
        "status": raw.get("status") if raw.get("status") in JOB_STATUS_ENUM else "待评估",
        "risk_flags": risk_flags,
        "missing_info": missing_info,
        "is_duplicate": False,
        "duplicate_of": None,
        "raw_text": "\n".join(
            part for part in [title, company, location, industry, job_type, requirements, responsibilities] if part
        ),
    }
    job.update(salary)
    if "salary_text" not in job:
        job["salary_text"] = ""
    return job


def load_input(path):
    """输入可以是单个 JSON 文件，也可以是目录（读取其中全部 *.json）。"""
    entries = []
    if os.path.isdir(path):
        for name in sorted(os.listdir(path)):
            if name.lower().endswith(".json"):
                entries.extend(load_input(os.path.join(path, name)))
        return entries
    data = read_json(path)
    raw_jobs = data.get("jobs") if isinstance(data, dict) else data
    if not isinstance(raw_jobs, list):
        return entries
    default_collected = (
        str(data.get("collected_at") or now_iso()) if isinstance(data, dict) else now_iso()
    )
    for index, raw in enumerate(raw_jobs):
        if isinstance(raw, dict):
            raw = dict(raw)
            raw["_default_collected"] = default_collected
            entries.append((raw, index))
    return entries


def build_parser():
    parser = argparse.ArgumentParser(description="岗位字段标准化与去重（不修改原始数据）。")
    parser.add_argument("--input", required=True, help="原始岗位 JSON 文件或目录")
    parser.add_argument("--output", default="jobs/jobs.normalized.json", help="标准化结果输出路径")
    parser.add_argument("--report", default=None, help="可选：输出 Markdown 去重报告")
    parser.add_argument(
        "--merge",
        action="store_true",
        help="与已有标准化结果合并（默认按输入整体重建；原始岗位文件始终不会被修改）",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    input_path = resolve(args.input)
    output_path = resolve(args.output)
    if not os.path.exists(input_path):
        emit({"ok": False, "error": "输入路径不存在: %s" % input_path}, 2)

    entries = load_input(input_path)
    incoming = []
    skipped = []
    for index, (raw, position) in enumerate(entries):
        default_collected = raw.pop("_default_collected", now_iso())
        job = normalize_job(raw, index, default_collected)
        if not job["company"] and not job["title"]:
            skipped.append({"index": position, "reason": "公司名称与岗位名称同时缺失"})
            continue
        incoming.append(job)

    if not incoming:
        emit({"ok": False, "error": "输入中没有可处理的岗位", "skipped": skipped}, 1)

    existing_jobs = []
    if os.path.exists(output_path) and args.merge:
        try:
            with open(output_path, "r", encoding="utf-8-sig") as fh:
                previous = json.load(fh)
            existing_jobs = previous.get("jobs") or [] if isinstance(previous, dict) else []
        except (json.JSONDecodeError, OSError) as exc:
            warn("已有标准化结果无法读取，按空结果处理: %s" % exc)
            existing_jobs = []

    by_id = {job.get("job_id"): job for job in existing_jobs if isinstance(job, dict)}
    added = updated = 0
    for job in incoming:
        previous = by_id.get(job["job_id"])
        if previous:
            preserved_status = previous.get("status") if previous.get("status") in JOB_STATUS_ENUM else None
            merged = {**previous, **job}
            if preserved_status and preserved_status != "待评估":
                merged["status"] = preserved_status
            # 新数据进入后需要重新评分
            for field in ("match_score", "score_breakdown"):
                merged.pop(field, None)
            by_id[job["job_id"]] = merged
            updated += 1
        else:
            by_id[job["job_id"]] = job
            added += 1

    jobs = list(by_id.values())
    jobs.sort(key=lambda item: (str(item.get("collected_at") or ""), str(item.get("source_url") or "")))

    groups = {}
    for job in jobs:
        groups.setdefault(job["dedupe_key"], []).append(job)
    duplicates = []
    for dedupe_key, group in groups.items():
        canonical = group[0]
        canonical["is_duplicate"] = False
        canonical["duplicate_of"] = None
        for other in group[1:]:
            other["is_duplicate"] = True
            other["duplicate_of"] = canonical["job_id"]
            duplicates.append(
                {
                    "dedupe_key": dedupe_key,
                    "canonical_job_id": canonical["job_id"],
                    "duplicate_job_id": other["job_id"],
                    "company": other["company"],
                    "title": other["title"],
                    "sources": [canonical.get("source_url"), other.get("source_url")],
                    "note": "疑似重复：公司/岗位/城市相同，保留两条来源以便核对",
                }
            )

    output = {
        "schema_version": "1.0",
        "generated_at": now_iso(),
        "generated_by": "scripts/normalize_jobs.py",
        "source_input": rel_path(input_path),
        "counts": {
            "input_jobs": len(entries),
            "added": added,
            "updated": updated,
            "total": len(jobs),
            "unique": len(groups),
            "duplicates": len(duplicates),
            "skipped": len(skipped),
        },
        "jobs": jobs,
    }
    save_json(output, output_path)

    result = {
        "ok": True,
        "output": rel_path(output_path),
        "generated_at": output["generated_at"],
        "counts": output["counts"],
        "added_job_ids": [job["job_id"] for job in incoming if job["job_id"] not in {j.get("job_id") for j in existing_jobs}],
        "duplicates": duplicates,
        "skipped": skipped,
    }

    if args.report:
        report_path = resolve(args.report)
        lines = [
            "# 岗位标准化与去重报告",
            "",
            "- 生成时间：%s" % output["generated_at"],
            "- 输入：`%s`" % rel_path(input_path),
            "- 输出：`%s`" % rel_path(output_path),
            "- 统计：输入 %(input_jobs)d 条 / 新增 %(added)d / 更新 %(updated)d / 合计 %(total)d / 唯一岗位 %(unique)d / 疑似重复 %(duplicates)d / 跳过 %(skipped)d"
            % output["counts"],
            "",
            "## 岗位清单",
            "",
            "| job_id | 公司 | 岗位 | 地点 | 薪资 | 来源 | 去重键 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for job in jobs:
            salary = (
                "%s-%s %s" % (job.get("salary_min"), job.get("salary_max"), job.get("salary_period") or "")
                if job.get("salary_min") is not None
                else (job.get("salary_text") or "未标注")
            )
            lines.append(
                "| %s | %s | %s | %s | %s | %s | %s |"
                % (
                    job["job_id"],
                    job["company"],
                    job["title"],
                    job["location"],
                    salary,
                    job["source"],
                    job["dedupe_key"],
                )
            )
        lines += ["", "## 疑似重复（%d）" % len(duplicates)]
        if duplicates:
            for item in duplicates:
                lines.append(
                    "- `%s` 与 `%s` 疑似同一岗位（%s / %s）：%s"
                    % (item["canonical_job_id"], item["duplicate_job_id"], item["company"], item["title"], item["note"])
                )
        else:
            lines.append("- 无")
        lines += ["", "## 数据缺失提示"]
        missing_lines = []
        for job in jobs:
            if job.get("missing_info"):
                missing_lines.append("- `%s`：%s" % (job["job_id"], "；".join(job["missing_info"])))
        lines += missing_lines or ["- 无"]
        lines += ["", "> 原始岗位文件未被修改；缺失字段一律按未知处理，不得推测补全。"]
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        result["report"] = rel_path(report_path)

    emit(result, 0)


if __name__ == "__main__":
    main()
