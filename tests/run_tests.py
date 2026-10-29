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
    check(mobile.get("allow_send_like_actions") is False, "手机端不得允许发送类动作")
    check(mobile.get("allow_credential_input") is False, "手机端不得允许输入凭据")

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
            check(after[name]["state"] == "unverified", "%s 仍应为 unverified" % name)
            if before[name].get("evidence"):
                check(after[name]["evidence"] == before[name]["evidence"],
                      "%s 的已登记证据被 doctor --write 冲掉了" % name)
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
