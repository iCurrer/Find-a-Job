# resumes/ — 材料版本目录

本目录存放**对外材料**：主简历、岗位定制版简历、求职信、网申答案草稿。规则详见
[`../skills/job-agent/references/resume-policy.md`](../skills/job-agent/references/resume-policy.md)。

## 命名规范

| 类型 | 路径 |
| --- | --- |
| 主简历（基础简历，步骤 0 产出） | `resumes/main-resume-v{major}.{minor}.md` |
| 主简历版本说明 | `resumes/main-resume-v{major}.{minor}.VERSION.md` |
| 岗位定制版 | `resumes/{job_id}/resume-{job_id}-v{major}.{minor}.md` |
| 求职信 | `resumes/{job_id}/cover-letter-{job_id}-v{major}.{minor}.md` |
| 投递/跟进邮件草稿 | `resumes/{job_id}/email-{job_id}-{type}-v{major}.{minor}.md` |
| 版本说明 | `resumes/{job_id}/VERSION.md` |
| 导出文件 | 与 Markdown 源文件同目录同名（`.pdf` / `.docx`） |

## 基础简历优先

主简历不是「投某个岗位时才做的材料」，而是流程的**步骤 0**：档案校验通过后先生成
`resumes/main-resume-v1.0.md`，之后每个岗位只从它派生定制版（重排顺序、按 JD 术语改写表达），
不重复从零起草。定制版头部必须写明 `基准主简历版本`。

档案事实不足时**不生成简历**，只输出「缺口清单」（缺哪些字段、哪些事实仍是 `pending`、先补哪项收益最高）。
不得用占位符堆出一份看起来完整的空简历。规则见
[`../skills/job-agent/references/resume-policy.md`](../skills/job-agent/references/resume-policy.md) 第 0 节。

## 硬性约束

- **只新增版本，不覆盖历史版本**；同一版本号不得对应两份不同内容。
- 只有 `profile.json` 中 `status=confirmed` 的事实可以写入材料；缺失数字统一写占位 `〔待确认：<字段>〕`。
- 材料生成后填写 `VERSION.md`（目标岗位、基准主简历版本、变更摘要、待确认项），并把版本标识回填到投递记录：`resume_version` 形如 `resume-job-xxxx-v1.0`。
- 生成材料前先跑 `python scripts/validate_profile.py --profile profile/profile.json`。

> 本目录只由模型按 `resume-policy.md` 写入，脚本不生成、不改写简历。
