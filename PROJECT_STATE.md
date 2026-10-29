# PROJECT_STATE — JobAgent

- 项目：WorkBuddy 个人求职 Agent（依据《WorkBuddy 个人求职 Agent 开发方案 V1.0》）
- 当前版本：**0.5.0**（Skill 0.5.0 / 评分配置 1.0.0 / 数据 schema 1.0）
- 更新时间：2026-10-29 13:40 (+08:00)
- 运行模式：半自动（真实投递默认不执行）
- 状态：P0 能力盘点已脚本化、P1 数据层、P2 Skill v0.5、P3 回归测试已完成；搜索 L1 已落地、L2 部分可用（C 通道）；P4/P5 与邮件通道规范已定待实测；P6 未开始

## 1. 已完成与验证证据

| 交付项 | 文件 | 验证方式 | 结果 |
| --- | --- | --- | --- |
| 项目骨架与模板 | `config/`、`profile/`、`jobs/`、`applications/`、`resumes/`、`reports/`、`logs/` | 目录存在、JSON 可解析 | 通过 |
| 档案校验 | `scripts/validate_profile.py` | 对示例档案运行；对缺失字段/损坏 JSON 运行 | 退出码 0 / 1，缺项逐条列出 |
| 标准化 + 去重 | `scripts/normalize_jobs.py` | 6 条原始岗位 | 5 个唯一岗位 + 1 组疑似重复，原始文件未改动 |
| 规则评分 | `scripts/score_jobs.py` | 示例岗位 + 示例档案 | 87 优先投递 / 73、70 待评估 / 54 暂缓 / 43 不匹配（学历阻断） |
| 投递状态机 | `scripts/update_application.py` | 正常推进、无证据提交、重复提交、非法迁移 | 4 类异常均按预期拒绝（退出码 1） |
| Skill 文档 | `skills/job-agent/SKILL.md` + 9 份 references | 章节与关键词检查（T07/T08/T15/T19） | 10 个章节齐全，含装载与根解析、搜索策略、两套执行器规范 |
| 岗位搜索 L1 | `config/search.json` + `scripts/search_urls.py` | T19/T20：生成计划、限定过滤、排除词生效 | 17 关键词 × 3 城市 × 3 平台 = 153 条查询；URL 编码正确、无未编码中文；整组命中排除词时退出码 1 并列出原因 |
| 搜索通道 | `references/job-search-policy.md` + `browser-policy.md` 第 1.1 节 | T19 检查通道顺序与硬边界 | 顺序固定 C（`WebFetch`）→ B（公开页）→ A（已登录标签页）；翻页上限 3、间隔 ≥2 秒、遇验证码即停、禁调非公开接口 |
| 执行器规范 | `references/browser-policy.md`、`references/android-adb-policy.md`、`references/email-policy.md` | T15/T17 检查关键条款是否写死 | 浏览器点名 `mcp__browser__*`/`tabs_claim` 并禁 Selenium/Playwright/Puppeteer；手机禁发送类、标注 `input text` 中文限制；邮件固定 `qq-mail`、禁 `agent-mail` 代发、要求全文展示 |
| 简历前置 | `references/resume-policy.md` 第 0 节 + `SKILL.md` 步骤 0 | T18 校验流程顺序与缺口清单机制 | 主流程九步，基础简历在导入岗位之前；事实不足时只输出缺口清单，不硬凑空简历 |
| 执行器配置 | `config/settings.json:executor_policy` | T16 校验字段 + `doctor --write` 后证据不丢 | `runtime=workbuddy_builtin`、`login_by_agent=false`、单岗位提交上限 1、`email.forbidden_connector=agent-mail`、`logs/screens/` 已忽略 |
| 能力盘点 | `scripts/jobagent.py doctor` | `doctor` 实测文件读写/脚本执行/标准库 | 四项 `verified` 带 evidence；浏览器/移动恒为 `unverified`（T13） |
| 根解析适配 | `scripts/common.py:find_root()` | 从项目外目录调用（T14） | `--root` → `JOBAGENT_ROOT` → 向上查找 → 兜底，四种路径均命中 |
| 回归测试 | `tests/run_tests.py` | `python tests/run_tests.py` | **20 通过 / 0 失败** |
| 运行报告 | `reports/*.md` | 打开检查 | 校验/去重/评分/运行摘要四类报告均生成 |

## 2. 关键设计决策

1. **数据与代码同仓**：`JobAgent/` 既是 Skill 依赖的项目根，也是数据工作区；Skill 文档只引用项目根相对路径，便于整体复制到 `D:\WorkBuddy\JobAgent\`。
2. **脚本与模型分责**：脚本只做确定性处理（校验、标准化、去重、加权、状态机），理解/生成交给模型；脚本不联网、不操作浏览器。
3. **幂等与可恢复**：标准化/评分默认**整体重建**（原始岗位是唯一事实源）；`--merge` 仅用于合并历史结果。投递记录写前自动 `.bak` 并追加 JSONL 审计日志。
4. **去重键与 ID**：`dedupe_key = sha1(company|title|city)[:10]`；`job_id = job-{dedupe_key}-{sha1(source_url)[:4]}`。同一岗位不同链接 → 相同 `dedupe_key`、不同 `job_id`，因此能既保留来源又识别重复。
5. **评分口径**：六维权重 25/20/20/15/10/10，总分四舍五入为整数；硬性不满足 → `blocked=true` 且状态 `不匹配`；阈值 `priority=78`、`consider=60` 放在 `config/scoring.json`，改权重必须升 `version` 并追加 `changelog`。
6. **事实状态**：`confirmed/pending/expired` 三态；`pending` 只进待确认清单，`expired` 只警告；材料只允许 `confirmed`。
7. **唯一写入口**：`applications.json` 只能经 `update_application.py` 修改；`已提交` 必须带证据；同一岗位已有提交类状态时拒绝重复申请。

## 3. 待办（按优先级）

1. **P0 能力盘点**（已脚本化，待你在 WorkBuddy 侧跑一次确认）：`python scripts/jobagent.py doctor --write`
   会实测文件读写、脚本执行与标准库依赖，并把带证据的能力矩阵写回 `config/settings.json`；
   `browser_exec` / `mobile_exec` 需你在 P4/P5 实测后自行确认，脚本不会自证。
2. **换真实档案**：用 `profile/profile.template.json` 建立 `profile/profile.json`；先把学历、毕业时间、
   实习、证书四类关键事实确认，再跑 `validate_profile.py`。
3. **生成基础简历**（步骤 0）：档案 confirmed 事实够了之后跑一次，产出 `resumes/main-resume-v1.0.md`；
   当前档案是占位示例，此时生成的也是示例简历，换真档案后才有意义。
4. **搜索 L2 实测**（规范已就绪）：三家校招站中，实习僧与牛客走 C 通道（`WebFetch` 文本只读）可直接读到
   岗位列表，应届生求职网需 B 通道（浏览器 DOM 渲染）。按 `job-search-policy.md` 跑一次真实抓取、
   核对字段映射后再把结果写入 `jobs/raw/`；`browser_exec` 未 `verified` 时应届生站只能给链接。
5. ~~打开 QQ 邮箱连接器~~（**已完成**：2026-10-29T13:20 确认 `qq-mail` 已连接，`bound=true, enabled=true`）。
   剩余：实测发出一封邮件，成功后把 `email_exec` 置 `verified`。
6. **权重校准**：用 10–20 条真实岗位跑评分，按"哪些分高但不想投/分低但想投"反馈调整
   `config/scoring.json`（记录 changelog）。
7. **P4 浏览器辅助**（规范已就绪，待实测）：按 `references/browser-policy.md` 先完成「A 路径只读」——
   `user_open_tabs` → `tabs_claim` → `dom_cua_get_visible_dom` 成功取到目标页结构，把证据登记进
   `config/settings.json` 的 `browser_exec.evidence` 后才置 `verified`；之后才谈填表与提交确认。
   执行器固定用 WorkBuddy 内置浏览器控制，不引入 Selenium/Playwright。
8. **P5 手机接入**（规范已就绪，待设备）：本机当前**无 adb、无 scrcpy**，需先安装 platform-tools 并接入设备，
   按 `references/android-adb-policy.md` 第 8 节完成一次只读闭环（`dumpsys window` / `screencap` /
   `uiautomator dump` 三样均成功）才能置 `verified`。手机端上限为「只读 + 引导」，永不代点发送类按钮。
9. **状态机补全**：如需"已撤回"，同步修改 `update_application.py`、`references/application-workflow.md`、`tests/`。

## 4. 待你确认的事项

- ~~WorkBuddy 版本与自定义 Skill 的实际目录/加载方式~~（已确认：`~/.workbuddy/skills/<slug>/`，`find_root()` 已适配）。
- ~~是否具备浏览器控制能力~~（已确认：WorkBuddy 内置浏览器控制可用，规范定为唯一执行器；仍需一次 A 路径只读实测才能置 `verified`）。
- 是否安装 Android platform-tools（adb）并允许接入设备：决定 P5 是否启动。
- ~~目标招聘平台优先级~~（已确认：先做**校招垂直站**三家——实习僧、应届生求职网、牛客校招；综合招聘站与国央企聚合暂不纳入 `config/search.json`）。
- 评分权重与薪资底线是否符合你的真实偏好。

## 5. 已知限制

- 技能匹配按关键词命中比例，粒度较粗；中文分词未引入，短词可能误命中。
- 去重为启发式，可能漏判或误判，需人工复核 `duplicates[]`。
- 材料文本由模型生成，脚本不校验最终措辞，只提供事实状态与版本规范。
- 未纳入"已撤回"状态；未实现定时任务、服务器同步、移动端自动化。
- 时间固定 `+08:00`；跨时区使用需改 `scripts/common.py`。
- **P4/P5 执行器仅有规范，无实现代码**：`browser-policy.md` 与 `android-adb-policy.md` 规定的是「怎么用宿主能力」，
  本项目不含浏览器/手机驱动代码（这是刻意设计，避免第三方依赖）。两项能力当前均为 `unverified`。
- **本机无 adb**：2026-10-29 实测 PATH 与常见安装位置均无 `adb`，也无 `scrcpy`；`android-adb-policy.md` 中的命令
  除 `input text` 的中文限制（已知社区结论）外，其余尚未在设备上逐条实测。
- **浏览器坐标类操作未验证**：`cua_*` 工具的坐标漂移特性来自通用经验，本机尚未实测，规范里已写入「每次重新截图」的约束作为对冲。
- **搜索平台模板会失效**：三家站 2026 年均改过 URL 参数。模板存于 `config/search.json` 并带 `verified_at`，
  脚本不联网故无法自动发现失效；换平台或改版时只改配置，不改代码。
- **抓取能力因站而异**：实习僧/牛客为服务端渲染，C 通道（`WebFetch`）可读；应届生求职网为前端渲染，
  需 B 通道（浏览器 DOM），`browser_exec` 未 `verified` 前拿不到其列表。这不等于「搜索功能不可用」，
  而是「可用范围受平台渲染方式限制」。
- **搜索来源可信度低一档**：`campus_vertical_search` 刻意不在 `trusted_sources` 内，同岗位官网直招那条评分更高；
  去重时若两条都在，应选官网那条为主记录。
- **邮件通道已连通但未实测发信**：`qq-mail` 连接器 2026-10-29T13:20 确认已连接（`bound=true`），
  `email_exec` 仍为 `unverified`——还差「实际发出一封邮件并确认送达」这一步。在此之前仍只产出草稿供用户复制发送。
- **基础简历尚未生成**：`profile/profile.json` 仍是占位示例，尚未产出 `main-resume-v1.0.md`；真实简历需先换真实档案。

## 6. 变更记录

| 日期 | 版本 | 说明 |
| --- | --- | --- |
| 2026-10-29 | 0.5.0 | 岗位搜索三层落地：新增 `config/search.json`（3 城市 / 17 关键词 / 3 平台 / 16 排除词，含各平台实测状态与 `verified_at`）与 `scripts/search_urls.py`（L1 纯本地生成，不联网）；`jobagent.py` 增 `search` 子命令；新增 `references/job-search-policy.md`（L1→L2→L3、通道顺序 C→B→A、翻页上限 3、间隔 ≥2 秒、遇验证码即停、禁非公开接口、禁能力不足编造岗位）；`browser-policy.md` 补第 1.1 节 **C 路径（`WebFetch` 文本只读）**，原「C（禁止）」改编号为 X；`settings.json` 增 `executor_policy.search` 与 `trusted_sources_note`（`campus_vertical_search` 刻意不列入可信来源）；SKILL.md 步骤 1 拆为 1a 发现 / 1b 导入；新增 T19/T20，回归 20/20 |
| 2026-10-29 | 0.4.0 | 简历前置 + 邮件通道：主流程**八步改九步**，新增「步骤 0：建立基础简历」（前置条件不足只出缺口清单，禁止占位符堆空简历；定制版必须标明基准主简历版本并从其派生）；`resume-policy.md` 增第 0 节（结构模板/分节取舍/完成必答三问）；新增 `references/email-policy.md`（用户本人 QQ 邮箱 `qq-mail`，禁 `agent-mail` 代发，全文展示 + 一次明确确认，禁批量，同岗位跟进仅一次，收费类招聘不发）；`settings.json` 增 `email_exec` + `executor_policy.email`；`doctor` 的外部能力表纳入 `email_exec`；新增 T17/T18，回归 18/18 |
| 2026-10-29 | 0.3.0 | 执行器规范：新增 `references/browser-policy.md`（浏览器固定用 WorkBuddy 内置 `mcp__browser__*`，禁 Selenium/Playwright/Puppeteer，A 路径 `tabs_claim` 复用已登录标签，DOM 优先于坐标，提交单次上限，截图落 `logs/screens`）与 `references/android-adb-policy.md`（USB 单设备、uiautomator 优先、永不代点发送类、`input text` 中文限制、禁 `adb tcpip`）；`settings.json` 新增 `executor_policy`；`doctor --write` 改为保留已登记证据；SKILL.md 5.2/步骤7 增执行器分工；`.gitignore` 补 `logs/screens/`；新增 T15/T16，回归 16/16；仓库改名 Find-a-Job |
| 2026-10-29 | 0.2.0 | WorkBuddy 装载适配：`skill/` → `skills/job-agent/`（符合 Skill 目录规范）；`common.py` 新增 `find_root()` 支持 `JOBAGENT_ROOT` 与向上查找；新增统一入口 `scripts/jobagent.py`（doctor/run/status）；`settings.json` 能力开关改为带证据的三态矩阵；`SKILL.md` 增第 0 章「装载与路径解析」、description 补触发词；新增 T13/T14，回归 14/14；README 重写 |
| 2026-10-29 | 0.1.0 | 首版落地：数据层 + 4 个脚本 + Skill v0.1 + 12 项回归测试 |
| 2026-10-29 | 0.1.0 | 开源整理：`common.py` 新增 `rel_path()`，产物与报告改输出相对路径（避免泄露执行机器绝对路径）；补 `LICENSE` / `THIRD_PARTY_NOTICES.md` / `.gitignore` / `.gitattributes`；`docs/` 收入设计文档；`logs/` 补 README 说明 |
