# PROJECT_STATE — JobAgent

- 项目：WorkBuddy 个人求职 Agent（依据《WorkBuddy 个人求职 Agent 开发方案 V1.0》）
- 当前版本：**0.2.0**（Skill 0.2.0 / 评分配置 1.0.0 / 数据 schema 1.0）
- 更新时间：2026-10-29 13:00 (+08:00)
- 运行模式：半自动（真实投递默认不执行）
- 状态：P0 能力盘点已脚本化、P1 数据层、P2 Skill v0.2、P3 回归测试已完成；P4/P5/P6 未开始

## 1. 已完成与验证证据

| 交付项 | 文件 | 验证方式 | 结果 |
| --- | --- | --- | --- |
| 项目骨架与模板 | `config/`、`profile/`、`jobs/`、`applications/`、`resumes/`、`reports/`、`logs/` | 目录存在、JSON 可解析 | 通过 |
| 档案校验 | `scripts/validate_profile.py` | 对示例档案运行；对缺失字段/损坏 JSON 运行 | 退出码 0 / 1，缺项逐条列出 |
| 标准化 + 去重 | `scripts/normalize_jobs.py` | 6 条原始岗位 | 5 个唯一岗位 + 1 组疑似重复，原始文件未改动 |
| 规则评分 | `scripts/score_jobs.py` | 示例岗位 + 示例档案 | 87 优先投递 / 73、70 待评估 / 54 暂缓 / 43 不匹配（学历阻断） |
| 投递状态机 | `scripts/update_application.py` | 正常推进、无证据提交、重复提交、非法迁移 | 4 类异常均按预期拒绝（退出码 1） |
| Skill 文档 | `skills/job-agent/SKILL.md` + 5 份 references | 章节与关键词检查（T07/T08） | 10 个章节齐全，含装载与根解析；命令与状态机对齐 |
| 能力盘点 | `scripts/jobagent.py doctor` | `doctor` 实测文件读写/脚本执行/标准库 | 四项 `verified` 带 evidence；浏览器/移动恒为 `unverified`（T13） |
| 根解析适配 | `scripts/common.py:find_root()` | 从项目外目录调用（T14） | `--root` → `JOBAGENT_ROOT` → 向上查找 → 兜底，四种路径均命中 |
| 回归测试 | `tests/run_tests.py` | `python tests/run_tests.py` | **14 通过 / 0 失败** |
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
3. **权重校准**：用 10–20 条真实岗位跑评分，按"哪些分高但不想投/分低但想投"反馈调整
   `config/scoring.json`（记录 changelog）。
4. **P4 浏览器辅助**：仅在 P0 证明浏览器可控后启动；先验证只读页面，再验证填写，最后才是"提交前确认"。
5. **状态机补全**：如需"已撤回"，同步修改 `update_application.py`、`references/application-workflow.md`、`tests/`。

## 4. 待你确认的事项

- WorkBuddy 版本与自定义 Skill 的实际目录/加载方式。
- 是否具备脚本执行与浏览器控制能力（决定 P4 路线）。
- 目标招聘平台优先级（先选 1 个官网/平台试点）。
- 评分权重与薪资底线是否符合你的真实偏好。

## 5. 已知限制

- 技能匹配按关键词命中比例，粒度较粗；中文分词未引入，短词可能误命中。
- 去重为启发式，可能漏判或误判，需人工复核 `duplicates[]`。
- 材料文本由模型生成，脚本不校验最终措辞，只提供事实状态与版本规范。
- 未纳入"已撤回"状态；未实现定时任务、服务器同步、移动端自动化。
- 时间固定 `+08:00`；跨时区使用需改 `scripts/common.py`。

## 6. 变更记录

| 日期 | 版本 | 说明 |
| --- | --- | --- |
| 2026-10-29 | 0.2.0 | WorkBuddy 装载适配：`skill/` → `skills/job-agent/`（符合 Skill 目录规范）；`common.py` 新增 `find_root()` 支持 `JOBAGENT_ROOT` 与向上查找；新增统一入口 `scripts/jobagent.py`（doctor/run/status）；`settings.json` 能力开关改为带证据的三态矩阵；`SKILL.md` 增第 0 章「装载与路径解析」、description 补触发词；新增 T13/T14，回归 14/14；README 重写 |
| 2026-10-29 | 0.1.0 | 首版落地：数据层 + 4 个脚本 + Skill v0.1 + 12 项回归测试 |
| 2026-10-29 | 0.1.0 | 开源整理：`common.py` 新增 `rel_path()`，产物与报告改输出相对路径（避免泄露执行机器绝对路径）；补 `LICENSE` / `THIRD_PARTY_NOTICES.md` / `.gitignore` / `.gitattributes`；`docs/` 收入设计文档；`logs/` 补 README 说明 |
