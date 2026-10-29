# 审计日志目录

本目录用于存放运行时审计日志（JSONL）。

- `applications.jsonl`：投递状态变更审计，由 `scripts/update_application.py` 追加写入。
- 日志内容不包含密码、Cookie、令牌或验证码。

> 日志文件已在 `.gitignore` 中排除（`logs/*.jsonl`），不会进入版本库。
