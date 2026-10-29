# 个人档案字段与事实状态规范（profile-schema）

## 适用范围

- 本文件是 `profile/profile.json` 的字段定义与事实状态规则说明。
- 在以下时机加载：读取或校验个人档案之前；判断某条信息能否写入对外材料之前；更新档案或登记事实来源之前。
- 字段、枚举与状态以项目构建契约为准；`profile/profile.template.json` 是空白模板，`profile/sources.md` 记录事实来源的登记方式。本文件不定义脚本以外的数据处理能力。

## 1. 文件位置与顶层结构

- 档案位置：`profile/profile.json`（只读分析阶段不修改；修改档案必须先征得用户同意）。
- 编码：UTF-8；时间：ISO 8601 带时区，例如 `2026-10-29T12:30:00+08:00`。
- 顶层必须包含 `schema_version`、`profile_id`、`updated_at`；`profile_id` 为本地标识，**不得包含身份证号等敏感标识**。

```json
{
  "schema_version": "1.0",
  "profile_id": "local-001",
  "updated_at": "2026-10-29T12:30:00+08:00",
  "basics": {...},
  "education": [...],
  "experience": [...],
  "skills": [...],
  "certifications": [...],
  "preferences": {...},
  "career_goals": {...},
  "constraints": {...},
  "facts_sources": [...],
  "open_questions": [...]
}
```

## 2. 字段定义

### 2.1 basics（基本信息）

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| `name` | string | 对外展示用姓名；未确认时可留空，不得使用他人信息 |
| `phone` | string | 只存用户本人确认的号码；示例/文档中一律用 `138****0000` 占位 |
| `email` | string | 用户确认的邮箱；示例用 `example@example.com` |
| `city` | string | 当前所在城市，用于通勤与地点匹配 |

### 2.2 education（教育经历，数组）

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| `id` | string | 形如 `edu-001`，档案内唯一 |
| `school` | string | 学校全称，以确认资料为准 |
| `major` | string | 专业 |
| `degree` | string | 学历层次，如 `本科`、`硕士` |
| `start` / `end` | string | `YYYY-MM`；毕业时间不确定时留空并写入 `open_questions` |
| `status` | enum | `confirmed` / `pending` / `expired` |

### 2.3 experience（经历，数组）

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| `id` | string | 形如 `exp-001`，档案内唯一 |
| `kind` | enum | `internship` / `project` / `parttime` / `fulltime` |
| `org` | string | 组织或项目名称 |
| `role` | string | 角色/职责名称 |
| `start` / `end` | string | `YYYY-MM`；未知则留空并列入 `open_questions` |
| `highlights` | string[] | 一次一条，**只写已确认事实**；数字缺失时标注「待确认」 |
| `status` | enum | `confirmed` / `pending` / `expired` |

规则：`highlights` 中不得出现无法追溯的业绩数字、排名、用户量、增长率；需要数字而档案未提供时，写「〔数字待确认〕」而不是估算。

### 2.4 skills（技能，数组）

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| `name` | string | 技能/工具/语言名称 |
| `level` | enum | `了解` / `使用过` / `熟练`，不得越级描述 |
| `evidence` | string | 证据来源，如「课程项目」「实习中使用」；无证据时标 `pending` |
| `status` | enum | `confirmed` / `pending` / `expired` |

### 2.5 certifications（证书与考试，数组）

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| `name` | string | 证书/考试名称 |
| `state` | enum | `已取得` / `备考中` / `未通过` / `计划中` |
| `date` | string | 取得或考试日期；未知留空 |
| `status` | enum | `confirmed` / `pending` / `expired` |

规则：`备考中`、`未通过`、`计划中` 一律不得写成「已取得」或「持有」；岗位要求该证书但档案未确认时，只能标记为风险/待确认。

### 2.6 preferences（求职偏好，对象）

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| `cities` | string[] | 可接受城市，按优先级排序 |
| `salary_min` | number | 期望最低薪资（数值），未知留空 |
| `salary_period` | enum | `month` / `year`，与 `salary_min` 口径一致 |
| `job_types` | string[] | 如 `实习`、`全职`、`兼职` |
| `industries` | string[] | 目标行业 |
| `work_modes` | string[] | 如 `onsite`、`remote`、`hybrid` |

规则：偏好用于评分与排序，不得据此推断用户已接受某条件；薪资未填写时评分中标记 `missing_info`。

### 2.7 career_goals（职业目标）

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| `short_term` | string | 短期就业目标（1–2 年） |
| `long_term` | string | 长期发展方向 |

允许随时间更新；更新后 `updated_at` 必须同步变化。

### 2.8 constraints（约束条件）

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| `max_commute_minutes` | number | 单程最大通勤分钟数 |
| `unacceptable` | string[] | 不可接受条件（如特定加班强度、岗位类型） |

规则：`unacceptable` 命中岗位硬性条件时，按「硬性门槛不满足」处理（阻断），不得用高软性分数掩盖。

### 2.9 facts_sources（事实来源登记，数组）

| 字段 | 类型 | 要求 |
| --- | --- | --- |
| `fact_id` | string | 形如 `fact-001`，与档案条目可对应 |
| `fact` | string | 事实内容摘要 |
| `source` | string | 用户口述、原始简历文件、证书文件等 |
| `confirmed_by` | string | 确认人（示例：`user`） |
| `confirmed_at` | string | 确认时间，ISO 8601 |

规则：关键事实（学历、毕业时间、证书、实习经历）必须有来源或明确标记 `pending`；来源登记说明见 `profile/sources.md`。

### 2.10 open_questions（待确认问题，数组）

字符串数组，每条是一个**可回答的问题**，例如「毕业时间是否为 2027-06？」。
`pending` / `expired` 事实必须同时出现在 `facts_sources` 或 `open_questions` 中，便于逐条追踪。

## 3. 事实状态与使用规则

| 状态 | 含义 | 能否写入对外材料 | 处理方式 |
| --- | --- | --- | --- |
| `confirmed` | 用户已确认 | 可以 | 正常使用，保留来源 |
| `pending` | 待用户确认 | **不可以** | 列为待确认问题，材料中用占位或避开 |
| `expired` | 已过期（如旧证书、旧实习状态） | **不可以** | 先核实更新，未更新前不写入 |

三条硬规则：

1. **只有 `confirmed` 事实可以写入对外材料**（简历、求职信、网申答案、邮件正文）。
2. `pending` 事实必须列为待确认问题；不得因岗位要求而将其写成确定事实。
3. `expired` 事实不得直接使用；先请用户确认最新状态并更新档案。

## 4. 校验命令与输出

```bash
python scripts/validate_profile.py --profile profile/profile.json --report reports/profile-report.md
```

输出契约：`{ok, errors[], warnings[], pending_facts[], missing_fields[]}`。

| 退出码 | 含义 | 处理 |
| --- | --- | --- |
| `0` | 结构校验通过 | 继续；`warnings`、`pending_facts` 进入待确认清单 |
| `1` | 字段缺失/待确认/过期资料 | 逐条报告，请用户补充或确认；不自动补造 |
| `2` | 参数错误或档案文件缺失 | 核对路径；提示从 `profile/profile.template.json` 复制，不自行创建假数据 |

## 5. 示例（占位数据）

```json
{
  "schema_version": "1.0",
  "profile_id": "local-001",
  "updated_at": "2026-10-29T12:30:00+08:00",
  "basics": {
    "name": "示例同学",
    "phone": "138****0000",
    "email": "example@example.com",
    "city": "上海"
  },
  "education": [
    {"id": "edu-001", "school": "示例大学", "major": "计算机科学与技术", "degree": "本科",
     "start": "2023-09", "end": "2027-06", "status": "confirmed"}
  ],
  "experience": [
    {"id": "exp-001", "kind": "project", "org": "示例课程项目", "role": "后端开发",
     "start": "2025-03", "end": "2025-06",
     "highlights": ["负责示例接口设计与实现，QPS 待确认"], "status": "confirmed"}
  ],
  "skills": [
    {"name": "Python", "level": "熟练", "evidence": "课程项目与个人练习", "status": "confirmed"}
  ],
  "certifications": [
    {"name": "CET-6", "state": "备考中", "date": "", "status": "pending"}
  ],
  "preferences": {
    "cities": ["上海"], "salary_min": 8000, "salary_period": "month",
    "job_types": ["实习"], "industries": ["互联网"], "work_modes": ["onsite"]
  },
  "career_goals": {"short_term": "后端开发实习", "long_term": "服务端工程师"},
  "constraints": {"max_commute_minutes": 60, "unacceptable": []},
  "facts_sources": [
    {"fact_id": "fact-001", "fact": "学历：示例大学 计算机科学与技术 本科", "source": "用户口述",
     "confirmed_by": "user", "confirmed_at": "2026-10-29T12:00:00+08:00"}
  ],
  "open_questions": ["毕业时间是否为 2027-06？"]
}
```

## 6. 变更规则

1. 档案变更必须先征得用户同意，再更新 `profile.json`；`updated_at` 同步更新。
2. 重要事实变化（学历、证书、实习）先更新主档，再生成新的材料版本，避免材料与档案不一致。
3. 新增事实必须可追溯到 `facts_sources`；无法追溯的事实标 `pending` 并写入 `open_questions`。
4. 不删除历史来源记录；过期信息以 `expired` 标记而不是直接抹除。
5. 示例、测试与文档中一律使用占位人物与脱敏联系方式，不写入真实身份证号、住址、银行卡等。

## 7. 失败处理

| 情形 | 处理 |
| --- | --- |
| JSON 解析失败 | 停止，报告行号附近的语法问题；不自动重写整份档案 |
| 必填字段缺失 | 列出 `missing_fields`，请用户补充；相应材料暂不生成 |
| 枚举值非法 | 指出字段与合法枚举，请用户选择，不擅自映射 |
| 事实状态矛盾（如 `confirmed` 但无来源） | 降级为 `pending` 并列入待确认，不直接对外使用 |
| 档案文件不存在（退出码 `2`） | 提示从模板复制，等待用户确认 |
| 校验报告写失败 | 保留 stdout JSON，报告路径改为用户可写位置并说明 |
