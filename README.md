# Find a Job · 个人求职流程 Agent

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-18%2F18-brightgreen.svg)](tests/test_cases.md)

**一个把「求职」变成可复现流程的本地工具包。** 它不替你投简历，也不编造经历——它负责把你散落在各处的
经历整理成**可追溯的事实档案**，把岗位整理成**可解释的分数**，把每次投递整理成**有证据的记录**，
而所有对外动作（投递、发邮件、上传材料）都停在你的确认键前面。

> 配套设计文档：《WorkBuddy 个人求职 Agent 开发方案 V1.0》→ [`docs/`](docs/)
> 当前版本 **v0.2.0** ｜ 纯 Python 标准库，**零依赖**，clone 即跑

---

## 1. 它到底解决什么问题

| 求职中的真实痛点 | 本项目的做法 |
| --- | --- |
| 简历越改越像别人，面试时讲不出过程 | 每条事实带 `status`（`confirmed` / `pending` / `expired`），**只有 confirmed 能进材料**，pending 只能进待确认清单 |
| 岗位存了几十个，凭感觉投，投完就忘 | 六维加权评分 + **硬性门槛独立阻断**（学历/证书不满足时高分也不能翻盘），分数必须带分项理由 |
| 同一岗位在多个平台，重复投递很尴尬 | 去重键 `sha1(company\|title\|city)[:10]`，同岗位不同链接识别为「疑似重复 + 各自来源」 |
| 记不清「到底提交了没有」 | 状态机强制：只有拿到**可验证提交结果**（确认页/邮件/申请编号）才能标 `已提交`，且必须带 `--evidence` |
| 把简历、手机号、登录态交给了某个云端服务 | 数据全在本地目录，脚本**不联网**（回归测试静态检查），密钥/凭据不落任何文件 |

一句话：**AI 负责理解与判断，脚本负责确定性计算，你负责最终确认。**

---

## 2. 30 秒快速开始

需要 Python 3.10+，无第三方依赖，无需 `pip install`。

```bash
# 仓库名是 Find-a-Job；这里显式把本地目录定为 JobAgent，与后文和 JOBAGENT_ROOT 保持一致
git clone https://github.com/iCurrer/Find-a-Job.git JobAgent
cd JobAgent

python scripts/jobagent.py doctor   # ① 能力与路径自检：应输出 ok=true，能力项 verified
python scripts/jobagent.py search   # ② 生成搜索计划：关键词×城市×平台的链接，写 jobs/raw/search-plan-*.md
python scripts/jobagent.py run      # ③ 跑通示例：校验 → 标准化去重 → 评分
python tests/run_tests.py           # ④ 回归测试：应输出 20 通过 / 0 失败
```

跑完打开三个文件看结果：
- `reports/scored-report.md` — 每个岗位的分数、分项理由、风险与缺失信息
- `jobs/jobs.scored.json` — 同样内容的结构化版本
- `jobs/raw/search-plan-*.md` — 可点开的搜索清单，按关键词分组

想让每一步单独执行（例如只想重跑评分）：

```bash
python scripts/validate_profile.py --profile profile/profile.json --report reports/profile-report.md
python scripts/normalize_jobs.py   --input jobs/raw/raw_jobs.json --output jobs/jobs.normalized.json --report reports/dedupe-report.md
python scripts/score_jobs.py       --jobs jobs/jobs.normalized.json --profile profile/profile.json \
                                   --config config/scoring.json --output jobs/jobs.scored.json --report reports/scored-report.md
```

> ⚠️ **仓库里的 `profile/profile.json` 是虚构占位示例**（`示例同学` / `138-0000-0000`），用于跑通流程。
> 填真实信息请另存为 `profile/profile.local.json`（已在 `.gitignore` 中排除），再把
> `config/settings.json` 的 `paths.profile` 指过去。**一旦真实简历被提交过，改 `.gitignore` 是无效的**，
> 必须 `git rm --cached`，历史里的内容还得重写历史才能清除。

---

## 3. 装进 WorkBuddy 当 Skill 用

`skills/job-agent/` 是一个符合 WorkBuddy Skill 规范的可分发目录（`SKILL.md` + `references/`），
它只携带**流程与边界**，不携带数据；运行时指向你本机的 JobAgent 项目目录。

### 3.1 安装

```bash
# macOS / Linux
cp -r skills/job-agent ~/.workbuddy/skills/job-agent

# Windows PowerShell
Copy-Item -Recurse skills\job-agent "$env:USERPROFILE\.workbuddy\skills\job-agent"
```

> Skill 目录的准确位置以你当前的 WorkBuddy 版本为准；本仓库按用户级 `~/.workbuddy/skills/` 编写。

### 3.2 让它找得到项目根（**关键一步**）

Skill 装到别处后，工作目录通常不是 JobAgent 项目根，四条命令会因相对路径失败。
按下面任一方式解决（优先级由高到低）：

| 方式 | 做法 | 适用 |
| --- | --- | --- |
| 显式传根 | 对话里告诉 WorkBuddy「项目根是 `D:\WorkBuddy\JobAgent`」，它会用 `--root` 调用 | 临时、多副本 |
| 环境变量 | `setx JOBAGENT_ROOT "D:\WorkBuddy\JobAgent"`（Win）/ `export JOBAGENT_ROOT=~/JobAgent` | 长期单副本，推荐 |
| 向上查找 | 从当前目录逐级向上找同时含 `config/settings.json` 与 `scripts/` 的目录 | 在项目内工作 |
| 兜底 | `scripts/` 所在目录的上一级 | 随项目一起跑 |

### 3.3 装完先验收

```bash
python "$JOBAGENT_ROOT/scripts/jobagent.py" doctor
```

看到 `file_read` / `file_write` / `script_exec` 都是 `verified`、`missing_dirs` 为空，
就说明 Skill 已经能正确驱动项目。`browser_exec` / `mobile_exec` 会一直是 `unverified`——
这两项**脚本不能自证**，只有你完成 P4/P5 实测并确认后才可以改。

### 3.4 然后就可以这样说话

> 「用 job-agent 把 `jobs/raw/` 里新加的岗位跑一遍，给我优先投递的排序和理由」
> 「这个岗位（贴链接）值不值得投？帮我评分，并把需要确认的信息列出来」
> 「按 job-agent 的规则，给 XX 公司的数据分析岗定制一版简历草稿，只用我确认过的事实」

---

## 4. 工作流：九步，简历在最前，确认键在执行前面

```
profile/profile.json ──► resumes/main-resume-v1.0.md   ← 步骤 0：先有简历，再谈岗位
     │ validate + 只用 confirmed 事实
     ▼
config/search.json ──► jobs/raw/search-plan-{date}.md  ← 步骤 1a：搜索计划（纯本地拼链接，不联网）
     │ 只读抓取，通道顺序 C→B→A（references/job-search-policy.md）
     ▼
jobs/raw/*.json                     ← 步骤 1b：岗位原文（搜索所得或你手工录入，只增不改）
     │ normalize：字段标准化 + dedupe_key 去重
     ▼
jobs/jobs.normalized.json
     │ score：六维加权 + 硬性门槛独立阻断
     ▼
jobs/jobs.scored.json ──► reports/scored-report.md
     │
     │ 从基础简历派生定制版（重排 + 措辞，不新增事实）
     │ 岗位只留邮箱时，一并起草邮件（references/email-policy.md）
     ▼
resumes/{job_id}/                   ← 版本化材料，不覆盖主简历
     │
     ▼  【★ 你显式确认：公司 / 岗位 / 材料版本 / 将要执行的动作】
     │     发邮件时还要看全文 + 给一次明确许可
     │
人工执行 或 已验证的执行器（浏览器 / 手机 / 邮箱）
     │ update_application.py（唯一写入口，写前 .bak + JSONL 审计日志）
     ▼
applications/applications.json ──► logs/applications.jsonl
```

**为什么简历在最前？** 简历是资产，不是「投某个岗位时才做的东西」。先产出一份基准，之后每个岗位只做派生（重排顺序、按 JD 术语改写表达），不必从零起草。放在最后的话，每个岗位都要重复劳动，而且前后版本容易不一致。

### 三条硬规则（脚本已强制执行，不是靠自觉）

1. **事实状态**：`confirmed` 才能写进材料；`pending` 只进待确认清单；脚本不做任何「猜测补全」。
2. **硬性门槛独立阻断**：学历/证书/经验不满足 → `blocked=true`、状态直接 `不匹配`，高分不能掩盖；判不准就记 `missing_info`，不当成已满足。
3. **提交证据**：改 `已提交` 必须带 `--evidence`，否则退出码 1；同一岗位已有提交记录时再投会被拦截。

### 4.1 岗位搜索：三层，先本地后浏览器

搜岗位不是一步，是三段，每段的失败方式不同，所以拆开：

| 层 | 做什么 | 谁做 | 需要能力验证吗 |
| --- | --- | --- | --- |
| **L1 生成搜索计划** | 按 `config/search.json` 拼出各平台搜索链接 | `scripts/search_urls.py`（纯本地） | 不需要，随时可用 |
| **L2 只读抓取列表** | 打开搜索页，读岗位卡片，抽成字段 | Agent（三条通道见下） | 按通道区分 |
| **L3 详情导入** | 补全字段、落 `jobs/raw/`、走去重评分 | Agent + 既有脚本 | 不需要 |

L2 有三条通道，**顺序固定 C → B → A**，能用代价最低的就别打扰你：

| 通道 | 手段 | 前置条件 | 能拿到什么 |
| --- | --- | --- | --- |
| **C 文本只读** | `WebFetch` 抓页面文本 | **无**，不需要 `browser_exec` 验证 | 服务端渲染的列表（实习僧、牛客） |
| **B 公开页只读** | `tabs_new` + DOM 读取 | `browser_exec=verified` | JS 渲染的列表（应届生求职网） |
| **A 已登录标签页** | `tabs_claim` 接管你打开的标签 | 同上 + 你已登录 | 登录后才可见的内容 |

C 路径是加搜索时补的：它不经过浏览器控制，所以**不受 `browser_exec` 状态限制**。这是当前唯一能立刻跑通的抓取通道，也是为什么搜索功能不用等你做浏览器实测就能用上一部分。

**硬边界**（写在 `job-search-policy.md`，不是靠自觉）：单条查询最多 3 页、相邻抓取间隔 ≥2 秒、遇到验证码/登录墙/频率提示**立即停止而不换方案重试**、绝不调用平台非公开接口、搜索阶段不做任何写操作（不点「立即沟通」「投递」）。

**一个刻意的设计**：搜索来的岗位 `source` 填 `campus_vertical_search`，**故意不加入** `trusted_sources`。聚合平台存在转载、过期、信息不全，信息可信度维度就该比官网直招低一档。所以同一岗位如果官网也发了，**以官网那条为主记录**。

平台参数会变（今年几家都改过），所以模板放在 `config/search.json` 里并带 `verified_at` 字段，失效时改配置，不用动脚本。

### 4.2 执行器：浏览器用宿主内置，手机走 adb，邮件用你自己的邮箱

第八步「执行」是整个流程里唯一碰真实世界的地方，因此单独定规范。三套规则都已在仓库里：

| | 浏览器（P4） | 手机（P5） | 邮件 |
| --- | --- | --- | --- |
| 规范文件 | [`browser-policy.md`](skills/job-agent/references/browser-policy.md) | [`android-adb-policy.md`](skills/job-agent/references/android-adb-policy.md) | [`email-policy.md`](skills/job-agent/references/email-policy.md) |
| 运行时 | **WorkBuddy 内置浏览器控制**（`mcp__browser__*` + `workbuddy-browser-use`） | `adb`（USB 单设备） | **你自己的 QQ 邮箱**（连接器 `qq-mail`） |
| 明确禁止 | Selenium / Playwright / Puppeteer / Pyppeteer / undetected-chromedriver | `adb tcpip`（无线调试）、`adb root`、`pm clear`、`settings put` | 用 `agent-mail` 代发（那是智能体邮箱，HR 联系不到你）、群发、把密码贴进对话 |
| 定位策略 | DOM 优先于坐标（`dom_cua_*` 优于 `cua_*`） | `uiautomator dump` 优先于 `input tap` | 收件地址逐字符核对（`qq.com` / `qq.con`） |
| 登录 / 身份 | **由你在浏览器里自己登录**，Skill 只 `tabs_claim` 接管那个标签页，全程不接触账号密码 | 同左，且不代填密码/验证码 | 连接器托管授权，Skill 不接触密码与授权码 |
| 提交动作 | 填到按钮前停下；你单独授权后才点**一次** | **永不代点**「发送/投递/打招呼/确认」，有不可撤回风险 | 全文展示 + 一次明确许可后才发；同岗位跟进仅一次 |
| 落盘 | 截图只允许 `logs/screens/`（已被 `.gitignore` 排除） | 同上；设备端副本 `pull` 后立即删 | 草稿存 `resumes/{job_id}/email-*.md`，发送记录进 `applications.json` |

**为什么浏览器不自己造一套？** 一是会引入第三方依赖，破坏「clone 后无需 `pip install`」这个承诺；二是自己起浏览器就得自己处理登录，"凭据不经 Skill 之手"这条线立刻守不住。

**为什么手机端比浏览器端更保守？** 网页误点提交通常能撤回或修正，App 里给 HR 发出的消息不可撤回。所以手机端的上限是「只读 + 引导」，不是「辅助投递」。

**邮件为什么必须用你自己的邮箱？** 用 `agent-mail` 代发，HR 看到的发件人不是你的真实地址，回复也进不了你的邮箱，后续沟通直接断掉。所以邮件通道的第一步永远是「检查 QQ 邮箱连接器是否已连接」，没连接就提示你打开，而不是绕过去。

还有两个实操坑，已经写进规范：`adb shell input text` **不支持中文**（只能 ASCII），需要中文时默认把手机交还给你；Windows 下 `adb exec-out screencap -p > x.png` 在 PowerShell 里会把 PNG 写坏，必须用「设备端落盘 → `pull` → 删设备端文件」三步。

> 三项能力当前都是 `unverified`：本机没有 adb；浏览器尚未做过「A 路径只读」实测；QQ 邮箱连接器已连上，
> 但还没实际发出过一封邮件。规范先行，实测通过并登记证据后才置 `verified`。

---

## 5. 目录结构

```
JobAgent/
├── README.md                  # 本文件
├── PROJECT_STATE.md           # 进度、已验证证据、待办、已知限制
├── LICENSE                    # MIT
├── THIRD_PARTY_NOTICES.md     # 第三方组件、商标与免责声明
├── docs/                      # 设计文档（开发方案 V1.0）
├── skills/job-agent/          # ★ 可装进 WorkBuddy 的 Skill
│   ├── SKILL.md               #   装载与根解析、八步主流程、工具边界、错误处理
│   └── references/            #   档案/评分/简历/投递/安全/搜索/浏览器/adb/邮件 九份规则
├── config/
│   ├── settings.json          #   路径、运行模式、能力矩阵、执行器策略、来源白名单
│   ├── scoring.json           #   六维权重、阈值、版本与 changelog
│   └── search.json            #   搜索城市、关键词组、排除词、平台 URL 模板
├── profile/
│   ├── profile.template.json  #   空白模板
│   └── profile.json           #   示例档案（虚构占位，可替换）
├── jobs/
│   ├── raw/raw_jobs.json      #   原始岗位（只增不改）
│   ├── jobs.normalized.json   #   标准化 + 去重结果（脚本生成）
│   └── jobs.scored.json       #   评分结果（脚本生成）
├── applications/
│   ├── applications.json      #   投递记录（只经脚本修改）
│   └── evidence/              #   提交证据（截图、确认页）
├── resumes/                   # 简历与求职信版本（命名规范见目录内 README）
├── reports/                   # 校验 / 去重 / 评分 / 运行摘要
├── logs/                      # 审计日志（已被 .gitignore 排除）
├── scripts/
│   ├── jobagent.py            # ★ 统一入口：doctor / search / run / status
│   ├── common.py              #   公共工具（含项目根解析 find_root）
│   ├── validate_profile.py    #   档案校验
│   ├── search_urls.py         #   岗位搜索计划生成（L1，纯本地不联网）
│   ├── normalize_jobs.py      #   岗位标准化 + 去重
│   ├── score_jobs.py          #   六维规则评分 + 硬性阻断
│   └── update_application.py  #   投递状态机（唯一写入口）
└── tests/
    ├── run_tests.py           # T01–T20 回归测试
    ├── sample_profile.json    # 测试固定档案
    ├── sample_jobs.json       # 测试固定岗位
    └── test_cases.md          # 用例说明
```

---

## 6. 换成你自己的数据

1. **档案**：复制 `profile/profile.template.json` → `profile/profile.json`，逐项填写。
   每条事实标 `status`，并在 `facts_sources` 记来源与确认时间（被追问时这就是你的底稿）。
   > 真实信息请存 `profile.local.json`（已被 `.gitignore` 排除），别往受版本管理的 `profile.json` 里写。
2. **先出基础简历**（步骤 0）：档案校验通过后，让 WorkBuddy「按 skills/job-agent 的 resume-policy 生成基础简历」，
   产出 `resumes/main-resume-v1.0.md` + 版本说明。它会同时告诉你三个缺口和先补哪个收益最高。
   档案事实不足时**不会**硬凑一份空简历，只给你缺口清单。
3. **搜索条件**：改 `config/search.json` 的城市、关键词组、排除词。`cities` 按优先级排列，
   `exclude_keywords` 是硬性排除项（命中即剔除，脚本只做子串匹配，不做语义判断）。
   排除词写错会误伤——例如「销售」会连「销售财务」一起排除，发现漏掉就改列表，不要改脚本。
4. **岗位**：让 Skill 按步骤 1 搜索并导入，或按 `jobs/raw/raw_jobs.json` 的字段格式自行录入。
   字段允许缺失——脚本会写入 `missing_info`，不会替你猜。
5. **权重**：改 `config/scoring.json` 的六维权重（合计必须为 1.0），并追加 `version` 与 `changelog`。
6. 重跑 `python scripts/jobagent.py search` 与 `run`。
7. **要发邮件的话**：在对话输入框左下角的连接器菜单里确认 **QQ 邮箱**（`qq-mail`）已连接。
   连上后 Skill 才能用你自己的邮箱发信；没连上时它只给草稿，不会替你发，也不会改用智能体邮箱代发。

权重怎么调才有意义：先跑 10–20 条真实岗位，把「分高但不想投」和「分低但想投」的挑出来，
再回头动权重——否则调的是自己的手感，不是模型。

---

## 7. 常见问题

**Q：为什么不直接把简历也自动生成、自动投？**
A：自动投递的失败成本是「投错一家公司」，而招聘平台的条款通常禁止自动化提交。本项目把
「理解与生成」交给模型、「执行」留给你，P4/P5 阶段也只做到「辅助填表 + 提交前确认」（手机端连提交都不做）。

**Q：评分准吗？**
A：不准，而且本来就不该准。它是**规则启发式**：技能匹配按关键词命中比例算，权重与阈值需要你按真实
反馈校准。它的价值是「可解释、可复现、不吹牛」，不是「预测录取概率」。

**Q：能用在真的招聘网站上吗？**
A：分两层说。**生成搜索链接**完全不联网，纯本地拼 URL；**抓取岗位列表**由 Agent 只读完成，走 C→B→A 通道，只在列表页读，不点投递、不碰登录、遇验证码即停。脚本本身仍然一行网络代码都没有（T12 静态检查）。

**Q：能自动帮我搜岗位吗？**
A：能搜，但「搜到」不等于「投出去」。`jobagent.py search` 给你一份可点开的搜索清单（关键词 × 城市 × 平台）；
L2 才尝试自动读列表并抽字段——实习僧和牛客可以直接文本读取，应届生求职网需要浏览器 DOM 渲染。
筛选、判断、投递始终由你决定。

**Q：搜索会不会把「搜到很多」当成「匹配很多」？**
A：不会。搜索只负责把岗位**带进来**（写 `jobs/raw/`），判断好坏由步骤 4 的评分做，两件事分开。

**Q：数据会不会被上传？**
A：脚本没有任何网络库调用（`tests/run_tests.py` T12 静态检查这一点）；日志与 `.bak` 都在 `.gitignore` 里。
搜索时读取的是公开页面，不会把你的档案或投递记录发给任何平台。

**Q：能只跑其中一步吗？**
A：能，见第 2 节的四段命令；`jobagent.py run` 只是把它们串起来并汇总退出码。

---

## 8. 进度对照（方案第 8 章）

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| P0 环境盘点 | ✅ 已可自动化 | `jobagent.py doctor` 实测并写出能力矩阵（T13 覆盖） |
| P1 MVP 数据层 | ✅ 已完成 | 档案 / 岗位 / 投递模板 + `schema_version` + 校验脚本 |
| P2 Skill v0.5 | ✅ 已完成 | `SKILL.md` 十章 + 9 份 references，含装载与根解析、搜索策略、两套执行器规范 |
| P3 质量测试 | ✅ 已完成 | T01–T20，20/20 通过 |
| P4 浏览器辅助 | 📋 规范已定，待实测 | [`browser-policy.md`](skills/job-agent/references/browser-policy.md) 就绪；需先通过「A 路径只读」实测，再验证填表，最后才是提交前确认 |
| P5 手机接入 | 📋 规范已定，待设备 | [`android-adb-policy.md`](skills/job-agent/references/android-adb-policy.md) 就绪；本机尚无 adb，接入设备后先做只读闭环 |
| P6 常驻与扩展 | ⏳ 未开始 | 定时运行 / 服务器 / 仪表盘 |

## 9. 已知限制

- 评分是**规则启发式**，不是成功率；中文未分词，短词可能误命中。
- 去重只识别「公司+岗位+城市」相同的明显重复，同公司多岗位、地点写法差异可能漏判。
- `resumes/` 的材料由模型按 `references/resume-policy.md` 生成，脚本只保证数据与状态，不校验最终措辞。
- 「已撤回」状态未纳入状态机（MVP 范围外）。
- 时间固定 `+08:00`；跨时区需改 `scripts/common.py` 的 `CST`。
- 根解析的兜底是「`scripts/` 上级目录」，同机多份副本请用 `JOBAGENT_ROOT` 显式指定。
- **搜索平台参数会变**：三家校招站今年都改过 URL 格式。模板放在 `config/search.json` 并带 `verified_at`，
  失效时改配置不改脚本；脚本不联网，因此无法自动发现失效。
- **抓取能力取决于平台渲染方式**：服务端渲染的能直接读，纯前端渲染的需要浏览器 DOM。不是「有搜索功能就能搜所有平台」。
- **搜索来源的可信度天然低一档**：`campus_vertical_search` 刻意不在 `trusted_sources` 里，所以同一岗位
  官网直招那条的评分会更高。这不是 bug，是刻意让「官网可核实」比「聚合站转发」优先。

## 10. 安全边界

- 脚本**不联网**、不发邮件、不操作浏览器。
- 密码 / Cookie / 令牌不写入任何文件；示例数据全部是占位符。
- 遇到验证码、登录保护、页面结构变化：暂停，交给你处理，不尝试绕过。
- 真实投递前必须展示完整信息并得到显式确认；确认前不推进状态。

---

## 11. 仓库里有什么、没有什么

| 有 | 说明 |
| --- | --- |
| `scripts/` 六个脚本 + `tests/` 20 项回归 | 纯标准库，clone 后**无需安装依赖** |
| `skills/job-agent/` | 可直接复制进 WorkBuddy 的 Skill 目录 |
| `docs/` 设计文档 | 《开发方案 V1.0》，13 章设计与分阶段路线 |
| 示例数据与示例报告 | 全部虚构占位（`示例*` / `example-*` 域名），可安全浏览 |

| 没有 | 补齐方式 |
| --- | --- |
| 真实个人档案 | 按第 6 节自建（建议存 `profile.local.json`） |
| 真实岗位数据 | 按 `jobs/raw/raw_jobs.json` 字段自行录入 |
| 简历成品（PDF/DOCX） | 按 `references/resume-policy.md` 生成，不入库 |
| 审计日志 | 首次 `update_application.py` 运行时自动创建 |
| 浏览器 / 手机执行器 | P4/P5 工作，尚未实现 |

## 12. 许可证与归属

- 代码与文档采用 **MIT License**，全文见 [`LICENSE`](LICENSE)。
- 无第三方运行时依赖（仅 Python 标准库），许可结论见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
- **无背书关系**：「WorkBuddy」为描述性引用其运行环境，本项目为个人独立项目，与 WorkBuddy 官方及各招聘平台
  均无雇佣、合作、赞助或认证关系。
- 评分与材料草稿均为规则启发式的辅助建议，不构成职业建议或录用承诺；本项目不代投、不代发、不代提交。
