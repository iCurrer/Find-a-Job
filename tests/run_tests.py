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


def run(script, args, extra_env=None):
    env = dict(ENV, **(extra_env or {}))
    proc = subprocess.run(
        [PYTHON, os.path.join(ROOT, "scripts", script)] + [str(item) for item in args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
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
    skill_path = os.path.join(ROOT, "skills", "job-agent", "SKILL.md")
    check(os.path.exists(skill_path), "缺少 skills/job-agent/SKILL.md")
    text = open(skill_path, "r", encoding="utf-8").read()
    check("页面" in text, "SKILL.md 应包含页面变化处理规则")
    check("暂停" in text, "SKILL.md 应要求异常时暂停")
    check("执行器" in text or "浏览器" in text, "SKILL.md 应说明执行器边界")


# ---------------------------------------------------------------------------
# T08 验证码或登录保护：暂停并交用户处理，不尝试绕过
# ---------------------------------------------------------------------------
def t08(ctx):
    text = open(os.path.join(ROOT, "skills", "job-agent", "SKILL.md"), "r", encoding="utf-8").read()
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


# ---------------------------------------------------------------------------
# T13 P0 能力盘点：doctor 必须给出可复现证据，且不得自证浏览器/移动能力
# ---------------------------------------------------------------------------
def t13(ctx):
    proc = subprocess.run(
        [PYTHON, os.path.join(ROOT, "scripts", "jobagent.py"), "doctor"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=ENV,
    )
    check(proc.returncode == 0, "doctor 应返回 0：%s%s" % (proc.stdout[:300], proc.stderr[:300]))
    payload = json.loads(proc.stdout)
    check(payload["ok"] is True, "doctor 应判定 ok")
    check(payload["missing_dirs"] == [], "目录应完整，实际缺失：%s" % payload["missing_dirs"])

    capabilities = payload["capabilities"]
    for name in ("file_read", "file_write", "script_exec", "stdlib_only"):
        check(name in capabilities, "能力矩阵缺少 %s" % name)
        check(capabilities[name]["state"] == "verified", "%s 应为 verified" % name)
        check(capabilities[name].get("evidence"), "%s 必须带可复现证据" % name)

    for name in ("browser_exec", "mobile_exec", "email_exec"):
        check(name in capabilities, "能力矩阵缺少 %s" % name)
        check(capabilities[name]["state"] == "unverified", "%s 不得被脚本自证为 verified" % name)

    check("require_confirmation" in open(os.path.join(ROOT, "config", "settings.json"), "r", encoding="utf-8").read(),
          "settings.json 应保留外部写入的确认点配置")


# ---------------------------------------------------------------------------
# T14 装载适配：从项目外的目录调用，仍能解析到项目根并跑通
# ---------------------------------------------------------------------------
def t14(ctx):
    import tempfile

    outside = tempfile.gettempdir()
    entry = os.path.join(ROOT, "scripts", "jobagent.py")

    proc = subprocess.run(
        [PYTHON, entry, "doctor"],
        cwd=outside,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=ENV,
    )
    check(proc.returncode == 0, "从项目外目录调用 doctor 应成功：%s%s" % (proc.stdout[:300], proc.stderr[:300]))
    payload = json.loads(proc.stdout)
    check(payload["ok"] is True, "从项目外目录调用仍应解析到项目根")
    check(payload["missing_dirs"] == [], "根解析错误，缺失目录：%s" % payload["missing_dirs"])

    env_override = dict(ENV, JOBAGENT_ROOT=ROOT.replace("\\", "/"))
    proc2 = subprocess.run(
        [PYTHON, entry, "status"],
        cwd=outside,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env_override,
    )
    check(proc2.returncode == 0, "设置 JOBAGENT_ROOT 后 status 应成功：%s%s" % (proc2.stdout[:300], proc2.stderr[:300]))
    payload2 = json.loads(proc2.stdout)
    check(payload2["ok"] is True, "JOBAGENT_ROOT 应生效")
    for key, value in (payload2.get("stores") or {}).items():
        if value:
            check(not os.path.isabs(value), "产物路径不得为绝对路径：%s=%s" % (key, value))


# ---------------------------------------------------------------------------
# T15 执行器规范：浏览器优先用宿主内置能力、手机走 adb 的硬约束必须在文档里写死
# ---------------------------------------------------------------------------
def t15(ctx):
    ref_dir = os.path.join(ROOT, "skills", "job-agent", "references")

    browser_path = os.path.join(ref_dir, "browser-policy.md")
    check(os.path.exists(browser_path), "缺少 references/browser-policy.md")
    browser = open(browser_path, "r", encoding="utf-8").read()

    # 必须优先用宿主内置浏览器能力，且明确禁用自建浏览器栈
    for token in ("mcp__browser__", "tabs_claim", "user_open_tabs", "dom_cua_get_visible_dom"):
        check(token in browser, "browser-policy 应说明内置浏览器工具 %s" % token)
    for forbidden in ("Selenium", "Playwright", "Puppeteer"):
        check(forbidden in browser, "browser-policy 应点名禁止 %s" % forbidden)
    check("DOM 优先于坐标" in browser, "browser-policy 应声明 DOM 优先于坐标")
    # 核心安全设计：不由 Agent 登录
    check("不由我们完成登录" in browser or "不接触账号密码" in browser,
          "browser-policy 应明确登录由用户完成")
    # 提交只允许一次
    check("一次" in browser and ("submit" in browser.lower() or "提交" in browser),
          "browser-policy 应限制提交只点一次")
    # 截图落盘位置
    check("logs/screens" in browser, "browser-policy 应规定截图只能落 logs/screens/")

    adb_path = os.path.join(ref_dir, "android-adb-policy.md")
    check(os.path.exists(adb_path), "缺少 references/android-adb-policy.md")
    adb = open(adb_path, "r", encoding="utf-8").read()

    # 手机端必须永不代点发送类动作
    check("allow_send_like_actions" in open(os.path.join(ROOT, "config", "settings.json"), "r", encoding="utf-8").read()
          or "禁止" in adb, "android-adb-policy 应禁止发送类动作")
    check("发送" in adb and "禁止" in adb, "android-adb-policy 应明确禁止发送/投递类按钮")
    # 中文输入硬限制必须写明（input text 不支持非 ASCII）
    check("input text" in adb, "android-adb-policy 应写明 adb input text 的用法")
    check("ASCII" in adb or "非 ASCII" in adb, "android-adb-policy 应写明中文输入的限制")
    # 无线调试风险
    check("tcpip" in adb, "android-adb-policy 应禁止 adb tcpip")
    # 定位优先
    check("uiautomator" in adb, "android-adb-policy 应要求先用 uiautomator 定位")
    # 隐私
    check("logs/screens" in adb, "android-adb-policy 应规定截图只能落 logs/screens/")
    # 必须诚实声明当前未验证
    check("unverified" in adb, "android-adb-policy 应标注当前能力状态为 unverified")


# ---------------------------------------------------------------------------
# T16 执行器配置：settings 声明了执行器优先级，且 doctor --write 不得冲掉已登记的证据
# ---------------------------------------------------------------------------
def t16(ctx):
    settings_path = os.path.join(ROOT, "config", "settings.json")
    settings = load_json(settings_path)

    policy = settings.get("executor_policy")
    check(isinstance(policy, dict), "settings.json 应包含 executor_policy")
    browser = policy.get("browser") or {}
    mobile = policy.get("mobile") or {}

    check(browser.get("runtime") == "workbuddy_builtin",
          "浏览器执行器应固定为宿主内置，实际：%r" % browser.get("runtime"))
    check(browser.get("login_by_agent") is False, "不得由 Agent 完成登录")
    check(browser.get("max_submit_clicks_per_job") == 1, "每岗位提交点击上限应为 1")
    for dep in ("selenium", "playwright", "puppeteer"):
        check(dep in (browser.get("forbidden_dependencies") or []),
              "禁止依赖清单应包含 %s" % dep)

    check(mobile.get("runtime") == "adb", "手机执行器应为 adb")
    # 手机端现在允许操控，但发送类必须逐条确认，且禁止批量
    check(mobile.get("send_like_policy") == "confirm_each", "发送类动作应为逐条确认（confirm_each）")
    check(mobile.get("allow_bulk_send") is False, "手机端不得允许批量发送")
    check(mobile.get("max_send_actions_per_job") == 1, "每岗位发送动作上限应为 1")
    check((mobile.get("action_levels") or {}).get("send_like") == "confirm_each", "action_levels.send_like 应为 confirm_each")
    check(mobile.get("allow_credential_input") is False, "手机端不得允许输入凭据")
    check(mobile.get("element_strategy") == "uiautomator_before_coordinate", "必须先 uiautomator 定位再考虑坐标")
    check(mobile.get("min_interval_seconds", 0) >= 2, "动作间隔应 ≥ 2 秒，避免触发风控")

    email = policy.get("email") or {}
    check(email.get("runtime") == "user_mail_connector", "邮件执行器应为用户本人邮箱连接器")
    check(email.get("preferred_connector") == "qq-mail", "首选邮箱连接器应为 qq-mail")
    check(email.get("forbidden_connector") == "agent-mail", "必须禁止用 agent-mail 代发求职邮件")
    check(email.get("allow_bulk_send") is False, "不得允许批量发信")
    check(email.get("max_followups_per_job") == 1, "同一岗位跟进上限应为 1")
    check(email.get("require_full_body_preview") is True, "必须要求展示邮件全文后才能发")

    check(policy.get("screenshot_dir") == "logs/screens", "截图目录应为 logs/screens")

    # 截图目录必须被 git 忽略，否则隐私截图会进公开仓库
    proc = subprocess.run(
        ["git", "check-ignore", "-q", "logs/screens/probe.png"],
        cwd=ROOT, capture_output=True, text=True,
    )
    check(proc.returncode == 0, "logs/screens/ 必须被 .gitignore 排除")

    # doctor --write 后，外部能力的已登记证据必须保留（不得被通用文案冲掉）
    before = load_json(settings_path)["verified_capabilities"]
    backup = settings_path + ".t16bak"
    shutil.copy2(settings_path, backup)
    try:
        proc = subprocess.run(
            [PYTHON, os.path.join(ROOT, "scripts", "jobagent.py"), "doctor", "--write"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=ENV,
        )
        check(proc.returncode == 0, "doctor --write 应成功：%s" % proc.stderr[:300])
        after = load_json(settings_path)["verified_capabilities"]
        for name in ("browser_exec", "mobile_exec", "email_exec"):
            check(
                after[name]["state"] == before[name]["state"],
                "%s 的状态被 doctor --write 改动了（%s -> %s）" % (name, before[name]["state"], after[name]["state"]),
            )
        # mobile_exec 的证据会被实时 adb 探测刷新（刻意行为），其余两项必须原样保留。
        for name in ("browser_exec", "email_exec"):
            if before[name].get("evidence"):
                check(after[name]["evidence"] == before[name]["evidence"],
                      "%s 的已登记证据被 doctor --write 冲掉了" % name)
        check("adb" in (after["mobile_exec"].get("evidence") or "").lower()
              or after["mobile_exec"]["state"] == "verified",
              "mobile_exec 的证据应反映本次 adb 探测结果")
        check("executor_policy" in load_json(settings_path), "doctor --write 不得删除 executor_policy")
    finally:
        shutil.copy2(backup, settings_path)
        os.remove(backup)


# ---------------------------------------------------------------------------
# T17 邮件通道：必须用用户本人邮箱连接器，且发送前必须展示全文并单独确认
# ---------------------------------------------------------------------------
def t17(ctx):
    ref = os.path.join(ROOT, "skills", "job-agent", "references", "email-policy.md")
    check(os.path.exists(ref), "缺少 references/email-policy.md")
    text = open(ref, "r", encoding="utf-8").read()

    check("qq-mail" in text, "email-policy 应指定 QQ 邮箱连接器 qq-mail")
    check("agent-mail" in text, "email-policy 应明确不用 agent-mail 代发求职邮件")
    check("智能体邮箱" in text, "email-policy 应说明 agent-mail 是智能体邮箱、不是求职邮箱")
    # 未连接时必须提示用户打开，而不是自己绕
    check("未连接" in text and ("提示用户" in text or "打开" in text),
          "email-policy 应规定连接器未连接时提示用户打开")
    # 全文 + 一次明确确认
    check("全文" in text, "email-policy 应要求展示邮件全文")
    check("一次明确" in text or "明确发送许可" in text or "一次确认" in text,
          "email-policy 应要求一次明确的发送许可")
    # 禁止批量与重复跟进
    check("批量" in text and "禁止" in text, "email-policy 应禁止批量发信")
    check("同一岗位只发一次" in text or "max_followups_per_job" in text or "仅一次" in text,
          "email-policy 应限制同一岗位仅跟进一次")
    # 不得把密码写进对话或文件
    check("密码" in text or "授权码" in text, "email-policy 应禁止把邮箱密码/授权码写入文件或对话")
    # 收件地址核对（低级的抄错地址风险）
    check("核对" in text, "email-policy 应要求核对收件人地址")
    # 收费/索要证件必须拒发
    check("押金" in text or "培训费" in text, "email-policy 应把收费类招聘列为不发")


# ---------------------------------------------------------------------------
# T18 简历前置：基础简历是步骤 0，且不得用占位符堆出空简历
# ---------------------------------------------------------------------------
def t18(ctx):
    policy_path = os.path.join(ROOT, "skills", "job-agent", "references", "resume-policy.md")
    policy = open(policy_path, "r", encoding="utf-8").read()

    check("步骤 0" in policy, "resume-policy 应有「步骤 0：基础简历」章节")
    check("main-resume-v1.0.md" in policy, "resume-policy 应指出基础简历产出路径")
    check("不得用占位符堆出" in policy, "resume-policy 应禁止用占位符堆出看似完整的空简历")
    check("缺口清单" in policy, "resume-policy 应要求前置条件不足时输出缺口清单")

    skill_path = os.path.join(ROOT, "skills", "job-agent", "SKILL.md")
    skill = open(skill_path, "r", encoding="utf-8").read()

    # 主流程必须是九步且简历在最前
    check("九步" in skill, "SKILL.md 主流程应声明为九步")
    check("建立基础简历 → 导入岗位" in skill, "主流程顺序应为「建立基础简历 → 导入岗位」")
    check("### 步骤 0：建立基础简历" in skill, "SKILL.md 应有步骤 0 章节")
    # 禁止把示例档案当真实简历交付
    check("示例简历" in skill or "示例档案" in skill, "SKILL.md 应要求说明占位档案生成的只是示例简历")
    # 定制版必须从基础简历派生
    check("从基础简历派生" in skill, "步骤 5 应要求从基础简历派生，而非从零起草")
    # 邮件通道需在步骤 5 衔接
    check("email-policy.md" in skill, "SKILL.md 应引用 email-policy.md")


# ---------------------------------------------------------------------------
# T19 搜索画像与策略：平台配置必须自证过、通道顺序与硬边界必须写死
# ---------------------------------------------------------------------------
def t19(ctx):
    config_path = os.path.join(ROOT, "config", "search.json")
    check(os.path.exists(config_path), "缺少 config/search.json")
    config = load_json(config_path)

    for key in ("cities", "keyword_groups", "platforms", "exclude_keywords", "constraints", "search_policy"):
        check(key in config, "search.json 缺少字段: %s" % key)

    check(len(config["cities"]) >= 1, "至少要有一个搜索城市")
    check(len(config["keyword_groups"]) >= 1, "至少要有一个关键词组")

    for platform in config["platforms"]:
        pid = platform.get("id")
        check(pid, "platform 缺少 id")
        check(str(platform.get("search_url", "")).startswith("https://"), "%s 的 search_url 必须是 https" % pid)
        check(str(platform.get("browse_url", "")).startswith("https://"), "%s 的 browse_url 必须是 https" % pid)
        check(
            platform.get("fetch_mode") in ("webfetch_ok", "needs_dom"),
            "%s 的 fetch_mode 非法: %s" % (pid, platform.get("fetch_mode")),
        )
        check(isinstance(platform.get("keyword_param_works"), bool), "%s 必须声明 keyword_param_works" % pid)
        if platform.get("keyword_param_works"):
            check("{keyword}" in str(platform.get("search_url")), "%s 宣称支持关键词，则 search_url 需含 {keyword}" % pid)
        if platform.get("params_verified"):
            check(platform.get("verified_at"), "%s 标为已核对就必须写 verified_at" % pid)

    excludes = " ".join(config["exclude_keywords"])
    for word in ("审计", "销售", "硬件"):
        check(word in excludes, "排除词应覆盖个人明确不投的方向: %s" % word)

    constraints = config["constraints"]
    check(constraints.get("graduate_year") == 2027, "届别应为 2027")
    check(int(constraints.get("max_pages_per_query") or 99) <= 5, "单查询翻页上限不得过高")

    policy_path = os.path.join(ROOT, "skills", "job-agent", "references", "job-search-policy.md")
    check(os.path.exists(policy_path), "缺少 references/job-search-policy.md")
    policy = open(policy_path, encoding="utf-8").read()

    check("C → B → A" in policy, "搜索策略必须固定通道尝试顺序 C → B → A")
    check("翻页上限" in policy, "搜索策略必须写明翻页上限")
    check("验证码" in policy and "立即停止" in policy, "搜索策略必须写明遇验证码立即停止")
    check("非公开接口" in policy, "搜索策略必须禁止调用平台非公开接口")
    check("campus_vertical_search" in policy, "搜索策略必须规定 source 取值")
    check("凭常识编造" in policy or "不得假装已搜" in policy, "搜索策略必须禁止能力不足时编造岗位")

    browser_policy = open(
        os.path.join(ROOT, "skills", "job-agent", "references", "browser-policy.md"), encoding="utf-8"
    ).read()
    check("C 路径" in browser_policy and "WebFetch" in browser_policy, "browser-policy 需补充 C 路径（文本只读）")
    check("X（禁止）" in browser_policy, "登录类操作应编号为 X（禁止），不得占用 C")


# ---------------------------------------------------------------------------
# T20 搜索计划生成：链接可点、编码正确、排除词在生成前生效、不写采集结果
# ---------------------------------------------------------------------------
def t20(ctx):
    import tempfile

    proc = run("search_urls.py", ["--stdout"])
    check(proc["code"] == 0, "生成搜索计划应成功：%s%s" % (proc["stdout"][:300], proc["stderr"][:300]))
    check("https://" in proc["stdout"], "计划里应含可点开的链接")
    check("本文件只有搜索链接" in proc["stdout"] or "不含任何采集结果" in proc["stdout"], "计划应声明不含采集结果")

    with tempfile.TemporaryDirectory() as tmp:
        proc = run("search_urls.py", ["--out-dir", tmp, "--city", "上海", "--group", "fin_impl"])
        check(proc["code"] == 0, "限定条件生成应成功：%s%s" % (proc["stdout"][:300], proc["stderr"][:300]))
        payload = proc["json"]
        check(payload["ok"] is True, "应返回 ok=true")
        plan_files = [name for name in os.listdir(tmp) if name.startswith("search-plan-") and name.endswith(".json")]
        check(plan_files, "应在输出目录生成 search-plan-*.json")
        plan = load_json(os.path.join(tmp, sorted(plan_files)[-1]))["plan"]
        check(len(plan) > 0, "应生成至少一条查询")

        for item in plan:
            check(item["url"].startswith("https://"), "链接必须是 https：%s" % item["url"])
            check(" " not in item["url"], "链接不得含空格（说明编码有误）：%s" % item["url"])
            check(item["city"] == "上海", "城市过滤失效：%s" % item["city"])
            check(item["keyword_param_works"] in (True, False), "keyword_param_works 应为布尔值")

        non_ascii = [item for item in plan if any(ord(ch) > 127 for ch in item["url"].split("://", 1)[1])]
        check(not non_ascii, "链接不得含未编码的中文：%s" % non_ascii[:1])

        # 排除词必须在生成前生效：把该组每个关键词都命中排除词，应整组跳过
        config = load_json(os.path.join(ROOT, "config", "search.json"))
        config["exclude_keywords"] = list(config["exclude_keywords"]) + ["会计", "税务"]
        custom = os.path.join(tmp, "search-custom.json")
        with open(custom, "w", encoding="utf-8") as fh:
            json.dump(config, fh, ensure_ascii=False)

        proc = run("search_urls.py", ["--config", custom, "--out-dir", tmp, "--group", "accounting"])
        check(proc["code"] == 1, "关键词全被排除时应以退出码 1 结束，实际 %s" % proc["code"])
        payload = proc["json"]
        check(payload["ok"] is False, "全被排除时 ok 应为 false")
        check("没有生成任何查询" in (payload.get("error") or ""), "应说明未生成任何查询")
        skipped = payload.get("skipped") or []
        check(skipped, "应报告被排除的关键词")
        check(
            all("排除词" in (item.get("reason") or "") for item in skipped),
            "排除原因应指明命中的排除词：%s" % skipped,
        )

        # 清理：临时目录在 with 结束时自动删除
        for name in os.listdir(tmp):
            if name.startswith("search-plan-"):
                os.remove(os.path.join(tmp, name))


# ---------------------------------------------------------------------------
# T21 学历门槛语义：区分「最低要求 / 仅优先 / 团队描述」
# ---------------------------------------------------------------------------
def _custom_pipeline(tmp, jobs, tag):
    """按给定岗位列表跑 标准化 + 评分，返回 (normalized, scored)。"""
    raw_path = os.path.join(tmp, "raw_%s.json" % tag)
    normalized_path = os.path.join(tmp, "normalized_%s.json" % tag)
    scored_path = os.path.join(tmp, "scored_%s.json" % tag)
    with open(raw_path, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": "1.0", "jobs": jobs}, fh, ensure_ascii=False)
    proc = run(
        "normalize_jobs.py",
        ["--input", raw_path, "--output", normalized_path, "--report", os.path.join(tmp, "dedupe_%s.md" % tag)],
    )
    check(proc["code"] == 0, "自定义岗位标准化失败：%s" % (proc["json"] or {}).get("error"))
    proc = run(
        "score_jobs.py",
        [
            "--jobs", normalized_path,
            "--profile", os.path.join("tests", "sample_profile.json"),
            "--config", os.path.join("config", "scoring.json"),
            "--output", scored_path,
            "--report", os.path.join(tmp, "scored_%s.md" % tag),
        ],
    )
    check(proc["code"] == 0, "自定义岗位评分失败：%s" % (proc["json"] or {}).get("error"))
    return load_json(normalized_path), load_json(scored_path)


def _candidate_job(title, requirements, **extra):
    item = {
        "company": "示例公司",
        "title": title,
        "location": "上海",
        "url": "https://careers.example.com/%s" % title,
        "source": "company_career_site",
        "requirements": requirements,
        "collected_at": "2026-10-29T10:00:00+08:00",
    }
    item.update(extra)
    return item


def t21(ctx):
    _normalized, scored = _custom_pipeline(
        ctx["tmp"],
        [
            _candidate_job("学历优先岗", ["本科及以上学历，博士优先"]),
            _candidate_job("博士团队岗", ["由博士团队领衔，负责课题研究"]),
            _candidate_job("硕士门槛岗", ["硕士及以上学历"]),
        ],
        "degree",
    )
    for title in ("学历优先岗", "博士团队岗"):
        job = job_by_title(scored, title)
        check(
            job["blocked"] is False,
            "%s 不应被学历门槛阻断（当前状态：%s）—— 「博士优先」「博士团队」不是最低学历要求" % (title, job["status"]),
        )
    hard = [dim for dim in job_by_title(scored, "学历优先岗")["score_breakdown"] if dim["key"] == "hard_requirements"][0]
    check("优先" in " ".join(hard["reasons"]) + " ".join(hard["risks"]), "应说明该岗位只是「博士优先」，非门槛")
    blocked_job = job_by_title(scored, "硕士门槛岗")
    check(blocked_job["blocked"] is True, "「硕士及以上」对本科档案仍应阻断")
    check(blocked_job["status"] == "不匹配", "被阻断岗位状态应为不匹配，实际 %s" % blocked_job["status"])


# ---------------------------------------------------------------------------
# T22 主流程失败传播：档案校验失败后不得继续评分
# ---------------------------------------------------------------------------
def t22(ctx):
    bad_profile = os.path.join(ctx["tmp"], "bad_profile.json")
    with open(bad_profile, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": "1.0"}, fh, ensure_ascii=False)

    proc = run("jobagent.py", ["run", "--profile", bad_profile])
    check(proc["code"] == 1, "档案校验失败时入口应返回退出码 1，实际 %s" % proc["code"])
    payload = proc["json"]
    check(payload and payload["ok"] is False, "ok 应为 false")
    check(payload.get("failed_at") == "validate_profile.py", "failed_at 应指向档案校验，实际 %r" % payload.get("failed_at"))
    statuses = {step["script"]: step["status"] for step in payload["steps"]}
    check(statuses.get("normalize_jobs.py") == "skipped", "档案校验失败后标准化必须跳过")
    check(statuses.get("score_jobs.py") == "skipped", "档案校验失败后评分必须跳过")
    check(payload["steps"][0]["code"] == 1, "应保留真实的失败退出码，而不是笼统记 false")


# ---------------------------------------------------------------------------
# T23 薪资解析：区间两端单位独立识别
# ---------------------------------------------------------------------------
def t23(ctx):
    normalized, _scored = _custom_pipeline(
        ctx["tmp"],
        [
            _candidate_job("混合单位岗", ["本科及以上"], salary="8千-1.2万"),
            _candidate_job("日薪岗", ["本科及以上"], salary="150-200元/天"),
            _candidate_job("年薪岗", ["本科及以上"], salary="20-30万/年"),
            _candidate_job("大写K岗", ["本科及以上"], salary="15-25K"),
        ],
        "salary",
    )

    mixed = job_by_title(normalized, "混合单位岗")
    check(mixed["salary_min"] == 8000, "「8千-1.2万」下限应为 8000，实际 %s" % mixed["salary_min"])
    check(mixed["salary_max"] == 12000, "「8千-1.2万」上限应为 12000，实际 %s" % mixed["salary_max"])

    daily = job_by_title(normalized, "日薪岗")
    check(daily["salary_period"] == "day", "「150-200元/天」周期应为 day")
    check(daily["salary_month_equivalent"]["min"] == 3150, "日薪下限按月折算应为 3150，实际 %s" % daily["salary_month_equivalent"]["min"])

    yearly = job_by_title(normalized, "年薪岗")
    check(yearly["salary_period"] == "year", "「20-30万/年」周期应为 year")
    check(yearly["salary_max"] == 300000, "年薪上限应为 300000，实际 %s" % yearly["salary_max"])

    k = job_by_title(normalized, "大写K岗")
    check((k["salary_min"], k["salary_max"]) == (15000, 25000), "「15-25K」应解析为 15000-25000，实际 %s-%s" % (k["salary_min"], k["salary_max"]))


# ---------------------------------------------------------------------------
# T24 投递记录与审计日志一致性：先记意图、日志不可写则不动状态
# ---------------------------------------------------------------------------
def t24(ctx):
    store = os.path.join(ctx["tmp"], "audit_apps.json")
    log = os.path.join(ctx["tmp"], "audit.jsonl")
    with open(store, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": "1.0", "applications": []}, fh, ensure_ascii=False)

    first = run(
        "update_application.py",
        ["--job-id", "job-audit-1", "--status", "待准备", "--company", "示例公司",
         "--title", "财务实施顾问", "--store", store, "--log", log],
    )
    check(first["code"] == 0 and first["json"]["ok"], "首次登记应成功：%s" % (first["json"] or {}).get("error"))
    check(first["json"]["audit"]["intent"] and first["json"]["audit"]["committed"], "审计应同时写入 intent 与 committed")

    # 日志路径不可写：必须在改状态之前中止
    blocker = os.path.join(ctx["tmp"], "blocked_as_file")
    with open(blocker, "w", encoding="utf-8") as fh:
        fh.write("not a directory")
    before_status = load_json(store)["applications"][0]["status"]
    second = run(
        "update_application.py",
        ["--job-id", "job-audit-1", "--status", "待确认", "--store", store,
         "--log", os.path.join(blocker, "audit.jsonl")],
    )
    check(second["code"] == 1, "日志不可写时应返回退出码 1")
    check(second["json"]["ok"] is False, "日志不可写时 ok 应为 false")
    check("未做任何修改" in second["json"]["error"], "错误信息应说明状态未被修改")
    check(load_json(store)["applications"][0]["status"] == before_status, "日志不可写时不得改变业务状态")

    # 悬空事件（只有 intent 没有 committed）应被检测出来
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": "2026-10-29T10:00:00+08:00", "phase": "intent",
                             "event_id": "orphan-001", "job_id": "job-audit-1"}, ensure_ascii=False) + "\n")
    third = run(
        "update_application.py",
        ["--job-id", "job-audit-1", "--status", "待确认", "--store", store, "--log", log],
    )
    check(third["code"] == 0, "正常推进应成功：%s" % (third["json"] or {}).get("error"))
    check(
        any("orphan-001" in warn for warn in third["json"]["warnings"]),
        "应告警提示存在未完成的审计事件",
    )


# ---------------------------------------------------------------------------
# T25 doctor 不得静默降级已登记的外部能力
# ---------------------------------------------------------------------------
def t25(ctx):
    settings_path = os.path.join(ROOT, "config", "settings.json")
    backup = settings_path + ".t25bak"
    shutil.copy2(settings_path, backup)
    try:
        settings = load_json(settings_path)
        settings["verified_capabilities"]["browser_exec"] = {
            "state": "verified",
            "evidence": "实测：接管已登录标签页读取岗位列表成功",
            "checked_at": "2026-10-29T15:00:00+08:00",
        }
        with open(settings_path, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, ensure_ascii=False, indent=2)

        proc = run("jobagent.py", ["doctor", "--write"])
        check(proc["code"] == 0, "doctor --write 应成功：%s" % proc["stderr"][:200])
        after = load_json(settings_path)["verified_capabilities"]["browser_exec"]
        check(after["state"] == "verified", "doctor --write 把已登记的 verified 降级为 %s" % after["state"])
        check(
            after["evidence"] == "实测：接管已登录标签页读取岗位列表成功",
            "doctor --write 覆盖了已登记的实测证据",
        )

        proc = run("jobagent.py", ["doctor", "--write", "--reset-external"])
        check(proc["code"] == 0, "doctor --reset-external 应成功")
        reset = load_json(settings_path)["verified_capabilities"]["browser_exec"]
        check(reset["state"] == "unverified", "显式 --reset-external 后应重置为 unverified")
    finally:
        shutil.copy2(backup, settings_path)
        os.remove(backup)


# ---------------------------------------------------------------------------
# T26 adb 操控链路：用假 adb 桩验证设备选择、UI 解析、文本定位与点击坐标
# ---------------------------------------------------------------------------
FAKE_UI_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" text="" resource-id="" class="android.widget.FrameLayout" bounds="[0,0][1080,2400]">
    <node index="0" text="\u8d22\u52a1\u5b9e\u65bd\u987e\u95ee" resource-id="com.hpbr.bosszhipin:id/job_name"
          class="android.widget.TextView" clickable="false" enabled="true" bounds="[60,400][700,460]" />
    <node index="1" text="\u7acb\u5373\u6c9f\u901a" resource-id="com.hpbr.bosszhipin:id/btn"
          class="android.widget.Button" clickable="true" enabled="true" bounds="[760,2000][1020,2100]" />
  </node>
</hierarchy>
"""

FAKE_ADB_PY = '''import os, sys
args = sys.argv[1:]
while args and args[0] in ("-s", "-d", "-e"):
    args = args[2:] if args[0] == "-s" else args[1:]
here = os.path.dirname(os.path.abspath(__file__))
def emit(line=""):
    print(line)
if args[:1] == ["devices"]:
    emit("List of devices attached")
    emit("FAKESERIAL123          device product:raven model:Pixel_7 device:raven")
elif args[:1] == ["version"]:
    emit("Android Debug Bridge version 1.0.41")
elif args[:3] == ["shell", "wm", "size"]:
    emit("Physical size: 1080x2400")
elif args[:2] == ["shell", "getprop"]:
    emit({"ro.product.model": "Pixel_7", "ro.build.version.release": "14"}.get(args[2], ""))
elif args[:3] == ["shell", "uiautomator", "dump"]:
    emit("UI hierchary dumped to: %s" % args[3])
elif args[:1] == ["pull"]:
    with open(os.path.join(here, "ui.xml"), "rb") as src, open(args[2], "wb") as dst:
        dst.write(src.read())
    emit("1 file pulled.")
else:
    emit("")
'''


def _make_fake_adb(tmp):
    """造一个假 adb：Windows 用 .cmd 包装，其他平台用 .sh，逻辑都在 .py 里。"""
    directory = os.path.join(tmp, "fakeadb")
    os.makedirs(directory, exist_ok=True)
    script = os.path.join(directory, "fake_adb.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(FAKE_ADB_PY)
    with open(os.path.join(directory, "ui.xml"), "w", encoding="utf-8") as fh:
        fh.write(FAKE_UI_XML)
    if os.name == "nt":
        shim = os.path.join(directory, "adb.cmd")
        with open(shim, "w", encoding="utf-8", newline="\r\n") as fh:
            fh.write('@echo off\r\n"%s" "%%~dp0fake_adb.py" %%*\r\n' % sys.executable)
    else:
        shim = os.path.join(directory, "adb")
        with open(shim, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nexec "%s" "$(dirname "$0")/fake_adb.py" "$@"\n' % sys.executable)
        os.chmod(shim, 0o755)
    return shim


def t26(ctx):
    shim = _make_fake_adb(ctx["tmp"])
    env = {"ADB": shim}

    status = run("adb_ctl.py", ["status"], extra_env=env)
    check(status["code"] == 0, "假 adb 下 status 应成功：%s" % (status["json"] or {}).get("error"))
    payload = status["json"]
    check(payload["model"] == "Pixel_7", "应读出机型，实际 %r" % payload.get("model"))
    check(payload["screen"]["width"] == 1080 and payload["screen"]["height"] == 2400, "应解析出屏幕分辨率")

    nodes = run("adb_ctl.py", ["dump"], extra_env=env)
    check(nodes["code"] == 0, "dump 应成功：%s" % (nodes["json"] or {}).get("error"))
    texts = [node["text"] for node in nodes["json"]["nodes"]]
    check("立即沟通" in texts, "dump 应解析出中文按钮文本，实际 %r" % texts)

    tap = run("adb_ctl.py", ["tap", "--text", "立即沟通"], extra_env=env)
    check(tap["code"] == 0, "按文本点击应成功：%s" % (tap["json"] or {}).get("error"))
    check(tap["json"]["tap"]["x"] == 890 and tap["json"]["tap"]["y"] == 2050,
          "点击坐标应为元素中心 (890,2050)，实际 %r" % tap["json"]["tap"])

    chinese = run("adb_ctl.py", ["text", "财务"], extra_env=env)
    check(chinese["code"] == 1, "中文输入必须被拒绝（input text 只支持 ASCII）")
    check("ASCII" in chinese["json"]["error"], "拒绝原因应说明 ASCII 限制")

    denied = run("adb_ctl.py", ["launch", "--package", "com.hpbr.bosszhipin"], extra_env={})
    check(denied["code"] == 2, "没有 adb 时应返回环境缺失退出码 2")


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
    ("T13", "能力盘点有证据且不自证浏览器", t13),
    ("T14", "项目外目录仍能解析根", t14),
    ("T15", "浏览器/手机执行器规范硬约束", t15),
    ("T16", "执行器配置与证据不被覆盖", t16),
    ("T17", "邮件通道与发送确认约束", t17),
    ("T18", "简历前置与缺口清单", t18),
    ("T19", "搜索画像与通道硬约束", t19),
    ("T20", "搜索计划生成与排除词生效", t20),
    ("T21", "学历门槛语义不误判", t21),
    ("T22", "档案校验失败即停止后续", t22),
    ("T23", "混合单位薪资解析", t23),
    ("T24", "投递审计一致性", t24),
    ("T25", "doctor 不降级已验证能力", t25),
    ("T26", "adb 操控链路（假设备）", t26),
]


def main():
    # 不用 tempfile.mkdtemp：Windows 下其 0700 目录可能被安全策略拒绝写入。
    tmp = os.path.join(ROOT, ".tests_tmp_%d" % os.getpid())
    shutil.rmtree(tmp, ignore_errors=True)
    # 兜底清理历史残留：文件被占用时 Windows 的 rmtree 会静默失败，
    # 只清自己那个目录不够，下次运行前顺手扫一遍。
    for name in os.listdir(ROOT):
        if name.startswith(".tests_tmp_") and name != os.path.basename(tmp):
            shutil.rmtree(os.path.join(ROOT, name), ignore_errors=True)
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
