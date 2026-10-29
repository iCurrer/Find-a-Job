# 事实来源登记（profile/sources.md）

本文件说明 `profile/profile.json` 中 `facts_sources` 的登记方式与确认流程。字段结构见
[`../skills/job-agent/references/profile-schema.md`](../skills/job-agent/references/profile-schema.md)。

## 为什么需要

方案 1.2 的验收标准要求“档案中的关键事实有来源或明确标记为待确认”。`facts_sources` 就是这条要求的落点：
简历、求职信、网申答案里的每一条事实，都应该能追溯到某条已确认记录；追溯不到的，只能是 `pending`。

## 登记规则

1. 一条事实一个条目，粒度到“可核对”：学历、毕业时间、每段实习/项目、每个证书、每项关键技能。
2. `source` 写来源类型与可核对的引用，例如：
   - `用户口述并核对学籍信息`
   - `成绩单截图（用户保存）`
   - `实习证明草稿`
   - `课程项目 README`
3. `confirmed_by` 只写 `user`（必须由你本人确认，模型不能代替）。
4. `confirmed_at` 写 ISO 8601 时间，例如 `2026-10-28T20:00:00+08:00`。
5. 来源丢失、记不清、无法核对的，不要登记为已确认：把对应条目的 `status` 改成 `pending`，
   并写进 `open_questions`。
6. 过期资料（例如旧版成绩单）把 `status` 改成 `expired`，重新核对后再改回 `confirmed`。

## 示例

```json
{
  "fact_id": "fact-001",
  "fact": "学历：示例大学 计算机科学与技术 本科，2027-06 毕业",
  "source": "学籍信息核对（用户口述 + 教务系统截图）",
  "confirmed_by": "user",
  "confirmed_at": "2026-10-28T20:00:00+08:00"
}
```

## 确认流程

1. 从 `profile/profile.template.json` 起草档案，把不确定的条目标 `pending`。
2. 逐条向用户确认，确认一条就补一条 `facts_sources`，并把该条 `status` 改为 `confirmed`。
3. 运行 `python scripts/validate_profile.py --profile profile/profile.json --report reports/profile-report.md`，
   确认 `pending_facts` 与 `open_questions` 都已列出、没有遗漏。
4. 生成材料前再检查一次：材料中出现的每个数字、时间、证书，都必须能在 `facts_sources` 中找到依据；
   找不到的写成 `〔待确认：<字段>〕`，不得估填。

> 事实状态与材料规则详见 `skills/job-agent/references/resume-policy.md`；档案结构详见 `skills/job-agent/references/profile-schema.md`。
