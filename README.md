# WorkBuddy 个人求职 Agent（JobAgent）

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

**一句话：** 把「求职档案 → 岗位标准化去重 → 可解释的六维评分 → 材料草稿 → 投递状态机」做成一套
**本地可运行、不联网、只做确定性计算**的 Python 骨架，AI 只负责理解、判断与生成，脚本负责可复现的部分。

《WorkBuddy 个人求职 Agent 开发方案 V1.0》的**可运行落地版**：把方案第 4–9 章的 Skill 结构、数据模型、
评分规则、投递状态机与测试用例做成了本地可执行的项目，当前版本 **v0.1.0**。
设计文档见 [`docs/WorkBuddy_个人求职Agent_开发方案_v1.0.docx`](docs/)。

- 定位：WorkBuddy 做理解与决策，`skill/` 规定流程与边界，`scripts/` 做确定性计算，真实网页/手机操作在 P0 验证前**不自动执行**。
- 默认模式：**半自动**。搜索、分析、评分、材料草稿可自动完成；真实投递、发邮件、上传个人资料必须由你逐项确认。
- 数据全部在本地：档案、岗位、简历、投递记录都在本目录，不上传第三方。

## 1. 先跑通（约 2 分钟）

需要 Python 3.10+，只用标准库，无需安装依赖。在项目根目录执行：

```bash
# ① 校验示例档案：应输出 ok=true，并列出 2 条待确认事实
python scripts/validate_profile.py --profile profile/profile.json --report reports/profile-report.md

# ② 导入并标准化 6 条示例岗位：应得到 5 个唯一岗位 + 1 组疑似重复
python scripts/normalize_jobs.py --input jobs/raw/raw_jobs.json --output jobs/jobs.normalized.json --report reports/dedupe-report.md

# ③ 规则评分：应得到 1 个"优先投递"、2 个"待评估"、1 个"暂缓"、1 个"不匹配（学历阻断）"
python scripts/score_jobs.py --jobs jobs/jobs.normalized.json --profile profile/profile.json \
  --config config/scoring.json --output jobs/jobs.scored.json --report reports/scored-report.md

# ④ 回归测试：应输出 12 通过 / 0 失败
python tests/run_tests.py
```

跑完后打开 `reports/scored-report.md` 看评分明细，`jobs/jobs.scored.json` 是结构化结果。

## 2. 换成你自己的数据

> ⚠️ **仓库内的 `profile/profile.json` 是虚构占位示例，用于跑通流程不要直接改成真实信息提交。**
> 填真实档案请另存为 `profile/profile.local.json`（已在 `.gitignore` 中排除），并把
> `config/settings.json` 的 `paths.profile` 指向它。一旦把真实简历、手机号、身份证号写进
> 已被跟踪的文件，光改 `.gitignore` 是无效的，必须 `git rm --cached` 才能从后续提交中移除，
> 历史里的内容仍需重写历史才能清除。

1. **档案**：复制 `profile/profile.template.json` 为 `profile/profile.json`，逐项填写。每条事实标 `status`：
   - `confirmed`：你确认过的（才能写进简历）；
   - `pending`：待确认（只会出现在"待确认清单"，不会写进材料）；
   - `expired`：过期资料（需重新确认）。
   `facts_sources` 记录每条关键事实的来源与确认时间，用于追溯。
2. **岗位**：把招聘信息按 `jobs/raw/raw_jobs.json` 的字段格式追加到 `jobs/raw/`（建议一个来源一个文件），
   或直接手工录入。字段允许缺失，脚本会写入 `missing_info` 而不会猜测补全。
3. **评分权重**：在 `config/scoring.json` 调整六维权重（合计必须为 1.0），改完追加 `version` 与 `changelog`。
4. 重新跑第 1 节的 ②③ 即可。

## 3. 在 WorkBuddy 里怎么用

方案要求"先盘点、后创建"，所以按下面顺序：

1. **P0 环境盘点（只读）**：确认当前 WorkBuddy 版本能否读本地文件、执行 Shell/Python、控制浏览器、安装自定义 Skill。
   任一项没有可复现证据，就在 `config/settings.json` 的 `verified_capabilities` 里保持 `false`
   （默认全是 `false`，即"未接入"）。把证据（命令输出、截图路径）登记到 `logs/`。
2. **装入 Skill**：把 `skill/` 目录放到 WorkBuddy 的自定义 Skill 目录（具体路径以你当前版本为准），
   或在对话里让它读取 `skill/SKILL.md` 并"按此 Skill 执行"。`SKILL.md` 里已写明触发条件、八步主流程、
   四个脚本命令、退出码、错误处理与确认点。
3. **按流程使用**：岗位导入 → 标准化 → 去重 → 评分 → 材料草稿 → **你确认** → 执行（未接入则给人工操作清单）→ 记录。
   每次运行让它输出 `reports/` 下的运行摘要（模板见 `SKILL.md` 第 8 节）。

> 项目路径建议：复制到 `D:\WorkBuddy\JobAgent\`（方案 5.1 的建议位置）。当前目录是 `JobAgent/`，可直接整体复制。

## 4. 目录结构

```
JobAgent/
├── README.md                  # 本文件
├── PROJECT_STATE.md           # 当前进度、已验证证据、待办与已知限制
├── LICENSE                    # MIT
├── THIRD_PARTY_NOTICES.md     # 第三方组件与许可、商标与免责声明
├── docs/                      # 设计文档（开发方案 V1.0）
├── config/
│   ├── settings.json          # 路径、运行模式、能力开关、可信来源白名单
│   └── scoring.json           # 六维权重、阈值、版本与 changelog
├── profile/
│   ├── profile.template.json  # 空白模板
│   └── profile.json           # 当前档案（默认是示例数据，需替换）
├── jobs/
│   ├── raw/raw_jobs.json      # 原始岗位（只增不改）
│   ├── jobs.normalized.json   # 标准化 + 去重结果（脚本生成）
│   └── jobs.scored.json       # 评分结果（脚本生成）
├── applications/
│   ├── applications.json      # 投递记录（只经脚本修改）
│   └── evidence/              # 提交证据（截图/确认页）
├── resumes/                   # 简历与求职信版本（命名规范见目录内 README）
├── reports/                   # 校验报告、去重报告、评分报告、运行摘要
├── logs/                      # 审计日志（JSONL，不含敏感信息；日志文件已被 .gitignore 排除）
├── scripts/
│   ├── common.py              # 公共工具（不直接运行）
│   ├── validate_profile.py    # 档案校验
│   ├── normalize_jobs.py      # 岗位标准化 + 去重
│   ├── score_jobs.py          # 六维规则评分 + 硬性阻断
│   └── update_application.py  # 投递状态机（唯一写入口）
├── tests/
│   ├── sample_profile.json    # 测试固定档案
│   ├── sample_jobs.json       # 测试固定岗位
│   ├── test_cases.md          # T01–T12 用例说明
│   └── run_tests.py           # 回归测试
└── skill/
    ├── SKILL.md               # Skill 主文件（8 个章节）
    └── references/            # 档案/评分/简历/投递/安全五份规则
```

## 5. 三条硬规则（脚本已经强制执行）

1. **事实状态**：只有 `confirmed` 事实能写进材料；`pending` 只能进待确认清单。脚本不做任何"猜测补全"。
2. **硬性门槛独立阻断**：学历/证书/经验等不满足时，`blocked=true`、状态直接 `不匹配`，高分不能掩盖；
   无法判断时记 `missing_info`，不会当成已满足。
3. **提交证据**：状态改为 `已提交` 必须提供 `--evidence`，否则脚本拒绝（退出码 1）；同一岗位已有提交记录时
   再投会被拦截；每次写入前生成 `applications.json.bak` 并追加审计日志。

## 6. 进度对照（方案第 8 章）

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| P0 环境盘点 | ⏳ 待你在 WorkBuddy 侧执行 | `config/settings.json` 默认把能力标为未接入；需实测并登记证据 |
| P1 MVP 数据层 | ✅ 已完成 | 档案/岗位/投递模板 + schema_version + 校验脚本 |
| P2 Skill v0.1 | ✅ 已完成 | `skill/SKILL.md` + 5 份 references，覆盖方案 4.2 八个章节 |
| P3 质量测试 | ✅ 已完成 | T01–T12，12/12 通过；见 `tests/test_cases.md` |
| P4 浏览器辅助 | ⏳ 未开始 | 需 P0 证明浏览器可控后，先做"只读页面"验证，再测填表 |
| P5 手机接入 | ⏳ 未开始 | 方案明确为后续阶段 |
| P6 常驻与扩展 | ⏳ 未开始 | 定时运行/服务器/仪表盘 |

## 7. 已知限制

- 评分是**规则启发式**，不是成功率：技能匹配按关键词命中比例计算，权重与阈值需要你按真实反馈调整。
- 去重只识别"公司+岗位+城市"相同的明显重复，同一公司多岗位、地点写法差异可能漏判，需人工复核 `duplicates[]`。
- `resumes/` 的材料由模型按 `skill/references/resume-policy.md` 生成，脚本只保证数据与状态，不生成文本。
- "已撤回"状态暂未纳入状态机（MVP 范围外），如需支持要同步改 `update_application.py` 与状态机文档。
- 时间统一按 `+08:00` 写入；跨时区使用需调整 `scripts/common.py` 中的 `CST`。

## 8. 安全边界

- 脚本**不联网**、不发邮件、不操作浏览器（`tests/run_tests.py` T12 会静态检查）。
- 密码/Cookie/令牌不写入任何文件；示例数据全部是占位符。
- 遇到验证码、登录保护、页面结构变化：暂停，交给你处理，不尝试绕过。
- 真实投递前必须展示完整信息并得到你的显式确认；确认前不推进状态。

## 9. 仓库里有什么、没有什么

| 有 | 说明 |
| --- | --- |
| `scripts/` 四个脚本 + `tests/` 回归测试 | 纯标准库，clone 后**无需安装依赖**即可运行 |
| `skill/` Skill 主文件与 5 份规则 | 可直接复制到 WorkBuddy 自定义 Skill 目录 |
| `docs/` 设计文档 | 《开发方案 V1.0》，说明 13 章设计与分阶段路线 |
| 示例数据与示例报告 | 全部为虚构占位（`示例*` / `example-*` 域名），可安全浏览 |

| 没有 | 补齐方式 |
| --- | --- |
| 真实个人档案 | 按第 2 节用 `profile.template.json` 自建（建议存为 `profile.local.json`） |
| 真实岗位数据 | 按 `jobs/raw/raw_jobs.json` 的字段格式自行录入 |
| 简历成品（PDF/DOCX） | 由 `skill/references/resume-policy.md` 规则生成，不入库 |
| 审计日志 | 首次运行 `update_application.py` 时自动创建 `logs/applications.jsonl` |
| 浏览器/手机执行器 | P4/P5 阶段工作，尚未实现，`config/settings.json` 中能力默认全为 `false` |

## 10. 许可证与归属

- 本项目代码与文档采用 **MIT License**，全文见 [`LICENSE`](LICENSE)。
- 无第三方运行时依赖（仅 Python 标准库），第三方组件许可与结论见 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
- **无背书关系**：「WorkBuddy」为描述性引用其运行环境，本项目为个人独立项目，与 WorkBuddy 官方及各招聘平台
  均无雇佣、合作、赞助或认证关系。
- 评分与材料草稿均为规则启发式的辅助建议，不构成职业建议或录用承诺；本项目不代投、不代发、不代提交。

