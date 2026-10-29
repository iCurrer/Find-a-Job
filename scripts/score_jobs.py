#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基于规则的岗位评分（可解释、可重复、硬性门槛独立阻断）。

输入：标准化岗位 + 已确认档案 + 权重配置
输出：jobs/jobs.scored.json、可选 Markdown 报告

用法:
    python scripts/score_jobs.py --jobs jobs/jobs.normalized.json \
        --profile profile/profile.json --config config/scoring.json \
        --output jobs/jobs.scored.json --report reports/scored-report.md

退出码:
    0 成功
    1 数据错误（权重不合法、岗位/档案结构错误）
    2 参数或文件缺失

说明：match_score 是可解释的匹配度，不是录取概率。
"""

import argparse
import os
import re

from common import (
    emit,
    norm_key,
    norm_text,
    now_iso,
    read_json,
    rel_path,
    resolve,
    save_json,
    split_city,
    text_of,
)

DOMAIN_KEYWORDS = [
    "数据分析",
    "数据开发",
    "数据挖掘",
    "商业分析",
    "数据产品",
    "产品运营",
    "产品经理",
    "运营",
    "算法",
    "机器学习",
    "测试",
    "前端",
    "后端",
    "全栈",
    "Java",
    "Python",
    "市场",
    "销售",
    "人力资源",
    "财务",
    "设计",
    "研究",
    "咨询",
]

CERT_KEYWORDS = [
    "教师资格证",
    "教师资格",
    "CPA",
    "ACCA",
    "CFA",
    "PMP",
    "软考",
    "计算机二级",
    "CET-4",
    "CET-6",
    "雅思",
    "托福",
]

DIMENSION_ORDER = [
    "responsibilities_match",
    "hard_requirements",
    "career_value",
    "preference_fit",
    "compensation",
    "source_credibility",
]


def build_parser():
    parser = argparse.ArgumentParser(description="规则化岗位评分：六维加权 + 硬性门槛阻断。")
    parser.add_argument("--jobs", default="jobs/jobs.normalized.json", help="标准化岗位 JSON")
    parser.add_argument("--profile", default="profile/profile.json", help="个人档案 JSON")
    parser.add_argument("--config", default="config/scoring.json", help="评分权重配置")
    parser.add_argument("--settings", default="config/settings.json", help="运行配置（可信来源白名单）")
    parser.add_argument("--output", default="jobs/jobs.scored.json", help="评分结果输出路径")
    parser.add_argument("--report", default=None, help="可选：Markdown 评分报告")
    parser.add_argument(
        "--include-duplicates",
        action="store_true",
        help="对疑似重复岗位也评分（默认跳过重复项）",
    )
    return parser


def load_config(path):
    config = read_json(path)
    if not isinstance(config, dict):
        emit({"ok": False, "error": "评分配置顶层必须是对象"}, 1)
    weights = config.get("weights") or {}
    missing = [key for key in DIMENSION_ORDER if key not in weights]
    if missing:
        emit({"ok": False, "error": "评分配置缺少权重: %s" % ",".join(missing)}, 1)
    total = sum(float(weights[key]) for key in DIMENSION_ORDER)
    if abs(total - 1.0) > 0.01:
        emit({"ok": False, "error": "权重之和必须为 1.0，当前为 %.3f" % total}, 1)
    return config


def profile_facts(profile):
    """只提取 confirmed 事实；pending/expired 一律不进入评分依据。"""
    facts = {
        "degrees": [],
        "skills": [],
        "roles": [],
        "certs": [],
        "cities": [],
        "industries": [],
        "job_types": [],
        "work_modes": [],
        "salary_min": None,
        "salary_period": "month",
        "goals": "",
        "pending": [],
    }
    for item in profile.get("education") or []:
        if isinstance(item, dict) and item.get("status") == "confirmed" and item.get("degree"):
            facts["degrees"].append(item["degree"])
    for item in profile.get("skills") or []:
        if isinstance(item, dict):
            if item.get("status") == "confirmed" and item.get("name"):
                facts["skills"].append(item["name"])
            elif item.get("status") == "pending":
                facts["pending"].append("技能：%s" % item.get("name"))
    for item in profile.get("experience") or []:
        if isinstance(item, dict) and item.get("status") == "confirmed":
            if item.get("role"):
                facts["roles"].append(item["role"])
    for item in profile.get("certifications") or []:
        if isinstance(item, dict):
            if item.get("status") == "confirmed" and item.get("state") == "已取得":
                facts["certs"].append(item.get("name") or "")
            elif item.get("status") == "pending" or item.get("state") in ("备考中", "计划中"):
                facts["pending"].append("证书：%s（%s）" % (item.get("name"), item.get("state")))
    prefs = profile.get("preferences") or {}
    facts["cities"] = [str(item) for item in prefs.get("cities") or []]
    facts["industries"] = [str(item) for item in prefs.get("industries") or []]
    facts["job_types"] = [str(item) for item in prefs.get("job_types") or []]
    facts["work_modes"] = [str(item) for item in prefs.get("work_modes") or []]
    facts["salary_min"] = prefs.get("salary_min")
    facts["salary_period"] = prefs.get("salary_period") or "month"
    goals = profile.get("career_goals") or {}
    facts["goals"] = " ".join(
        [str(goals.get("short_term") or ""), str(goals.get("long_term") or "")]
    ).strip()
    return facts


def make_dimension(config, key, score, reasons=None, evidence=None, missing=None, risks=None):
    label = (config.get("dimension_labels") or {}).get(key, key)
    weight = float(config["weights"][key])
    return {
        "key": key,
        "label": label,
        "score": int(max(0, min(100, round(score)))),
        "weight": weight,
        "weighted": round(max(0, min(100, round(score))) * weight, 1),
        "reasons": reasons or [],
        "evidence": evidence or [],
        "missing_info": missing or [],
        "risks": risks or [],
    }


def job_text(job):
    return norm_text(
        "\n".join(
            text_of(job.get(field))
            for field in (
                "title",
                "company",
                "location",
                "industry",
                "job_type",
                "requirements",
                "responsibilities",
                "raw_text",
            )
        )
    )


def max_degree_rank(facts, degree_rank):
    ranks = [degree_rank.get(degree, 0) for degree in facts["degrees"]]
    return max(ranks) if ranks else 0


def detect_required_degree(job, degree_rank, text):
    explicit = str(job.get("degree") or "").strip()
    if explicit:
        for degree in ("博士", "硕士", "本科", "大专"):
            if degree in explicit:
                return degree
        if "不限" in explicit:
            return "不限"
    for degree in ("博士", "硕士", "本科", "大专"):
        if degree in text:
            return degree
    return ""


def score_responsibilities(job, facts, config):
    text = job_text(job)
    terms = [term for term in (facts["skills"] + facts["roles"]) if norm_key(term)]
    deduped = []
    seen = set()
    for term in terms:
        key = norm_key(term)
        if key not in seen:
            seen.add(key)
            deduped.append(term)
    if not deduped:
        return make_dimension(
            config,
            "responsibilities_match",
            50,
            reasons=["档案中没有已确认的技能/经历关键词，只能给默认分"],
            missing=["档案缺少已确认的技能与经历关键词"],
        )
    matched = [term for term in deduped if norm_key(term) in text]
    ratio = len(matched) / len(deduped)
    score = round(100 * ratio)
    if matched and score < 20:
        score = 20
    reasons = ["档案关键词 %d 个，岗位描述命中 %d 个（%.0f%%）" % (len(deduped), len(matched), ratio * 100)]
    if not matched:
        reasons.append("岗位描述未命中任何已确认技能，职责相关性低")
    return make_dimension(
        config,
        "responsibilities_match",
        score,
        reasons=reasons,
        evidence=matched,
    )


def score_hard_requirements(job, facts, config):
    text = job_text(job)
    degree_rank = config["degree_rank"]
    profile_rank = max_degree_rank(facts, degree_rank)
    required_degree = detect_required_degree(job, degree_rank, text)
    reasons, missing, risks = [], [], []
    warnings = []
    hard_fail = False

    if required_degree and required_degree != "不限":
        required_rank = degree_rank.get(required_degree, 0)
        if profile_rank == 0:
            missing.append("档案未确认学历，无法判断学历门槛")
            warnings.append("学历未确认")
        elif required_rank > profile_rank:
            hard_fail = True
            reasons.append(
                "学历要求 %s，档案最高为 %s：硬性不满足，总分不改变该结论"
                % (required_degree, "/".join(facts["degrees"]) or "未确认")
            )
        else:
            reasons.append("学历要求 %s，档案为 %s，满足" % (required_degree, "/".join(facts["degrees"])))
    elif required_degree == "不限":
        reasons.append("学历不限")
    else:
        missing.append("岗位学历要求未标注")

    years = re.findall(r"(?<!\d)(\d{1,2})\s*(?:-\s*(\d{1,2}))?\s*年", text)
    required_years = 0
    for first, second in years:
        if first.isdigit():
            required_years = max(required_years, int(first))
    if required_years >= 1:
        warnings.append("岗位要求 %d 年以上经验，档案未确认全职经验" % required_years)
        risks.append("经验门槛为 %d 年以上，档案仅有实习/项目经历，需确认是否符合" % required_years)

    if re.search(r"英语|英文|日语|CET|雅思|托福", text):
        has_language = any(
            re.search(r"英语|英文|日语|CET|雅思|托福", cert) for cert in facts["certs"]
        )
        if has_language:
            reasons.append("语言要求可在档案证书中找到依据（%s）" % "、".join(facts["certs"]))
        else:
            warnings.append("岗位有语言要求，档案未确认对应证书")
            risks.append("语言要求未在档案中确认，不得写成已满足")

    for keyword in CERT_KEYWORDS:
        if keyword in text:
            confirmed = any(norm_key(keyword) in norm_key(cert) for cert in facts["certs"])
            if not confirmed:
                warnings.append("岗位提到 %s，档案未确认已取得" % keyword)
                risks.append("%s：档案未确认已取得，只能标注待确认" % keyword)

    score = 0 if hard_fail else max(20, 100 - 20 * len(warnings))
    for item in warnings:
        missing.append(item) if item not in missing else None
    return make_dimension(
        config,
        "hard_requirements",
        score,
        reasons=reasons or ["未标注硬性门槛或已满足"],
        missing=missing,
        risks=risks,
    ), hard_fail


def score_career_value(job, facts, config):
    text = job_text(job)
    missing = []
    if not facts["goals"]:
        return make_dimension(
            config,
            "career_value",
            50,
            reasons=["档案未填写职业目标，只能给默认分"],
            missing=["career_goals 未填写"],
        )
    goals_text = norm_text(facts["goals"])
    goal_domains = [domain for domain in DOMAIN_KEYWORDS if norm_key(domain) in goals_text]
    hits = [domain for domain in goal_domains if norm_key(domain) in text]
    industry_hits = [industry for industry in facts["industries"] if norm_key(industry) in text]
    score = 40
    reasons = []
    if hits:
        score += 30
        reasons.append("与职业目标方向重合：%s" % "、".join(hits))
    if industry_hits:
        score += 30
        reasons.append("行业与偏好重合：%s" % "、".join(industry_hits))
    if not goal_domains:
        missing.append("职业目标未包含可识别方向关键词")
    if not hits:
        reasons.append("岗位方向与职业目标关键词无直接重合")
    if not industry_hits:
        missing.append("岗位行业未标注或与偏好行业不同")
    return make_dimension(config, "career_value", score, reasons=reasons, missing=missing)


def score_preference_fit(job, facts, config):
    text = job_text(job)
    location = str(job.get("location") or "")
    job_city = str(job.get("city") or "") or split_city(location)
    score = 25
    reasons, missing, risks = [], [], []
    if facts["cities"]:
        if job_city and (job_city in facts["cities"] or any(city in location for city in facts["cities"])):
            score += 45
            reasons.append("城市符合偏好（%s）" % job_city)
        else:
            reasons.append("城市不符合偏好：期望 %s，岗位 %s" % ("/".join(facts["cities"]), job_city or "未标注"))
            risks.append("工作地点与偏好不一致，需确认是否接受")
    else:
        score += 25
        missing.append("档案未确认期望城市")
    if facts["job_types"]:
        if any(job_type in text for job_type in facts["job_types"]):
            score += 25
            reasons.append("岗位类型符合偏好")
        else:
            reasons.append("岗位类型与偏好不同")
    return make_dimension(config, "preference_fit", score, reasons=reasons, missing=missing, risks=risks)


def monthly_from(amount, period):
    if amount is None:
        return None
    if period == "year":
        return amount / 12
    if period == "day":
        return amount * 21
    return amount


def score_compensation(job, facts, config):
    defaults = config.get("defaults") or {}
    salary = job.get("salary_month_equivalent") or {}
    job_month = salary.get("min") if isinstance(salary, dict) else None
    missing, reasons, risks = [], [], []
    if not job_month:
        return make_dimension(
            config,
            "compensation",
            float(defaults.get("unknown_salary_score", 50)),
            reasons=["薪资未标注或无法解析，按默认分处理"],
            missing=["薪资信息缺失，无法判断是否达到底线"],
            risks=["薪资未知，投递前需向招聘方确认"],
        )
    pref_month = monthly_from(facts["salary_min"], facts["salary_period"])
    if not pref_month:
        return make_dimension(
            config,
            "compensation",
            60,
            reasons=["档案未确认薪资底线"],
            missing=["preferences.salary_min 未填写"],
        )
    ratio = job_month / pref_month
    if ratio >= 1:
        score, note = 100, "达到或超过薪资底线"
    elif ratio >= 0.8:
        score, note = 80, "略低于薪资底线（约 %.0f%%）" % (ratio * 100)
    elif ratio >= 0.6:
        score, note = 60, "明显低于薪资底线（约 %.0f%%）" % (ratio * 100)
    else:
        score, note = 40, "远低于薪资底线（约 %.0f%%）" % (ratio * 100)
    reasons.append("%s：岗位约 %d 元/月，底线约 %d 元/月" % (note, job_month, pref_month))
    if score < 60:
        risks.append("薪资明显低于底线，需确认是否接受")
    return make_dimension(config, "compensation", score, reasons=reasons, missing=missing, risks=risks)


def score_source_credibility(job, trusted_sources, config):
    defaults = config.get("defaults") or {}
    url = str(job.get("source_url") or "").strip()
    source = str(job.get("source") or "").strip()
    reasons, risks = [], []
    if url:
        if source in trusted_sources:
            score = 100
            reasons.append("来源为可信渠道（%s）且带原始链接" % source)
        else:
            score = 75
            reasons.append("有原始链接，但来源渠道未登记为可信（%s）" % (source or "unknown"))
    else:
        score = float(defaults.get("unknown_source_score", 40))
        reasons.append("缺少原始链接，无法核验岗位真实性")
        risks.append("缺少来源链接，真实性未验证")
    if not job.get("company"):
        score -= 20
        risks.append("公司名称缺失")
    if not job.get("location"):
        score -= 15
        risks.append("工作地点缺失")
    return make_dimension(config, "source_credibility", max(0, score), reasons=reasons, risks=risks)


def evaluate_job(job, facts, config, trusted_sources):
    dimensions = []
    resp = score_responsibilities(job, facts, config)
    dimensions.append(resp)
    hard, hard_fail = score_hard_requirements(job, facts, config)
    dimensions.append(hard)
    dimensions.append(score_career_value(job, facts, config))
    dimensions.append(score_preference_fit(job, facts, config))
    dimensions.append(score_compensation(job, facts, config))
    dimensions.append(score_source_credibility(job, trusted_sources, config))

    total = round(sum(dimension["weighted"] for dimension in dimensions))
    thresholds = config.get("thresholds") or {}
    if hard_fail:
        status = thresholds.get("blocked_status", "不匹配")
    elif total >= thresholds.get("priority", 78):
        status = "优先投递"
    elif total >= thresholds.get("consider", 60):
        status = "待评估"
    else:
        status = "暂缓"

    ranked = sorted(dimensions, key=lambda item: item["weighted"], reverse=True)
    top_reasons = []
    if hard_fail and hard["reasons"]:
        top_reasons.append("硬性阻断：%s" % hard["reasons"][0])
    for dimension in ranked:
        for reason in dimension["reasons"]:
            text = "%s：%s" % (dimension["label"], reason)
            if text not in top_reasons:
                top_reasons.append(text)
    missing_info = []
    risk_flags = []
    for dimension in dimensions:
        for item in dimension["missing_info"]:
            if item not in missing_info:
                missing_info.append(item)
        for item in dimension["risks"]:
            if item not in risk_flags:
                risk_flags.append(item)
    for item in job.get("missing_info") or []:
        if item not in missing_info:
            missing_info.append(item)
    for item in job.get("risk_flags") or []:
        if item not in risk_flags:
            risk_flags.append(item)

    return {
        "match_score": total,
        "score_breakdown": dimensions,
        "risk_flags": risk_flags,
        "missing_info": missing_info,
        "top_reasons": top_reasons[:3],
        "blocked": hard_fail,
        "status": status,
    }


def build_report(result, config, jobs_by_id):
    lines = [
        "# 岗位评分报告",
        "",
        "- 生成时间：%s" % result["generated_at"],
        "- 配置版本：%s" % result.get("config_version"),
        "- 评分口径：六维加权（%s）" % " / ".join(
            "%s %d%%" % (config["dimension_labels"][key], round(config["weights"][key] * 100))
            for key in DIMENSION_ORDER
        ),
        "- 结论数量：%d" % result["count"],
        "",
        "| 排名 | 岗位 | 公司 | 城市 | 分数 | 建议状态 | 硬性阻断 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in result["ranking"]:
        lines.append(
            "| %d | %s | %s | %s | %d | %s | %s |"
            % (
                item["rank"],
                item["title"],
                item["company"],
                item.get("city") or "未标注",
                item["score"],
                item["status"],
                "是" if item["blocked"] else "否",
            )
        )
    if not result["ranking"]:
        lines.append("| - | 无可评分岗位 | - | - | - | - | - |")
    lines += ["", "## 明细"]
    for item in result["ranking"]:
        job = jobs_by_id.get(item["job_id"], {})
        lines += [
            "",
            "### %s. %s｜%s（%d 分 / %s）" % (item["rank"], item["company"], item["title"], item["score"], item["status"]),
            "",
            "- job_id：`%s`" % item["job_id"],
            "- 来源：%s（%s）" % (job.get("source") or "unknown", job.get("source_url") or "无链接"),
            "- 分项：%s" % "；".join(
                "%s %d（权重 %d%%）" % (dim["label"], dim["score"], round(dim["weight"] * 100))
                for dim in item["breakdown"]
            ),
        ]
        if item["blocked"]:
            lines.append("- **硬性阻断**：总分不改变阻断结论，建议不投递或先确认资格")
        if item.get("reasons"):
            lines.append("- 主要理由：%s" % "；".join(item["reasons"]))
        if item.get("risks"):
            lines.append("- 风险：%s" % "；".join(item["risks"]))
        if item.get("missing_info"):
            lines.append("- 待确认/缺失：%s" % "；".join(item["missing_info"]))
    if result.get("skipped_duplicates"):
        lines += ["", "## 跳过的疑似重复岗位（默认不评分）"]
        for item in result["skipped_duplicates"]:
            lines.append("- `%s` %s｜%s：%s" % (item["job_id"], item["company"], item["title"], item["reason"]))
    lines += [
        "",
        "> 评分是可解释的匹配度，不是录取概率。硬性门槛单独阻断；未知信息只能标注待确认，不得推测补全。",
    ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    args = build_parser().parse_args(argv)
    config = load_config(resolve(args.config))
    jobs_path = resolve(args.jobs)
    profile_path = resolve(args.profile)
    profile = read_json(profile_path)
    jobs_doc = read_json(jobs_path)
    settings_path = resolve(args.settings)
    settings = {}
    if os.path.exists(settings_path):
        settings = read_json(settings_path)
    trusted_sources = set(settings.get("trusted_sources") or [])

    jobs = jobs_doc.get("jobs") if isinstance(jobs_doc, dict) else jobs_doc
    if not isinstance(jobs, list):
        emit({"ok": False, "error": "岗位文件结构错误：缺少 jobs 数组"}, 1)

    facts = profile_facts(profile)
    evaluated, skipped = [], []
    scored_jobs = []
    jobs_by_id = {}
    for job in jobs:
        if not isinstance(job, dict):
            continue
        jobs_by_id[job.get("job_id")] = job
        record = dict(job)
        if job.get("is_duplicate") and not args.include_duplicates:
            record["evaluated"] = False
            record["skip_reason"] = "与 %s 疑似重复，默认不评分" % job.get("duplicate_of")
            skipped.append(
                {
                    "job_id": job.get("job_id"),
                    "company": job.get("company"),
                    "title": job.get("title"),
                    "duplicate_of": job.get("duplicate_of"),
                    "reason": record["skip_reason"],
                }
            )
            scored_jobs.append(record)
            continue
        result = evaluate_job(job, facts, config, trusted_sources)
        record.update(result)
        record["evaluated"] = True
        record["scored_at"] = now_iso()
        scored_jobs.append(record)
        evaluated.append(
            {
                "job_id": job.get("job_id"),
                "company": job.get("company"),
                "title": job.get("title"),
                "city": job.get("city") or split_city(job.get("location")),
                "score": result["match_score"],
                "status": result["status"],
                "blocked": result["blocked"],
                "reasons": result["top_reasons"],
                "risks": result["risk_flags"][:5],
                "missing_info": result["missing_info"][:5],
                "breakdown": [
                    {"label": dim["label"], "score": dim["score"], "weight": dim["weight"]}
                    for dim in result["score_breakdown"]
                ],
            }
        )

    evaluated.sort(key=lambda item: (item["blocked"], -item["score"]))
    for rank, item in enumerate(evaluated, start=1):
        item["rank"] = rank

    result = {
        "ok": True,
        "generated_at": now_iso(),
        "generated_by": "scripts/score_jobs.py",
        "config_version": config.get("version"),
        "weights": config["weights"],
        "profile": rel_path(profile_path),
        "count": len(evaluated),
        "ranking": evaluated,
        "skipped_duplicates": skipped,
    }

    output = {
        "schema_version": "1.0",
        "generated_at": result["generated_at"],
        "generated_by": result["generated_by"],
        "config_version": config.get("version"),
        "counts": {"total": len(scored_jobs), "evaluated": len(evaluated), "skipped_duplicates": len(skipped)},
        "jobs": scored_jobs,
    }
    output_path = resolve(args.output)
    save_json(output, output_path)
    result["output"] = rel_path(output_path)

    if args.report:
        report_path = resolve(args.report)
        os.makedirs(os.path.dirname(report_path), exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write(build_report(result, config, jobs_by_id))
        result["report"] = rel_path(report_path)

    emit(result, 0)


if __name__ == "__main__":
    main()
