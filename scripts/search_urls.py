#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按搜索画像生成各平台搜索链接（L1 层：纯本地，不联网、不抓取）。

只做一件事：读 `config/search.json`，把「关键词 × 城市 × 平台」展开成可点开的
搜索计划，输出 Markdown（人读）与 JSON（供 L2 抓取使用）。

本脚本刻意不含任何网络能力：不请求、不解析网页、不写 jobs 业务数据。
真正的抓取由 Agent 按 skill 的 job-search-policy.md 执行。

用法:
    python scripts/search_urls.py
    python scripts/search_urls.py --group fin_impl --city 上海
    python scripts/search_urls.py --platform shixiseng --max 20

退出码:
    0 生成成功
    1 配置非法（缺字段、占位符错误、没有可用关键词）
    2 配置文件缺失或参数错误
"""

import argparse
import os
import sys

from common import (
    emit,
    now_date,
    now_iso,
    read_json,
    rel_path,
    resolve,
    save_json,
)

DEFAULT_CONFIG = "config/search.json"
DEFAULT_OUT_DIR = "jobs/raw"

ALLOWED_FETCH_MODES = {"webfetch_ok", "needs_dom"}
REQUIRED_PLATFORM_FIELDS = (
    "id",
    "name",
    "search_url",
    "browse_url",
    "keyword_param_works",
    "fetch_mode",
)


def url_quote(text):
    """最小化的 UTF-8 百分号编码。

    不引入 urllib：T12 会拒斥脚本中的网络模块引用，且这里只需要最基础的
    字符转义。保留 RFC 3986 的 unreserved 字符集，其余按字节编码。
    """
    safe = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~")
    out = []
    for byte in str(text).encode("utf-8"):
        char = chr(byte)
        if char in safe:
            out.append(char)
        else:
            out.append("%%%02X" % byte)
    return "".join(out)


def load_config(path):
    """读取并校验搜索画像；任何结构问题都以退出码 1 报出。"""
    config = read_json(path)
    if not isinstance(config, dict):
        emit({"ok": False, "error": "search.json 顶层必须是对象"}, 1)

    platforms = config.get("platforms")
    if not isinstance(platforms, list) or not platforms:
        emit({"ok": False, "error": "search.json 缺少 platforms 列表"}, 1)

    for index, platform in enumerate(platforms):
        if not isinstance(platform, dict):
            emit({"ok": False, "error": "platforms[%d] 必须是对象" % index}, 1)
        for field in REQUIRED_PLATFORM_FIELDS:
            if field not in platform:
                emit(
                    {
                        "ok": False,
                        "error": "platforms[%d] 缺少字段: %s" % (index, field),
                    },
                    1,
                )
        mode = platform.get("fetch_mode")
        if mode not in ALLOWED_FETCH_MODES:
            emit(
                {
                    "ok": False,
                    "error": "platforms[%s].fetch_mode 只能是 %s，当前为 %s"
                    % (platform.get("id"), " / ".join(sorted(ALLOWED_FETCH_MODES)), mode),
                },
                1,
            )
        template = str(platform.get("search_url") or "")
        if not template.startswith("https://"):
            emit(
                {
                    "ok": False,
                    "error": "platforms[%s].search_url 必须是 https 地址" % platform.get("id"),
                },
                1,
            )

    groups = config.get("keyword_groups")
    if not isinstance(groups, list) or not groups:
        emit({"ok": False, "error": "search.json 缺少 keyword_groups"}, 1)

    cities = config.get("cities")
    if not isinstance(cities, list) or not cities:
        emit({"ok": False, "error": "search.json 缺少 cities"}, 1)

    return config


def build_plan(config, args):
    """展开关键词矩阵，返回 (plan, skipped)。

    排除词在这里生效：关键词本身命中排除词就不生成查询，而不是「生成了再过滤」。
    少发一次请求，比多过滤一条结果更省事，也更不容易误触平台的频控。
    """
    excludes = [str(item).strip() for item in (config.get("exclude_keywords") or []) if str(item).strip()]

    platforms = config["platforms"]
    if args.platform:
        wanted = {item.strip().lower() for item in args.platform}
        platforms = [p for p in platforms if str(p["id"]).lower() in wanted]
        if not platforms:
            emit({"ok": False, "error": "指定的 platform 未在 search.json 中定义"}, 2)

    cities = config["cities"]
    if args.city:
        wanted_city = {item.strip() for item in args.city}
        cities = [c for c in cities if str(c["name"]) in wanted_city]
        if not cities:
            emit({"ok": False, "error": "指定的 city 未在 search.json 中定义"}, 2)

    groups = sorted(config["keyword_groups"], key=lambda g: (g.get("priority", 99), str(g.get("id"))))
    if args.group:
        wanted_group = {item.strip().lower() for item in args.group}
        groups = [g for g in groups if str(g.get("id")).lower() in wanted_group]
        if not groups:
            emit({"ok": False, "error": "指定的 group 未在 search.json 中定义"}, 2)

    plan = []
    skipped = []

    for group in groups:
        for keyword in group.get("keywords") or []:
            keyword = str(keyword).strip()
            if not keyword:
                continue
            hits = [word for word in excludes if word in keyword]
            if hits:
                skipped.append(
                    {
                        "keyword": keyword,
                        "group": group.get("id"),
                        "reason": "关键词命中排除词: %s" % "、".join(hits),
                    }
                )
                continue
            for city in cities:
                for platform in platforms:
                    template = str(platform["search_url"])
                    url = template.replace("{keyword}", url_quote(keyword)).replace(
                        "{city}", url_quote(str(city["name"]))
                    )
                    plan.append(
                        {
                            "group_id": group.get("id"),
                            "group_label": group.get("label"),
                            "group_priority": group.get("priority", 99),
                            "keyword": keyword,
                            "city": city["name"],
                            "city_priority": city.get("priority"),
                            "platform_id": platform["id"],
                            "platform_name": platform["name"],
                            "url": url,
                            "fetch_mode": platform["fetch_mode"],
                            "keyword_param_works": bool(platform["keyword_param_works"]),
                            "params_verified": bool(platform.get("params_verified")),
                            "verified_at": platform.get("verified_at"),
                        }
                    )

    if args.max and args.max > 0:
        plan = plan[: args.max]

    return plan, skipped


def render_markdown(config, plan, skipped, generated_at):
    """生成人读的搜索计划：按关键词分组，每条一行链接。"""
    lines = []
    lines.append("# 岗位搜索计划")
    lines.append("")
    lines.append("> 由 `scripts/search_urls.py` 生成于 %s。" % generated_at)
    lines.append("> 本文件只有搜索链接，**不含任何采集结果**；抓取规则见 `skills/job-agent/references/job-search-policy.md`。")
    lines.append("")

    total_queries = len(plan)
    platforms = sorted({item["platform_name"] for item in plan})
    cities = []
    for item in plan:
        if item["city"] not in cities:
            cities.append(item["city"])
    lines.append("| 项 | 值 |")
    lines.append("| --- | --- |")
    lines.append("| 查询条数 | %d |" % total_queries)
    lines.append("| 平台 | %s |" % ("、".join(platforms) if platforms else "—"))
    lines.append("| 城市 | %s |" % ("、".join(cities) if cities else "—"))
    lines.append("| 已过滤关键词 | %d |" % len(skipped))
    lines.append("")

    mode_note = {
        "webfetch_ok": "可直接只读抓取",
        "needs_dom": "需浏览器 DOM 渲染",
    }

    current_section = None
    for item in plan:
        section = (item["group_id"], item["keyword"])
        if section != current_section:
            if current_section is not None:
                lines.append("")
            current_section = section
            lines.append("## %s · %s" % (item["group_label"], item["keyword"]))
            lines.append("")
        flag = "" if item["keyword_param_works"] else "（该平台关键词参数不生效，需抓取后本地过滤）"
        lines.append(
            "- **%s** · %s%s：[打开搜索](%s)  `%s`"
            % (
                item["city"],
                item["platform_name"],
                flag,
                item["url"],
                mode_note.get(item["fetch_mode"], item["fetch_mode"]),
            )
        )

    if skipped:
        lines.append("## 已过滤的关键词")
        lines.append("")
        for item in skipped:
            lines.append("- `%s` — %s" % (item["keyword"], item["reason"]))
        lines.append("")

    constraints = config.get("constraints") or {}
    if constraints:
        lines.append("## 搜索时请一并核对的硬条件")
        lines.append("")
        if constraints.get("graduate_year"):
            lines.append("- 届别：%s 届" % constraints["graduate_year"])
        if constraints.get("job_types"):
            types = {"campus": "校招", "internship": "实习"}
            lines.append(
                "- 岗位类型：%s"
                % "、".join(types.get(t, t) for t in constraints["job_types"])
            )
        if constraints.get("weekly_days_min"):
            lines.append("- 实习到岗：每周不少于 %s 天" % constraints["weekly_days_min"])
        if constraints.get("max_pages_per_query"):
            lines.append("- 单条查询翻页上限：%s 页" % constraints["max_pages_per_query"])
        lines.append("")

    lines.append("## 下一步")
    lines.append("")
    lines.append("1. 点开上表中关心的链接，确认岗位是否符合预期。")
    lines.append("2. 把中意的岗位原文（或链接）交给 Agent，按步骤 1 导入 `jobs/raw/`。")
    lines.append("3. 若某条链接失效，先改 `config/search.json` 的 `url_template`，**不要改脚本**。")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="按搜索画像生成各平台搜索链接（纯本地，不联网）"
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="搜索画像文件，默认 config/search.json")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="输出目录，默认 jobs/raw")
    parser.add_argument("--platform", nargs="+", help="只生成指定平台（可多个）")
    parser.add_argument("--city", nargs="+", help="只生成指定城市（可多个）")
    parser.add_argument("--group", nargs="+", help="只生成指定关键词组（可多个）")
    parser.add_argument("--max", type=int, default=0, help="最多生成多少条查询（0 表示不限）")
    parser.add_argument("--stdout", action="store_true", help="只打印 Markdown，不写文件")
    args = parser.parse_args()

    config_path = resolve(args.config)
    if not os.path.exists(config_path):
        emit({"ok": False, "error": "配置文件不存在: %s" % args.config}, 2)

    config = load_config(config_path)
    plan, skipped = build_plan(config, args)

    if not plan:
        emit(
            {
                "ok": False,
                "error": "没有生成任何查询：关键词可能全部被排除，或过滤条件过窄",
                "skipped": skipped,
            },
            1,
        )

    generated_at = now_iso()

    if args.stdout:
        print(render_markdown(config, plan, skipped, generated_at))
        return

    out_dir = resolve(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    date_tag = now_date()
    md_path = os.path.join(out_dir, "search-plan-%s.md" % date_tag)
    json_path = os.path.join(out_dir, "search-plan-%s.json" % date_tag)

    markdown = render_markdown(config, plan, skipped, generated_at)
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(markdown)
        if not markdown.endswith("\n"):
            fh.write("\n")

    save_json(
        {
            "schema_version": "1.0",
            "generated_at": generated_at,
            "source_config": rel_path(config_path),
            "note": "本文件仅为搜索计划，不含采集结果。抓取后写入新的 raw_jobs 文件。",
            "counts": {
                "queries": len(plan),
                "keywords": len({item["keyword"] for item in plan}),
                "cities": len({item["city"] for item in plan}),
                "platforms": len({item["platform_id"] for item in plan}),
                "skipped_keywords": len(skipped),
            },
            "constraints": config.get("constraints") or {},
            "policy": config.get("search_policy") or {},
            "plan": plan,
            "skipped": skipped,
        },
        json_path,
    )

    emit(
        {
            "ok": True,
            "generated_at": generated_at,
            "counts": {
                "queries": len(plan),
                "keywords": len({item["keyword"] for item in plan}),
                "platforms": len({item["platform_id"] for item in plan}),
                "skipped_keywords": len(skipped),
            },
            "skipped": skipped,
            "outputs": {"markdown": rel_path(md_path), "json": rel_path(json_path)},
        }
    )


if __name__ == "__main__":
    sys.exit(main())
