# resumes/ — 材料版本目录

本目录存放**对外材料**：主简历、岗位定制版简历、求职信、网申答案草稿。规则详见
[`../skill/references/resume-policy.md`](../skill/references/resume-policy.md)。

## 命名规范

| 类型 | 路径 |
| --- | --- |
| 主简历 | `resumes/main-resume-v{major}.{minor}.md` |
| 岗位定制版 | `resumes/{job_id}/resume-{job_id}-v{major}.{minor}.md` |
| 求职信 | `resumes/{job_id}/cover-letter-{job_id}-v{major}.{minor}.md` |
| 版本说明 | `resumes/{job_id}/VERSION.md` |
| 导出文件 | 与 Markdown 源文件同目录同名（`.pdf` / `.docx`） |

## 硬性约束

- **只新增版本，不覆盖历史版本**；同一版本号不得对应两份不同内容。
- 只有 `profile.json` 中 `status=confirmed` 的事实可以写入材料；缺失数字统一写占位 `〔待确认：<字段>〕`。
- 材料生成后填写 `VERSION.md`（目标岗位、基准主简历版本、变更摘要、待确认项），并把版本标识回填到投递记录：`resume_version` 形如 `resume-job-xxxx-v1.0`。
- 生成材料前先跑 `python scripts/validate_profile.py --profile profile/profile.json`。

> 本目录只由模型按 `resume-policy.md` 写入，脚本不生成、不改写简历。
