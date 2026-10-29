# 岗位评分规范（job-scoring）

## 适用范围

- 本文件定义岗位评分的六维权重、硬性门槛阻断、缺失信息与风险标注、分数与状态的关系。
- 在以下时机加载：岗位标准化与去重完成后、准备运行 `score_jobs.py` 之前；向用户解释分数、调整权重或处理阻断岗位之前。
- 权重与门槛的**数值来源**是 `config/scoring.json`；本文件只解释规则，不替代配置。评分结果是**匹配度参考**，不是成功率。

## 1. 评分原则

1. 可解释：每一维都有 0–100 的分项分、理由与可追溯依据（档案事实或岗位原文）。
2. 硬门槛优先：先判断硬性条件，再进行软性加权；硬性不满足时独立阻断，不能被总分掩盖。
3. 不知道就说不确定：岗位缺字段、档案未确认时写入 `missing_info` / `risk_flags`，不当作已满足。
4. 可重复：同一输入与同一权重版本必须得到同样结果；不使用随机性判断。
5. 权重可版本化：任何权重调整都要在 `config/scoring.json` 记录 `version` 与 `changelog`。

## 2. 六维权重

| 维度 | 权重 | 判断依据 | 0–100 分参考 |
| --- | --- | --- | --- |
| 岗位职责匹配 | **25%** | 实际经历、工作内容、技能相关性 | 职责与已确认经历高度重合为高分；仅名称相似为低分 |
| 硬性条件符合度 | **20%** | 学历、毕业时间、证书、经验、语言等 | 全部满足为高分；部分满足按缺口扣分；不满足可触发阻断 |
| 职业发展价值 | **20%** | 技能积累、行业可迁移性、未来发展 | 与 `career_goals` 一致、技能可迁移为高分 |
| 个人偏好符合度 | **15%** | 城市、岗位类型、行业、工作方式 | 命中 `preferences` 主要项为高分；冲突项要写明 |
| 薪资与资源条件 | **10%** | 薪资透明度、通勤成本、培训与成长 | 薪资未知记 `missing_info`，不按「默认可接受」给满分 |
| 招聘信息可信度 | **10%** | 来源可靠性、信息完整度、异常风险 | 官方渠道、字段完整为高分；缺链接、信息矛盾为低分 |

合计必须为 100%。若 `config/scoring.json` 的权重合计不等于 100% 或与上表不一致，按配置版本在报告中注明差异；无法解释时停止评分并请用户/项目维护者确认。

## 3. 计算方式

- 每维先打 0–100 分，再按权重加权求和；`match_score` 为四舍五入后的整数，各维 `weighted` 保留 1 位小数。
- `score_breakdown` 必须逐维记录：维度键、维度名、分数、权重、加权分、理由、依据（引用档案事实或岗位字段），例如：

```json
{
  "score_breakdown": [
    {"key": "responsibilities_match", "label": "岗位职责匹配", "score": 82, "weight": 0.25, "weighted": 20.5,
     "reasons": ["档案关键词 6 个，岗位描述命中 5 个（83%）"], "evidence": ["Python", "SQL"], "missing_info": [], "risks": []},
    {"key": "hard_requirements", "label": "硬性条件符合度", "score": 100, "weight": 0.2, "weighted": 20.0,
     "reasons": ["学历要求 本科，档案为 本科，满足"], "evidence": [], "missing_info": [], "risks": []},
    {"key": "career_value", "label": "职业发展价值", "score": 70, "weight": 0.2, "weighted": 14.0,
     "reasons": ["行业与偏好重合：互联网"], "evidence": [], "missing_info": [], "risks": []},
    {"key": "preference_fit", "label": "个人偏好符合度", "score": 95, "weight": 0.15, "weighted": 14.3,
     "reasons": ["城市符合偏好（上海）"], "evidence": [], "missing_info": [], "risks": []},
    {"key": "compensation", "label": "薪资与资源条件", "score": 60, "weight": 0.1, "weighted": 6.0,
     "reasons": ["明显低于薪资底线：岗位约 4200 元/月，底线约 6000 元/月"], "evidence": [], "missing_info": [], "risks": []},
    {"key": "source_credibility", "label": "招聘信息可信度", "score": 100, "weight": 0.1, "weighted": 10.0,
     "reasons": ["来源为可信渠道且带原始链接"], "evidence": [], "missing_info": [], "risks": []}
  ],
  "match_score": 85
}
```

- 理由必须能回答「为什么是这个分」，不得只写「较匹配」。

## 4. 硬性门槛（独立阻断）

硬性门槛包括但不限于：学历层次、毕业时间/届别、证书、经验年限、语言要求、工作地点/通勤、工作方式、薪资下限、`constraints.unacceptable` 命中项。

规则：

1. 门槛判定只使用档案中 `status=confirmed` 的事实；档案未确认该项 → 记为 `missing_info`，**不得视为已满足**。
2. 任一硬性条件明确不满足 → `blocked=true`，状态直接判 `不匹配` 或 `暂缓`，并在 `reasons[]` 写明冲突项（哪条门槛、岗位要求、档案事实）。
3. 门槛无法判断（信息缺失）→ 不阻断，但必须写入 `missing_info`，状态不得判为 `优先投递` 而无提示。
4. 总分不得用于覆盖阻断：报告中阻断岗位单独成组，不参与「优先投递」排序，或排名中明确标注 `blocked=true`。

## 5. `missing_info` 与 `risk_flags`

| 情形 | 记入 | 要求 |
| --- | --- | --- |
| 岗位未提供薪资 | `missing_info` | 薪资维度不得给高分，也不得按「可接受」处理 |
| 缺少来源链接或来源不明 | `risk_flags` + 信息可信度扣分 | 报告标注来源风险 |
| 要求证书但档案未确认 | `missing_info` / `risk_flags` | 不得声称「已取得」或「符合」 |
| 岗位信息自相矛盾（如地点与描述冲突） | `risk_flags` | 请用户核实后再投 |
| 发布时间过久/链接失效 | `risk_flags`，必要时状态 `已过期` | 提醒重新核实 |
| 职责描述过泛、无法判断 | `missing_info` | 建议补充原文或向招聘方确认 |

`missing_info` 与 `risk_flags` 都必须出现在 `score_jobs.py` 的输出与 Markdown 报告中，不能只存在于中间过程。

## 6. 分数与状态

- 岗位状态枚举：`待评估|优先投递|暂缓|不匹配|已过期`。
- 状态映射（例如「优先投递的分数线」）以 `config/scoring.json` 的阈值配置为准；本文件不硬编码未在配置中声明的阈值。
- 若 `config/scoring.json` 未定义阈值：只能依据硬性门槛判定 `不匹配/暂缓`，其余保持 `待评估`，并在报告中说明「阈值配置缺失」。
- 已过期岗位单独标记 `已过期`，不进入推荐排序。
- **分数不是成功率**：禁止使用「录取概率」「通过率」「命中率」等表述；统一表述为「匹配分」「匹配度参考」。

## 7. 权重版本与变更记录

`config/scoring.json` 必须包含可追溯的版本信息：

```json
{
  "schema_version": "1.0",
  "version": "1.0.0",
  "updated_at": "2026-10-29T12:30:00+08:00",
  "weights": {
    "responsibilities_match": 0.25,
    "hard_requirements": 0.20,
    "career_value": 0.20,
    "preference_fit": 0.15,
    "compensation": 0.10,
    "source_credibility": 0.10
  },
  "thresholds": {"priority": 78, "consider": 60, "blocked_status": "不匹配"},
  "changelog": [
    {"version": "1.0.0", "date": "2026-10-29", "note": "首版权重，与方案 6.2 初始假设对齐"}
  ]
}
```

变更要求：

1. 每次调整权重必须递增 `version`、写明变更原因与日期，并保留旧记录（不覆盖历史 changelog）。
2. 权重变化后，用同一批岗位重新评分，报告中标注新旧版本与分数差异。
3. 变更需用户确认；未确认的权重不得直接用于对外建议。
4. `SKILL.md` 版本与评分规则变化要同步更新，避免文档与配置不一致。

## 8. 运行命令与示例

```bash
python scripts/score_jobs.py --jobs jobs/jobs.normalized.json --profile profile/profile.json \
  --config config/scoring.json --output jobs/jobs.scored.json --report reports/scored-report.md
```

输出契约：`{ok, count, ranking[{job_id, company, title, score, status, blocked, reasons[], risks[], missing_info[]}]}`。

示例输出片段（占位数据）：

```json
{
  "ok": true,
  "count": 2,
  "ranking": [
    {"job_id": "job-6d4169afd8-bb41", "company": "示例科技", "title": "后端开发实习生",
     "score": 82.3, "status": "优先投递", "blocked": false,
     "reasons": ["职责与项目经历重合", "地点与偏好一致"],
     "risks": ["岗位未提供薪资"], "missing_info": ["salary_min", "posted_at"]},
    {"job_id": "job-6716c6394a-7bc1", "company": "示例网络", "title": "算法实习生",
     "score": 68.5, "status": "不匹配", "blocked": true,
     "reasons": ["硬性门槛不满足：要求硕士，档案为本科"],
     "risks": [], "missing_info": []}
  ]
}
```

## 9. 失败处理

| 情形 | 退出码 | 处理 |
| --- | --- | --- |
| 权重合计 ≠ 100% 或维度名不匹配 | `1` | 停止评分，报告配置问题；请维护者修正 `scoring.json`，不擅自改权重 |
| 档案含 `pending` 硬性事实（学历/证书/语言） | — | 记入 `missing_info` / `risk_flags`，不得当作已满足；状态不得判为 `优先投递` 而无提示 |
| 输入岗位文件缺失或参数错误 | `2` | 核对 `--jobs` 路径与命令；不生成空结果 |
| 单个岗位字段异常 | `1` | 逐条列出异常岗位；其余岗位是否继续以脚本输出为准，不手工拼接结果 |
| 输出文件写入失败 | `1`/`2` | 保留 stdout JSON，报告路径建议改为可写目录并说明原因 |
| 权重版本与报告不一致 | — | 报告注明实际使用的 `version`；无法确认时暂停给用户决策 |
