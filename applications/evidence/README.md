# applications/evidence/ — 提交证据

存放真实投递后的可验证证据（平台确认页截图、确认邮件截图、申请编号截图等）。

- 每份证据命名：`{job_id}-{YYYYMMDD}-{说明}.{png|pdf|txt}`，例如 `job-6d4169afd8-bb41-20261029-confirm.png`。
- 登记时只把**相对路径或可识别摘要**写进 `--evidence`，例如：
  `python scripts/update_application.py --job-id job-6d4169afd8-bb41 --status 已提交 --evidence "applications/evidence/job-6d4169afd8-bb41-20261029-confirm.png"`
- 证据不得包含密码、Cookie、令牌或验证码；截图中的身份证号等敏感信息请先打码。
- 没有证据时不要标记 `已提交`，保持 `执行中` 或转为 `需人工介入`。
