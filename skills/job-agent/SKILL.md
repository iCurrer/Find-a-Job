---
name: job-agent
description: 个人求职流程编排 Skill。以本地个人档案为唯一事实来源，完成岗位导入、标准化去重、可解释的六维评分、简历/求职信/网申答案草稿与投递状态记录；任何外部写入（投递、发邮件、上传资料）前必须由用户显式确认。当用户提到「求职、找工作、岗位、投递、岗位评估、岗位打分、优先级排序、简历定制、求职信、网申、面试跟进、求职日报、求职周报、Offer 比较」，或提供招聘链接/岗位截图/岗位 JSON 要求分析或导入，或要求查询、更新投递记录时使用。
version: 0.2.0
---

# job-agent（个人求职流程 Skill）

> **能力边界声明（每次运行先读）**
>
> 1. WorkBuddy 的**文件读取、脚本执行、浏览器控制、移动端自动化**能力，在 P0 环境盘点并取得可核验证据之前，一律视为**「未接入」**，不得假设可用。
> 2. 能力未接入时，本 Skill 只能输出评分报告、材料草稿和**可复制的人工操作清单**；不得声称已自动投递、已自动填表或已发送邮件。
> 3. **真实投递、发送邮件、上传个人资料、提交任何声明**都属于外部写入，每一项都必须有独立的**显式确认点**；用户确认前不得执行。
> 4. 本 Skill 不联网、不绕过验证码、不代替用户保管或填写登录凭据；脚本只做确定性计算，理解、判断与生成由模型完成。
> 5. 本文件及 `references/` 中的字段、命令、状态与权重，均以项目构建契约为准；发现方案原文与契约不一致时，**按契约执行**并在报告中列出差异。

## 0. 装载与路径解析（每次运行先做）

本 Skill 只规定**流程与边界**，不携带数据；脚本与数据在 JobAgent 项目目录里。因此第一步永远是**确认项目根**，
否则相对路径会被拼到错误位置，四条命令会整体失败。

### 0.1 三种部署形态

| 形态 | Skill 位置 | 项目根（脚本 + 数据） | 说明 |
| --- | --- | --- | --- |
| 项目内（开发） | `<root>/skills/job-agent/` | 同仓的 `<root>/` | cwd 通常就是项目根 |
| 装进 WorkBuddy | `~/.workbuddy/skills/job-agent/` | 另需指定 JobAgent 项目目录 | **cwd 不是项目根，必须解析根** |
| 便携 / 多份副本 | 任意 | 任意盘符 | 用 `JOBAGENT_ROOT` 显式指定，避免歧义 |

### 0.2 项目根解析优先级

1. 命令行 `--root PATH`（`scripts/jobagent.py` 支持）；
2. 环境变量 `JOBAGENT_ROOT`；
3. 从当前工作目录**向上逐级查找**同时含 `config/settings.json` 与 `scripts/` 的目录；
4. 兜底：`scripts/` 所在目录的上一级。

**执行约定：** 除 `jobagent.py` 外，四个业务脚本都按「项目根相对路径」解析参数。因此调用它们之前
**必须先 `cd` 到项目根**；若当前目录无法确定，先跑第 2.1 节的解析命令拿到绝对路径，再
`cd "$JOBAGENT_ROOT"` 后执行。不要把相对路径命令放在其他目录直接运行。

### 0.3 装载后的第一条命令（能力与路径自检）

```bash
python "$JOBAGENT_ROOT/scripts/jobagent.py" doctor
```

- 退出码 `0` 且 `file_read` / `file_write` / `script_exec` 均为 `verified` → 进入主流程；
- 任一项 `unavailable` 或 `missing_dirs` 非空 → 停止，按 2.3 降级为人工操作清单，并向用户报告缺失项。
- 用户确认能力真实可用后，可加 `--write` 把能力矩阵写回 `config/settings.json`。

## 1. 名称与触发条件

### 1.1 名称与版本

- 名称：`job-agent`（个人求职流程）
- 版本：`0.2.0`（与 `PROJECT_STATE.md`、报告头中的版本号保持一致）
- 定位：以 WorkBuddy 为决策中枢，以 Skill 编排流程，以**可验证的本地脚本**完成确定性处理；网页/手机操作在验证通过前保留为人工步骤。

### 1.2 用途

1. 把用户指定的个人资料整理为可追溯的 `profile/profile.json`，区分已确认事实、待确认信息与过期资料。
2. 导入、标准化、去重公开岗位，输出可解释的六维评分、风险与缺失信息。
3. 基于**已确认事实**为具体岗位生成简历草稿、求职信草稿与网申答案草稿。
4. 记录投递状态、材料版本、提交证据与跟进时间，避免重复申请。
5. 每次运行生成摘要报告：完成了什么、证据是什么、哪些事项待用户处理。

### 1.3 适用场景

- 用户提出岗位搜索、岗位导入、岗位评估/打分、优先级排序。
- 用户要求针对某个岗位定制简历、求职信或网申答案。
- 用户要求更新投递进度、登记提交结果、安排跟进。
- 用户要求生成本次求职日报/周报。
- 用户直接点名 `job-agent`，或引用 `JobAgent/` 项目内的流与文件。

### 1.4 触发条件

满足以下任一条件即触发：

- 用户明确提到「求职、找工作、岗位、投递、简历定制、求职信、面试、Offer、日报」等求职域任务；
- 用户提供招聘链接、岗位截图、岗位 JSON 或 `jobs/raw/` 下的新文件，要求分析或导入；
- 用户要求查询或更新 `applications/applications.json` 中的投递记录；
- 用户明确指示按本 Skill 执行（例如「用 job-agent 跑一遍今天的岗位」）。

### 1.5 不适用与拒绝场景

- 批量无人值守投递、绕过验证码/登录保护/反自动化、伪造经历或证书；
- 代替用户作出法律/合同承诺，或未经确认发送邮件；
- 在 P0 未验证浏览器/手机能力时承诺自动填表；
- 请求写入真实密码、Cookie、令牌、身份证号。

上述请求一律拒绝，并给出合规的替代方案（人工操作清单或仅做分析）。

## 2. 启动前检查

启动前检查只读，不修改任何业务数据。任一项不通过时，先向用户说明再决定是否继续。

### 2.1 工作区与项目根

按第 0.2 节的优先级解析项目根，命令一律使用**项目根相对路径**（如 `python scripts/validate_profile.py --profile profile/profile.json`）。

```bash
# 方式一：由入口脚本解析项目根（推荐，任意 cwd 都可用）
python "$JOBAGENT_ROOT/scripts/jobagent.py" doctor

# 方式二：显式指定根，适用于多份副本 / U 盘便携部署
export JOBAGENT_ROOT=/path/to/JobAgent
python "$JOBAGENT_ROOT/scripts/jobagent.py" doctor
```

- 必须存在的目录：`config/`、`profile/`、`jobs/raw/`、`applications/`、`resumes/`、`reports/`、`logs/`、`scripts/`、`tests/`、`skills/job-agent/references/`。
- `missing_dirs` 非空，或 `cd` 无法进入项目根：停止执行脚本，列出缺失项，请用户确认 `--root` 后再继续（不要把相对路径拼到错误位置）。

### 2.2 档案检查

```bash
python scripts/validate_profile.py --profile profile/profile.json --report reports/profile-report.md
```

- 输出契约：`{ok, errors[], warnings[], pending_facts[], missing_fields[]}`。
- 退出码 `0`：结构通过；继续，但 `warnings/pending_facts` 必须进入待确认清单。
- 退出码 `1`：档案存在字段缺失、待确认事实或过期资料；**不得自动补造**，先把缺失项列为问题，必要时只做只读分析。
- 退出码 `2`：参数错误或 `profile/profile.json` 不存在；提示用户先建立档案（可用 `profile/profile.template.json` 复制为 `profile/profile.json`），再决定是否继续。

### 2.3 运行时能力盘点（P0）——交给 doctor，不要凭感觉

```bash
python "$JOBAGENT_ROOT/scripts/jobagent.py" doctor          # 只探测，不写文件
python "$JOBAGENT_ROOT/scripts/jobagent.py" doctor --write  # 用户确认后写回 config/settings.json
```

`doctor` 实测文件读、文件写、脚本执行与标准库依赖，按 `state` 三态（`verified` / `unverified` / `unavailable`）输出，
每项带 `evidence` 与 `checked_at`，可直接作为 P0 的可复现证据写进报告。

| 能力 | doctor 判据 | 非 verified 时的降级 |
| --- | --- | --- |
| 文件读取 `file_read` | 能否读取 `config/settings.json` | 仅输出人工操作清单 |
| 文件写入 `file_write` | 能否在 `logs/` 写入并删除探针文件 | 只输出可复制命令，由用户在本机执行 |
| 脚本执行 `script_exec` | 入口脚本是否真的跑起来了 | 输出命令与预期退出码，用户回填结果 |
| 标准库自检 `stdlib_only` | `scripts/` 的导入是否全来自标准库 | 提示用户补依赖（本项目预期为空） |
| 浏览器控制 `browser_exec` | **不由 doctor 判定**，恒为 `unverified` | 不填表、不点提交，输出人工清单 |
| 移动端/App `mobile_exec` | **不由 doctor 判定**，恒为 `unverified` | 不接入，列入后续阶段 |

> 1. 「未接入」不是失败，而是当前运行模式的既定前提；报告中必须显式写明本次运行处于哪种模式，并引用 doctor 的 `checked_at`。
> 2. **禁止**自行把 `browser_exec` / `mobile_exec` 改成 `verified`——只有用户完成 P4/P5 实测并确认后才可以。
> 3. 能力矩阵的 `state` 是本次运行的事实，不得沿用上一次的 `verified` 结论，除非本次 doctor 仍然返回 `verified`。

### 2.4 按需加载的参考文件

`references/` 使用相对本 Skill 目录的路径引用，**只在对应步骤开始前加载**，避免无关内容干扰：

| 参考文件 | 何时加载 |
| --- | --- |
| `references/profile-schema.md` | 读取、校验、更新个人档案之前；需要解释事实状态时 |
| `references/job-scoring.md` | 岗位标准化/去重完成、准备评分或解释分数之前 |
| `references/resume-policy.md` | 生成、修改、导出一份对外的简历/求职信/网申答案之前 |
| `references/application-workflow.md` | 更新投递状态、登记提交证据、重试或判断重复申请之前 |
| `references/security-policy.md` | 任何涉及敏感信息、外部写入、日志与平台边界的操作之前 |

### 2.5 配置检查

- 读取 `config/settings.json`：确认路径、运行模式（半自动）、平台白名单；不在白名单内的平台只做分析，不做操作。
- 读取 `config/scoring.json`：确认六维权重、硬性门槛规则，并记录 `version` 与 `changelog`；权重不等于方案默认值时，在报告中注明版本差异。
- 配置缺失或损坏：停止评分步骤，报告缺失文件与退出码，不自行生成默认权重写入配置。

### 2.6 启动前检查清单

- [ ] 当前目录 = 项目根，目录结构完整
- [ ] `profile.json` 已校验，待确认事实已知
- [ ] 文件/脚本/浏览器/移动能力状态已判定并记录
- [ ] 本次任务的目标平台在白名单内
- [ ] `scoring.json` 的权重版本已记录
- [ ] 已确认本次运行是否需要外部写入（默认不需要）

## 3. 主流程

标准流程固定为八步：**导入岗位 → 标准化 → 去重 → 评分 → 材料生成 → 用户确认 → 执行 → 记录**。不得跳过「用户确认」直接执行，也不得在评分未完成时提前生成材料。

```
导入岗位 → 标准化 → 去重 → 评分 → 材料生成 → 用户确认 → 执行 → 记录
   ↓          ↓        ↓       ↓         ↓           ↓        ↓       ↓
 raw_jobs  normalized  dedupe  scored    reports/   explicit  executor record
   .json     .json     报告    .json     草稿       confirm   or manual  apps+logs
```

### 步骤 1：导入岗位

- 输入：用户提供的招聘链接/截图/文本，或 `jobs/raw/` 下用户手工整理的原始 JSON。
- 操作：将岗位原文、来源、采集时间写入 `jobs/raw/`（**只增不改**，一个来源一个文件或按采集批次命名，不改动已有文件）。
- 必须保留：`source`、`source_url`、`company`、`title`、`location`、`collected_at`、`raw_text`（或 `requirements`/`responsibilities`）。
- 无法验证的信息标记为未知（`missing_info`），不猜测补全。
- 岗位状态初始为 `待评估`。
- 若浏览器能力未接入：请用户粘贴岗位原文或提供链接由用户自行保存，本 Skill 不抓取。

### 步骤 2：标准化

```bash
python scripts/normalize_jobs.py --input jobs/raw/raw_jobs.json --output jobs/jobs.normalized.json
```

- 输出契约：`{ok, counts{input_jobs, added, updated, total, unique, duplicates, skipped}, duplicates[], skipped[], output, report}`；单个岗位的风险写在 `risk_flags` / `missing_info`。
- 脚本只读 `jobs/raw/`、只写新文件 `jobs/jobs.normalized.json`，不覆盖原始数据。
- 退出码 `0` 继续；`1` 表示有记录无法通过字段校验，逐条列出并请用户补充；`2` 表示输入文件缺失或参数错误，停止并要求确认路径。

### 步骤 3：去重

- 去重与标准化同一次脚本运行完成：`dedupe_key = sha1(归一化 company|title|city)[:10]`；`job_id = "job-" + dedupe_key + "-" + sha1(source_url)[:4]`。同一岗位不同来源链接因此得到不同 `job_id`、相同 `dedupe_key`，可被识别为疑似重复。
- 检查 `duplicates[]`：重复项不删除，保留来源并在报告中列出「疑似重复 + 各自来源链接」。
- 同一岗位不同来源链接视为疑似重复；必须由用户决定主记录。
- 岗位级风险（`risk_flags` / `missing_info`）与跳过的记录（`skipped[]`）进入报告，不静默丢弃。

### 步骤 4：评分

```bash
python scripts/score_jobs.py --jobs jobs/jobs.normalized.json --profile profile/profile.json \
  --config config/scoring.json --output jobs/jobs.scored.json --report reports/scored-report.md
```

- 输出契约：`{ok, count, ranking[{job_id, company, title, score, status, blocked, reasons[], risks[], missing_info[]}]}`。
- 六维权重：职责匹配 25%、硬性条件 20%、职业发展 20%、个人偏好 15%、薪资条件 10%、信息可信度 10%（详见 `references/job-scoring.md`）。
- **硬性门槛独立阻断**：硬性条件不满足时 `blocked=true`，状态直接判 `不匹配` 或 `暂缓`，不得被高软性分数掩盖。
- 未提供薪资、缺少来源链接、要求证书但档案未确认等，写入 `missing_info` / `risk_flags`，不得视为已满足。
- 分数不是成功率，不得表述为「录取概率」。
- 输出岗位状态仅限：`待评估|优先投递|暂缓|不匹配|已过期`。

### 步骤 5：材料生成

- 前置：评分完成且用户已选定岗位（默认取 `优先投递`，用户可指定其他）。
- 只使用档案中 `status=confirmed` 的事实；缺失的业绩数字、技能熟练度、证书、时间一律标注「待确认」，不自行补造（详见 `references/resume-policy.md`）。
- 按 `references/resume-policy.md` 的版本命名规范生成草稿到 `resumes/`，保留版本号、目标岗位、生成日期与变更摘要。
- 材料草稿必须与岗位对应：每个岗位一个独立版本，不覆盖主简历历史版本。
- 若档案存在 `pending` 事实：先在草稿中避开或以「待确认」占位，并在报告中列为待确认问题。

### 步骤 6：用户确认（强制门禁）

- 向用户展示**完整待提交信息**：公司、岗位、地点、材料版本、关键答案、将要执行的动作（填表/上传/提交/发邮件）。
- 明确告知三种可选结果：批准执行、修改后重提、取消。
- 在用户给出**显式确认**（明确的「确认提交/批准」表述）之前：
  - 禁止任何外部写入；
  - 禁止把状态推进到 `执行中` / `已提交`；
  - 能力未接入时，改为输出**可复制的人工操作清单**（见 6.3）。
- 确认记录写入申请记录 `notes` 并追加审计日志（不含敏感信息）。

### 步骤 7：执行

- 仅当同时满足：① 执行器能力已有 P0 证据；② 目标平台在白名单且规则允许；③ 用户已显式确认。
- 执行中只做用户已批准的动作；页面结构变化、出现验证码/登录保护、信息冲突时立即停止并转为 `需人工介入`。
- 只有拿到**可验证的提交结果**（平台确认页、确认邮件、申请编号等）才可标记 `已提交`；仅「已填写」「已点击提交」不算。
- 执行器未接入时，输出人工操作清单，由用户自行完成并在回执中登记结果；本 Skill 不代点提交。

### 步骤 8：记录

```bash
# 建立/更新到待准备
python scripts/update_application.py --job-id job-6d4169afd8-bb41 --status 待准备 --notes "用户已选定该岗位"

# 登记提交证据后才允许进入已提交
python scripts/update_application.py --job-id job-6d4169afd8-bb41 --status 已提交 \
  --evidence "示例平台确认页面，申请编号 APP-EXAMPLE-0001，见用户保存的截图"
```

- `update_application.py` 是**投递状态的唯一写入口**；写前自动生成 `applications.json.bak` 并追加 JSONL 审计日志。
- 状态迁移必须符合 `references/application-workflow.md` 中的完整迁移表；非法迁移退出码 `1`。
- `已提交` 必须有非空 `--evidence`，并由脚本自动写入 `submitted_at`。
- 同一 `job_id` 已存在 `已提交/笔试/面试/Offer` 记录时，再次提交被拒绝（退出码 `1`，重复申请风险）；不得绕过脚本手改 JSON。
- 每次运行结束生成报告到 `reports/`；`PROJECT_STATE.md` 由项目维护者更新，本 Skill 只在报告中建议需要登记的内容，不直接改写。

## 4. 输入输出契约

### 4.1 全局约定

- 所有脚本：纯 Python 3 标准库、UTF-8、`python scripts/<name>.py --help` 可查用法；**不联网、不发邮件、不调用浏览器**。
- 退出码：`0` 成功；`1` 数据校验/业务规则失败；`2` 参数或文件缺失。报告中必须写出退出码。
- 输出：JSON 到 stdout；可选 `--report PATH` 输出 Markdown 报告。
- 写入原则：脚本默认**只读输入、写新文件**；唯一例外是 `update_application.py`，写前生成 `.bak` 并追加审计日志。
- 时间统一 ISO 8601 带时区，例如 `2026-10-29T12:30:00+08:00`。
- 每个 JSON 顶层含 `schema_version`、`updated_at`。
- 相对路径以项目根 `JobAgent/` 为基准，不拼绝对路径。
- 项目根由 `scripts/common.py` 的 `find_root()` 解析：`--root` → 环境变量 `JOBAGENT_ROOT` → 从 cwd 向上查找 → 脚本上级目录。入口脚本 `jobagent.py` 从任意 cwd 都能工作；四个业务脚本仍建议先 `cd` 到项目根再执行。

### 4.2 命令契约（统一入口 + 四个业务脚本）

| 步骤 | 命令 | 成功输出（JSON 关键字段） |
| --- | --- | --- |
| 能力盘点 | `python scripts/jobagent.py doctor [--write]` | `{ok, root, missing_dirs[], capabilities{<name>:{state,evidence,checked_at}}}` |
| 全流程 | `python scripts/jobagent.py run [--profile P] [--raw R]` | `{ok, steps[{script,code,outputs}], next}` |
| 状态概览 | `python scripts/jobagent.py status` | `{applications_total, applications_by_status{}, follow_ups[], scored_by_status{}}` |
| 档案校验 | `python scripts/validate_profile.py --profile profile/profile.json --report reports/profile-report.md` | `{ok, errors[], warnings[], pending_facts[], missing_fields[]}` |
| 标准化+去重 | `python scripts/normalize_jobs.py --input jobs/raw/raw_jobs.json --output jobs/jobs.normalized.json` | `{ok, counts{...}, duplicates[], skipped[], output}` |
| 规则评分 | `python scripts/score_jobs.py --jobs jobs/jobs.normalized.json --profile profile/profile.json --config config/scoring.json --output jobs/jobs.scored.json --report reports/scored-report.md` | `{ok, count, ranking[{job_id, company, title, score, status, blocked, reasons[], risks[], missing_info[]}]}` |
| 状态更新 | `python scripts/update_application.py --job-id job-xxxxxxxxxx --status 待准备 [--notes "..."] [--evidence "..."] [--store applications/applications.json]` | `{ok, application_id, status, history_count, backup}` |

### 4.3 数据模型摘要

- `profile/profile.json`：`schema_version`、`profile_id`、`updated_at`、`basics`、`education[]`、`experience[]`、`skills[]`、`certifications[]`、`preferences`、`career_goals`、`constraints`、`facts_sources[]`、`open_questions[]`。字段与事实状态详见 `references/profile-schema.md`。
- `jobs/jobs.normalized.json`：`jobs[]`，元素含必需字段 `job_id`、`source`、`source_url`、`company`、`title`、`location`、`collected_at`、`dedupe_key`、`status`、`raw_text`（或 `requirements`/`responsibilities`），以及可选 `salary_*`、`degree`、`experience`、`language_requirements`、`posted_at`、`match_score`、`score_breakdown`、`risk_flags`、`missing_info`。
- `jobs/jobs.scored.json`：在归一化岗位基础上补充 `match_score`、`score_breakdown`、`risk_flags`、`missing_info`、`status`，不覆盖输入文件。
- `applications/applications.json`：`{schema_version, updated_at, applications[]}`，单条含 `application_id`、`job_id`、`company`、`title`、`status`、`resume_version`、`cover_letter_version`、`prepared_at`、`submitted_at`、`submission_evidence`、`next_action`、`follow_up_at`、`notes`、`outcome`、`history[]`。状态机与证据要求详见 `references/application-workflow.md`。

### 4.4 写入边界

| 允许写入 | 说明 |
| --- | --- |
| `jobs/raw/` | 仅新增原始岗位文件，不修改已有文件 |
| `jobs/jobs.normalized.json`、`jobs/jobs.scored.json`、`reports/*.md` | 脚本生成的新文件（可重复覆盖同名输出，但输入永不覆盖） |
| `resumes/` | 只新增版本化材料，不覆盖主简历历史版本 |
| `applications/applications.json` | 仅经 `update_application.py` 写入，且生成 `.bak` |
| `logs/` | 追加审计日志（JSONL，不含敏感信息） |

**禁止**：直接编辑 `applications.json`、覆盖 `jobs/raw/` 原始数据、把凭据写入任何文件、把个人资料上传到第三方。

## 5. 工具调用前置检查

### 5.1 脚本调用前

- [ ] 命令使用项目根相对路径，且当前目录正确。
- [ ] 目标脚本存在；首次使用先运行 `--help` 确认参数与契约一致。
- [ ] 输入文件存在；输出目录可写；不会覆盖原始数据。
- [ ] Python 解释器可用（`python --version` 有输出）；脚本仅依赖标准库。
- [ ] 预期退出码可解释：`0` 成功、`1` 校验/规则失败、`2` 参数或文件缺失。

任一项不满足：不执行脚本，输出缺失清单与可复制的修正命令。

### 5.2 浏览器/手机工具调用前

- [ ] P0 能力盘点中有该项的验证证据（读取页面能力优先验证）。
- [ ] 目标平台在 `config/settings.json` 白名单内，且平台规则允许相应操作。
- [ ] 操作是用户已确认的具体动作，而非「顺便多投几个」。
- [ ] 具备失败即停的机制：页面结构变化、验证码、登录失效时转为 `需人工介入`。

以上任一不满足 → 视为**未接入**，本次不调用。

### 5.3 未接入时的降级输出（人工操作清单）

当脚本或浏览器能力不可用时，输出可直接复制的人工操作清单，至少包含：

1. 岗位名称、公司、来源链接、`job_id`；
2. 需要用户手动执行的命令（含完整参数与预期退出码）；
3. 需要用户在平台页面填写/上传的字段与材料版本；
4. 提交后需要回填的证据（确认页链接、申请编号、截图文件名）；
5. 回填命令示例：`python scripts/update_application.py --job-id ... --status 已提交 --evidence "..."`。

### 5.4 每步执行前的通用检查

- 本步输入是否已由上一步产出并校验通过；
- 本步是否涉及外部写入（是 → 必须已有显式确认）；
- 本步输出写到哪里、是否可能覆盖已有数据；
- 失败时如何回退（`.bak`、原始数据只增、历史版本保留）。

## 6. 错误处理

### 6.1 退出码与总体策略

| 退出码 | 含义 | 处理 |
| --- | --- | --- |
| `0` | 成功 | 继续下一步；记录输出文件路径与摘要 |
| `1` | 数据校验/业务规则失败 | 停止当前步骤，逐条报告错误与缺失项，请用户补充；不得绕过规则 |
| `2` | 参数或文件缺失 | 停止，核对路径与参数，输出修正后的完整命令 |

原则：**失败即停、保留状态、不盲目重试**；重试前必须检查是否已产生外部副作用（尤其是否已提交）。

### 6.2 场景处理表

| 场景 | 处理 | 目标状态/输出 |
| --- | --- | --- |
| 页面结构变化/定位失败 | 立即停止自动操作，截图或记录页面状态，报告异常 | `需人工介入` |
| 出现验证码/登录保护/风控 | 不尝试绕过，暂停并交由用户处理 | `需人工介入` |
| 岗位字段缺失 | 标记 `missing_info`，不猜测补全；必要时请用户补充原文 | 岗位保持 `待评估` |
| 网络错误/来源不可访问 | 不重试抓取；保留来源链接并标注不可访问 | 报告中列为风险 |
| 重复申请风险 | 提交前检查同 `job_id` 是否已有 `已提交/笔试/面试/Offer`；有则拒绝（退出码 `1`） | 不重复提交 |
| 点击提交后无确认结果 | 不得标记 `已提交`；记录未验证并请用户核对 | `需人工介入` |
| 登录失效 | 停止操作，请用户重新登录后确认是否继续 | `需人工介入` |
| 档案字段缺失/过期 | 列出缺失项与过期事实，材料中不写未确认内容 | `待准备` 前先补档 |
| 脚本执行中断 | 保留输入输出与错误信息；检查 `.bak` 后安全恢复 | 按审计日志回退 |
| 状态迁移非法 | 拒绝写入（退出码 `1`），展示允许的下一步 | 状态不变 |
| 备份恢复需求 | 使用 `applications.json.bak` 恢复；恢复前先确认差异 | 记录恢复原因 |

### 6.3 需要人工介入的统一话术

输出：发生了什么 → 影响范围 → 建议用户的具体动作 → 用户完成后的回填命令。不得用「已处理」掩盖未验证的结果。

## 7. 安全规则

1. **本地优先**：档案、简历、申请记录默认留在用户可控的工作区，不上传第三方服务器。
2. **凭据隔离**：密码、Cookie、令牌、验证码不写入 Skill 文档、配置、日志或版本控制；示例数据一律使用占位符（如「示例同学」、`138****0000`、`example@example.com`）。
3. **最小权限**：执行器只获得当前任务所需权限，随时可停止；不申请「一次授权、长期自动执行」。
4. **明确授权**：搜索与分析可在只读范围内执行；真实投递、发送邮件、上传个人资料、提交声明必须逐项显式确认。
5. **平台规则**：使用平台允许的功能与访问方式；遇验证码、风控或禁止自动化条款立即停止。
6. **事实真实**：只有 `confirmed` 事实可写入对外材料；缺失数字标注「待确认」，禁止编造经历、证书、数字或技能。
7. **可审计**：记录时间、任务、目标岗位、执行步骤摘要、结果与错误；日志不含密码、Cookie、验证码或不必要的个人信息。
8. **备份恢复**：状态更新前自动 `.bak`；主简历与岗位定制版分开，避免误覆盖。

详细规则、日志字段白名单与事件处理见 `references/security-policy.md`。

## 8. 验收与报告格式

### 8.1 每次运行必须回答的三个问题

1. **完成了什么**：产出/更新的文件与记录，逐项列出路径与关键字段。
2. **证据是什么**：脚本退出码与输出摘要、校验报告、提交证据、用户确认记录。
3. **哪些事项待处理**：待确认事实、缺失信息、`需人工介入` 项、下一步动作与建议时间。

### 8.2 报告模板（写入 `reports/`）

```markdown
# job-agent 运行摘要 — 2026-10-29T12:30:00+08:00

- Skill 版本：0.1.0
- 运行模式：半自动 / 只读分析（写明能力未接入项）
- 触发指令：<用户原始诉求摘要>
- 输入文件：profile/profile.json、jobs/raw/raw_jobs.json
- 输出文件：jobs/jobs.normalized.json、jobs/jobs.scored.json、reports/scored-report.md

## 1. 完成事项
| 步骤 | 结果 | 退出码 | 输出 |
| --- | --- | --- | --- |
| 档案校验 | 通过/有警告 | 0 | reports/profile-report.md |
| 标准化+去重 | 新增 N 条，疑似重复 M 条 | 0 | jobs/jobs.normalized.json |
| 评分 | 优先投递 X 个，阻断 Y 个 | 0 | reports/scored-report.md |

## 2. 证据
- 命令与退出码：
- 关键数据引用（job_id、application_id、材料版本）：
- 用户确认记录（时间、确认内容）：

## 3. 待确认 / 待处理
- 待确认事实（来自 pending_facts）：
- 缺失信息（missing_info）：
- 需人工介入项：

## 4. 下一步
- 建议动作、负责人（用户/执行器）、建议时间（follow_up_at）
```

### 8.3 验收清单（与方案 9.2 对齐）

- [ ] 关键数据结构有 `schema_version` 与说明。
- [ ] 脚本可在样例数据上重复运行，且不静默覆盖原始数据。
- [ ] 评分结果可解释：分数、分项理由、硬性门槛与不确定性均有展示。
- [ ] 材料事实核验通过：未确认事实未被写成确定事实。
- [ ] 真实提交动作有显式确认点，且确认记录可追溯。
- [ ] 日志不含密码、Cookie、验证码或不必要的敏感个人信息。
- [ ] 出错时能暂停，不盲目重复提交。
- [ ] 报告三问（完成/证据/待处理）齐全，可直接作为用户验收依据。

### 8.4 报告与交付命名

- 运行摘要：`reports/YYYY-MM-DD-HHmm-job-agent.md`（同一分钟多次运行追加后缀 `-2`）。
- 评分报告：`reports/scored-report.md`（由脚本生成）。
- 档案校验报告：`reports/profile-report.md`（由脚本生成）。
- 材料版本与命名遵循 `references/resume-policy.md`；申请记录只经 `update_application.py` 更新。

## 版本与维护

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| 0.1.0 | 2026-10-29 | 首版：覆盖方案 4.2 的 8 个章节，对齐构建契约的字段、脚本与状态机 |
| 0.2.0 | 2026-10-29 | 适配 WorkBuddy 装载：新增第 0 章「装载与路径解析」（根解析优先级 + 部署形态）、2.3 改由 `jobagent.py doctor` 实测能力矩阵、4.2 增补统一入口三命令；`description` 补齐触发词以便自动命中 |

维护要求：Skill 版本、脚本命令、状态机、评分权重任一项变化时，同步更新本文件与对应 reference；评分权重变更还需在 `config/scoring.json` 中记录 `version` 与 `changelog`。
