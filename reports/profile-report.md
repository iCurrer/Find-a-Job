# 个人档案校验报告

- 档案：`.tests_tmp_9328/bad_profile.json`
- 校验时间：2026-10-29T16:46:07+08:00
- 结论：存在结构错误

## 结构错误（12）
- 缺少顶层字段: profile_id
- 缺少顶层字段: updated_at
- 缺少顶层字段: basics
- 缺少顶层字段: education
- 缺少顶层字段: experience
- 缺少顶层字段: skills
- 缺少顶层字段: certifications
- 缺少顶层字段: preferences
- 缺少顶层字段: career_goals
- 缺少顶层字段: constraints
- 缺少顶层字段: facts_sources
- 缺少顶层字段: open_questions

## 警告（6）
- preferences.cities 为空，无法判断地点是否符合
- preferences.salary_min 未填写，薪资维度将只能给默认分
- basics.name 未填写（对外材料提交前必须补全）
- basics.phone 未填写（对外材料提交前必须补全）
- basics.email 未填写（对外材料提交前必须补全）
- basics.city 未填写（对外材料提交前必须补全）

## 待确认事实（0）
- 无

## 待确认问题（0）
- 无

> 说明：pending 事实只能出现在“待确认清单”中，不能写入简历、求职信或网申答案。
