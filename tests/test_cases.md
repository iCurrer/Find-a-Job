# 测试用例（T01–T14）

T01–T12 对应方案 9.1 的必测用例；T13–T14 为「装进 WorkBuddy 后能否跑通」补充的装载适配用例。

## 运行方式

在项目根 `JobAgent/` 下执行：

```bash
python tests/run_tests.py
```

脚本会在项目内创建临时目录 `.tests_tmp_<pid>/` 跑完整流程（档案校验 → 标准化去重 → 评分 → 状态机），结束后自动清理，**不会改动 `profile/`、`jobs/raw/`、`applications/` 中的真实数据**。

当前结果：**14/14 通过**（2026-10-29，Python 3.13）。

## 用例与实现

| 编号 | 场景 | 测试方式 | 预期结果 | 现状 |
| --- | --- | --- | --- | --- |
| T01 | 个人档案存在字段缺失 | 删除 `skills` 与 `education[0].school` 后校验 | 退出码 1，错误信息逐项指出缺失字段，不自动补造 | PASS |
| T02 | 两个岗位链接不同但职位信息相同 | 同一公司/岗位/城市、不同 URL 的两条原始岗位 | 识别为 1 组疑似重复，保留两条来源，去重键相同、`job_id` 不同 | PASS |
| T03 | 岗位要求证书但档案未确认 | 岗位要求教师资格证，档案中该证书为备考中 | 写入 `risk_flags`，不声称已取得，状态不为优先投递 | PASS |
| T04 | 岗位与个人硬性条件冲突 | 岗位要求硕士，档案为本科 | `blocked=true`、状态 `不匹配`、硬性维度 0 分，理由写明学历冲突 | PASS |
| T05 | 简历需要不存在的数字/未确认事实 | 校验含 pending 证书的档案 | `pending_facts` 与 `open_questions` 被列出，报告中不写成确定事实 | PASS |
| T06 | 同一岗位已经提交 | 已提交后再尝试创建记录/重复提交 | 退出码 1 并提示重复申请风险，不产生第二条记录 | PASS |
| T07 | 浏览器页面结构变化 | 检查 `skills/job-agent/SKILL.md` 强制规则 | 要求停止自动操作、暂停并报告异常 | PASS（规则层） |
| T08 | 出现验证码或登录保护 | 检查 `skills/job-agent/SKILL.md` 强制规则 | 要求暂停交用户处理，不尝试绕过 | PASS（规则层） |
| T09 | 提交按钮点击后无确认结果 | 无 `--evidence` 时改为已提交 | 退出码 1，状态保持 `执行中`，不写 `submitted_at` | PASS |
| T10 | 脚本执行中断 | 传入损坏 JSON | 退出码 1、输出结构化错误、不产出半成品报告、无裸 traceback | PASS |
| T11 | 恢复备份 | 状态推进后检查 `.bak` 并回滚 | 备份为写入前状态，覆盖后成功还原 | PASS |
| T12 | 未授权外发个人信息 | 静态扫描 `scripts/*.py` | 无网络库依赖；`settings.json` 保留外部写入确认点 | PASS |
| T13 | P0 能力盘点是否可信 | 执行 `jobagent.py doctor` | 文件读/写、脚本执行、标准库自检均为 `verified` 且带 `evidence`；`browser_exec`/`mobile_exec` 恒为 `unverified`（不得自证） | PASS |
| T14 | Skill 装在别处还能不能跑 | 从项目外目录（系统临时目录）调用 `jobagent.py`，再用 `JOBAGENT_ROOT` 覆盖 | 两种方式都能解析到项目根，`missing_dirs` 为空，产物路径非绝对路径 | PASS |
| T15 | 执行器规范是否真的把约束写死 | 读 `references/browser-policy.md` 与 `references/android-adb-policy.md`，检查关键条款 | 浏览器必须点名 `mcp__browser__`/`tabs_claim`/`user_open_tabs` 并显式禁止 Selenium/Playwright/Puppeteer、声明 DOM 优先、登录由用户完成、提交只点一次、截图落 `logs/screens`；手机必须写明 L0–L3 分级、`adb input text` 的 ASCII 限制、禁止 `adb tcpip`、要求 uiautomator 优先、标注当前为 `unverified` | PASS |
| T16 | 执行器配置与证据能否被误覆盖 | 读 `settings.json` 校验 `executor_policy`；`git check-ignore` 验证截图目录；备份后跑 `doctor --write` 比对证据 | `runtime=workbuddy_builtin`、登录不由 Agent 完成、单岗位提交上限 1、禁止依赖清单齐全；手机端 `send_like_policy=confirm_each`、`allow_bulk_send=false`、每岗位发送上限 1、间隔 ≥2 秒；`logs/screens/` 被忽略；`doctor --write` 后已登记证据与 `executor_policy` 均未被冲掉 | PASS |
| T17 | 邮件能不能直接发出去、会不会发错 | 读 `references/email-policy.md` 检查关键约束 | 必须指定 `qq-mail`、明确不用 `agent-mail` 代发、未连接时提示用户打开、要求展示全文与一次明确确认、禁批量、同岗位跟进仅一次、禁止把密码写入对话、收费类招聘不发 | PASS |
| T18 | 简历是不是在流程最前面生成 | 读 `resume-policy.md` 与 `SKILL.md` | 主流程声明为**九步**且「建立基础简历 → 导入岗位」顺序正确；有「步骤 0：建立基础简历」章节；禁止用占位符堆出空简历；前置条件不足输出缺口清单；定制版必须从基础简历派生；步骤 5 引用 `email-policy.md` 衔接邮件通道 | PASS |
| T19 | 搜索画像与通道约束是否真的写死 | 读 `config/search.json`、`job-search-policy.md`、`browser-policy.md` | 平台必填字段齐全、`search_url` 均为 https、`fetch_mode` 取值合法、宣称支持关键词就必须含 `{keyword}`、标为已核对就必须写 `verified_at`；排除词覆盖审计/销售/硬件；通道顺序固定 **C → B → A**；写明翻页上限、遇验证码立即停止、禁调非公开接口、禁能力不足时编造岗位；`browser-policy` 已补 C 路径且登录类操作编号为 X（禁止） | PASS |
| T20 | 搜索计划生成与排除词是否生效 | 跑 `search_urls.py --stdout` 与限定生成，再构造被排除的临时配置 | 计划含可点链接并声明不含采集结果；每条 URL 均 https、无空格、无未编码中文；城市过滤生效；排除词在**生成前**生效（整组命中排除词时以退出码 1 结束并列出原因） | PASS |
| T21 | 学历门槛会不会误判阻断 | 构造三份岗位：`本科及以上学历，博士优先`、`由博士团队领衔`、`硕士及以上`，跑标准化 + 评分 | 前两份**不得**被阻断（优先条件与团队描述都不是最低门槛），并说明「仅优先」；`硕士及以上` 对本科档案仍阻断且状态为不匹配 | PASS |
| T22 | 档案校验失败后主流程会不会继续 | 给只有 `schema_version` 的坏档案跑 `jobagent.py run` | 退出码 1、`ok=false`、`failed_at=validate_profile.py`；标准化与评分均为 `skipped`；保留真实失败退出码 | PASS |
| T23 | 混合单位薪资会不会被放大 | 构造 `8千-1.2万`、`150-200元/天`、`20-30万/年`、`15-25K` 四份岗位 | 分别解析为 8000–12000、按 21 天折算 3150–4200、年薪 200000–300000、15000–25000 | PASS |
| T24 | 投递状态与审计日志会不会不一致 | 正常登记一次；把日志目录指向普通文件再推进；手工插入只有 intent 的事件 | 正常路径 intent + committed 成对；日志不可写时改前中止、状态不变、错误信息说明未修改；悬空事件被检出并告警 | PASS |
| T25 | `doctor --write` 会不会把已验证能力打回 | 备份 `settings.json`，伪造 `browser_exec=verified` 后跑 `doctor --write`，再跑 `--reset-external` | 普通诊断保留 `verified` 与原始证据；只有显式 `--reset-external` 才重置为 `unverified`；结束后还原配置 | PASS |
| T26 | adb 操控链路是否真的能用 | 造一个假 adb（`.cmd`/`.sh` 包装 Python 桩），喂固定 UI XML，跑 status / dump / tap / text | 识别机型与分辨率；dump 出中文按钮；`tap --text` 命中元素中心 (890,2050)；中文输入被拒并给替代方案；无 adb 时退出码 2 | PASS |

## 说明与边界

1. **T07/T08 只验证规则与约束**：真实页面变化、验证码属于 P4 浏览器执行器阶段，需要 WorkBuddy/Playwright 侧用例，本地脚本不联网、不操作页面。
2. **T05 的“简历生成”由模型完成**：脚本层只能保证未确认事实被列出、不被当作已确认；材料侧约束见 `skills/job-agent/references/resume-policy.md`，模型生成材料后须按该文件的核对表自检。
3. **T02 的去重是启发式**：`dedupe_key = sha1(company|title|city)[:10]`，只识别“明显重复”；同公司多岗位、子公司、地点写法差异可能漏判，需人工复核 `duplicates[]`。
4. **T12 是静态检查**：脚本不引入网络库即可证明不会主动外发；用户环境中的 WorkBuddy 浏览器能力另需 P0 验证。
5. **T13 的边界**：doctor 能证明「脚本跑得动、文件读得动」，**不能**证明「浏览器可控」；后者只能由用户实测后确认，脚本刻意不给出 `verified`。
6. **T14 的边界**：根解析的兜底是「`scripts/` 的上级目录」，若同一台机器存在多份 JobAgent 副本，请用 `JOBAGENT_ROOT` 显式指定，避免歧义。
7. **T20 只验证链接生成，不验证平台可达**：脚本不联网，因此无法断言某个平台今天是否改版。平台参数失效时改 `config/search.json` 的 `search_url` 与 `verified_at`，不改脚本。
8. 回归测试是**发布门槛**的一部分：修改脚本、评分权重、状态机、搜索画像后必须重新运行并保持 26/26。
9. **T26 用假 adb，不是真机**：它只能证明「命令拼装、XML 解析、文本匹配、坐标换算、拒绝逻辑」正确，
   不能证明真机会按预期响应。`mobile_exec` 仍为 `unverified`，必须按 `android-adb-policy.md` 第 8 节走完
   读闭环 + 点闭环才能置 `verified`。
10. **T21–T25 对应 2026-10-29 代码审计发现的 5 个缺陷**，属于「回归守卫」：这些用例在旧实现上会失败。
