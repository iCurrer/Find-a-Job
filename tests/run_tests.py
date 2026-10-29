#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试：用固定样例数据验证 4 个脚本与 Skill 文档的确定性行为。

对应方案 9.1 必测用例 T01–T12。浏览器类用例（T07/T08 的真实页面部分）
无法在本地脚本层复现，这里验证 Skill 文档中的强制暂停规则与脚本侧的
“无证据不得标记已提交”约束。

用法:
    python tests/run_tests.py

退出码: 0 全部通过；1 存在失败用例。
"""

import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")

RESULTS = []


def run(script, args):
    proc = subprocess.run(
        [PYTHON, os.path.join(ROOT, "scripts", script)] + [str(item) for item in args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=ENV,
    )
    payload = None
    try:
        payload = json.loads(proc.stdout.strip())
    except (json.JSONDecodeError, AttributeError):
        payload = None
    return {
        "code": proc.returncode,
        "json": payload,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(data, path):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def job_by_title(scored, title):
    for job in scored["jobs"]:
        if job.get("title") == title:
            return job
    raise AssertionError("评分结果中找不到岗位: %s" % title)


def create_application(store, job_id, log_path, check_steps=("待准备", "待确认", "执行中")):
    for status in check_steps:
        result = run(
            "update_application.py",
            ["--job-id", job_id, "--status", status, "--store", store, "--log", log_path],
        )
        check(result["code"] == 0, "状态 %s 更新失败: %s" % (status, result["stdout"][:400]))


# ---------------------------------------------------------------------------
# T01 个人档案存在字段缺失：明确提示缺失项，不自动编造
# ---------------------------------------------------------------------------
def t01(ctx):
    profile = load_json(os.path.join(ROOT, "tests", "sample_profile.json"))
    profile.pop("skills")
    profile["education"][0].pop("school")
    broken = os.path.join(ctx["tmp"], "broken_profile.json")
    write_json(profile, broken)
    result = run("validate_profile.py", ["--profile", broken])
    check(result["code"] == 1, "缺失字段时退出码应为 1，实际 %s" % result["code"])
    payload = result["json"]
    check(payload and payload["ok"] is False, "缺失字段时 ok 必须为 false")
    text = " ".join(payload["errors"])
    check("skills" in text, "错误信息应指出缺失的 skills 字段")
    check("school" in text, "错误信息应指出缺失的 education.school 字段")


# ---------------------------------------------------------------------------
# T02 两个岗位链接不同但职位信息相同：识别为疑似重复并保留来源
# ---------------------------------------------------------------------------
def t02(ctx):
    payload = ctx["normalize"]["json"]
    check(payload and payload["ok"] is True, "标准化应成功")
    duplicates = payload["duplicates"]
    check(len(duplicates) == 1, "应识别出 1 组疑似重复，实际 %d" % len(duplicates))
    pair = duplicates[0]
    check(pair["canonical_job_id"] != pair["duplicate_job_id"], "重复项必须保留两条来源记录")
    sources = [item for item in pair["sources"] if item]
    check(len(sources) == 2 and sources[0] != sources[1], "两条来源链接应不同且都被保留")
    jobs = {job["job_id"]: job for job in load_json(ctx["normalized_path"])["jobs"]}
    canonical = jobs[pair["canonical_job_id"]]
    duplicate = jobs[pair["duplicate_job_id"]]
    check(canonical["dedupe_key"] == duplicate["dedupe_key"], "重复岗位应有相同去重键")
    check(duplicate["is_duplicate"] is True, "重复项应标记 is_duplicate")
    check(duplicate["duplicate_of"] == canonical["job_id"], "重复项应指向原始 job_id")


# ---------------------------------------------------------------------------
# T03 岗位要求证书但档案未确认：标记待确认/风险，不声称已取得
# ---------------------------------------------------------------------------
def t03(ctx):
    job = job_by_title(ctx["scored"], "内容审核专员")
    risks = " ".join(job.get("risk_flags") or [])
    check("教师资格证" in risks, "应就未确认的教师资格证给出风险提示，实际: %s" % risks)
    check(
        "已取得" not in " ".join(job.get("top_reasons") or []),
        "不得把未确认证书写成已取得",
    )
    check(job["status"] != "优先投递", "存在硬性/证书风险时不应直接判定优先投递")


# ---------------------------------------------------------------------------
# T04 岗位与个人硬性条件冲突：显示阻断或警示原因，不被总分掩盖
# ---------------------------------------------------------------------------
def t04(ctx):
    job = job_by_title(ctx["scored"], "算法实习生")
    check(job["blocked"] is True, "硕士要求 vs 本科学历应触发硬性阻断")
    check(job["status"] == "不匹配", "阻断岗位状态应为不匹配，实际 %s" % job["status"])
    hard = [dim for dim in job["score_breakdown"] if dim["key"] == "hard_requirements"][0]
    check(hard["score"] == 0, "硬性条件不满足时该维度应为 0 分")
    check("学历" in " ".join(hard["reasons"]), "阻断原因必须写明学历不满足")


# ---------------------------------------------------------------------------
# T05 待确认事实不得当作已确认：进入待确认清单
# ---------------------------------------------------------------------------
def t05(ctx):
    result = run(
        "validate_profile.py",
        ["--profile", os.path.join("tests", "sample_profile.json"), "--report", os.path.join(ctx["tmp"], "profile-report.md")],
    )
    check(result["code"] == 0, "样例档案结构应合法")
    payload = result["json"]
    labels = " ".join(item["label"] for item in payload["pending_facts"])
    check("教师资格证" in labels, "备考中的证书应出现在 pending_facts")
    check(payload["open_questions"], "待确认问题应被列出")
    report = os.path.join(ctx["tmp"], "profile-report.md")
    check(os.path.exists(report), "应生成 Markdown 校验报告")
    text = open(report, "r", encoding="utf-8").read()
    check("待确认" in text and "教师资格证" in text, "报告中应展示待确认事实")


# ---------------------------------------------------------------------------
# T06 同一岗位已经提交：提醒重复申请风险，默认不再提交
# ---------------------------------------------------------------------------
def t06(ctx):
    job = job_by_title(ctx["scored"], "数据分析实习生")
    check(job.get("evaluated") is True, "非重复岗位应参与评分")
    store = os.path.join(ctx["tmp"], "applications_t06.json")
    log = os.path.join(ctx["tmp"], "audit_t06.jsonl")
    create_application(store, job["job_id"], log)
    submitted = run(
        "update_application.py",
        ["--job-id", job["job_id"], "--status", "已提交", "--evidence", "确认页截图", "--store", store, "--log", log],
    )
    check(submitted["code"] == 0, "有证据时应允许标记已提交")
    again = run(
        "update_application.py",
        ["--job-id", job["job_id"], "--status", "待准备", "--store", store, "--log", log],
    )
    check(again["code"] == 1, "已提交后重复创建记录应被拒绝")
    check(
        "重复" in (again["json"] or {}).get("error", ""),
        "错误信息应提示重复申请风险: %s" % again["stdout"][:300],
    )


# ---------------------------------------------------------------------------
# T07 浏览器页面结构变化：停止自动操作并报告异常（Skill 强制规则）
# ---------------------------------------------------------------------------
def t07(ctx):
    skill_path = os.path.join(ROOT, "skill", "SKILL.md")
    check(os.path.exists(skill_path), "缺少 skill/SKILL.md")
    text = open(skill_path, "r", encoding="utf-8").read()
    check("页面" in text, "SKILL.md 应包含页面变化处理规则")
    check("暂停" in text, "SKILL.md 应要求异常时暂停")
    check("执行器" in text or "浏览器" in text, "SKILL.md 应说明执行器边界")


# ---------------------------------------------------------------------------
# T08 验证码或登录保护：暂停并交用户处理，不尝试绕过
# ---------------------------------------------------------------------------
def t08(ctx):
    text = open(os.path.join(ROOT, "skill", "SKILL.md"), "r", encoding="utf-8").read()
    for keyword in ("验证码", "登录"):
        check(keyword in text, "SKILL.md 应包含 %s 处理规则" % keyword)
    check("绕过" in text or "不得" in text, "SKILL.md 应明确不得绕过风控")


# ---------------------------------------------------------------------------
# T09 提交按钮点击后无确认结果：不得直接标记为已提交
# ---------------------------------------------------------------------------
def t09(ctx):
    job = job_by_title(ctx["scored"], "数据分析实习生")
    store = os.path.join(ctx["tmp"], "applications_t09.json")
    log = os.path.join(ctx["tmp"], "audit_t09.jsonl")
    create_application(store, job["job_id"], log)
    result = run(
        "update_application.py",
        ["--job-id", job["job_id"], "--status", "已提交", "--store", store, "--log", log],
    )
    check(result["code"] == 1, "无证据时标记已提交必须失败")
    message = json.dumps(result["json"], ensure_ascii=False)
    check("evidence" in message or "证据" in message, "错误信息应要求提供提交证据")
    record = load_json(store)["applications"][0]
    check(record["status"] == "执行中", "失败后状态应保持执行中，而不是已提交")
    check(record["submitted_at"] == "", "无证据时不得写入 submitted_at")


# ---------------------------------------------------------------------------
# T10 脚本执行中断：保留状态和错误信息，不产出半成品
# ---------------------------------------------------------------------------
def t10(ctx):
    corrupt = os.path.join(ctx["tmp"], "corrupt_profile.json")
    with open(corrupt, "w", encoding="utf-8") as fh:
        fh.write('{"schema_version": "1.0", "education": [')
    report = os.path.join(ctx["tmp"], "should_not_exist.md")
    result = run("validate_profile.py", ["--profile", corrupt, "--report", report])
    check(result["code"] == 1, "损坏 JSON 应返回退出码 1，实际 %s" % result["code"])
    check((result["json"] or {}).get("ok") is False, "应输出结构化错误")
    check(not os.path.exists(report), "解析失败时不得产出报告文件")
    check("Traceback" not in result["stdout"], "不应向用户抛出裸 traceback")


# ---------------------------------------------------------------------------
# T11 恢复备份：能还原投递记录
# ---------------------------------------------------------------------------
def t11(ctx):
    job = job_by_title(ctx["scored"], "数据分析实习生")
    store = os.path.join(ctx["tmp"], "applications_t11.json")
    log = os.path.join(ctx["tmp"], "audit_t11.jsonl")
    create_application(store, job["job_id"], log, check_steps=("待准备",))
    result = run(
        "update_application.py",
        ["--job-id", job["job_id"], "--status", "待确认", "--store", store, "--log", log],
    )
    check(result["code"] == 0, "状态推进应成功")
    backup = store + ".bak"
    check(os.path.exists(backup), "写入前应生成 applications.json.bak")
    check(load_json(backup)["applications"][0]["status"] == "待准备", "备份应是写入前的状态")
    shutil.copy2(backup, store)
    check(load_json(store)["applications"][0]["status"] == "待准备", "用备份恢复后状态应还原")


# ---------------------------------------------------------------------------
# T12 未授权外发个人信息：本地脚本不得联网/发送数据
# ---------------------------------------------------------------------------
def t12(ctx):
    forbidden = ("import requests", "import socket", "import smtplib", "urllib.request", "http.client", "ftplib")
    scripts_dir = os.path.join(ROOT, "scripts")
    for name in sorted(os.listdir(scripts_dir)):
        if not name.endswith(".py"):
            continue
        text = open(os.path.join(scripts_dir, name), "r", encoding="utf-8").read()
        for token in forbidden:
            check(token not in text, "%s 不得包含网络能力: %s" % (name, token))
    check("require_confirmation" in open(os.path.join(ROOT, "config", "settings.json"), "r", encoding="utf-8").read(),
          "settings.json 应保留外部写入的确认点配置")


TESTS = [
    ("T01", "档案字段缺失提示", t01),
    ("T02", "不同链接同一岗位去重", t02),
    ("T03", "要求证书但档案未确认", t03),
    ("T04", "硬性条件冲突阻断", t04),
    ("T05", "待确认事实不当作已确认", t05),
    ("T06", "重复申请拦截", t06),
    ("T07", "页面变化暂停规则", t07),
    ("T08", "验证码/登录保护暂停规则", t08),
    ("T09", "无提交证据不得标记已提交", t09),
    ("T10", "脚本中断不产出半成品", t10),
    ("T11", "备份可恢复", t11),
    ("T12", "本地脚本不联网", t12),
]


def main():
    # 不用 tempfile.mkdtemp：Windows 下其 0700 目录可能被安全策略拒绝写入。
    tmp = os.path.join(ROOT, ".tests_tmp_%d" % os.getpid())
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        ctx = {"tmp": tmp}
        ctx["normalized_path"] = os.path.join(tmp, "jobs.normalized.json")
        scored_path = os.path.join(tmp, "jobs.scored.json")
        ctx["normalize"] = run(
            "normalize_jobs.py",
            [
                "--input", os.path.join("tests", "sample_jobs.json"),
                "--output", ctx["normalized_path"],
                "--report", os.path.join(tmp, "dedupe-report.md"),
            ],
        )
        if ctx["normalize"]["code"] != 0:
            print("FATAL: 标准化失败\nstdout:\n%s\nstderr:\n%s" % (ctx["normalize"]["stdout"], ctx["normalize"]["stderr"]))
            return 1
        ctx["score"] = run(
            "score_jobs.py",
            [
                "--jobs", ctx["normalized_path"],
                "--profile", os.path.join("tests", "sample_profile.json"),
                "--config", os.path.join("config", "scoring.json"),
                "--output", scored_path,
                "--report", os.path.join(tmp, "scored-report.md"),
            ],
        )
        if ctx["score"]["code"] != 0:
            print("FATAL: 评分失败\nstdout:\n%s\nstderr:\n%s" % (ctx["score"]["stdout"], ctx["score"]["stderr"]))
            return 1
        ctx["scored"] = load_json(scored_path)

        passed = failed = 0
        for code, title, function in TESTS:
            try:
                function(ctx)
                print("PASS  %s  %s" % (code, title))
                passed += 1
            except AssertionError as exc:
                print("FAIL  %s  %s -> %s" % (code, title, exc))
                failed += 1
            except Exception as exc:  # noqa: BLE001 - 测试运行器需要兜底
                print("ERROR %s  %s -> %s: %s" % (code, title, type(exc).__name__, exc))
                failed += 1

        print("\n合计：%d 通过 / %d 失败 / 共 %d" % (passed, failed, len(TESTS)))
        return 0 if failed == 0 else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
