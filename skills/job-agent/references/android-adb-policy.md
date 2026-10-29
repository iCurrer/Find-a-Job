# 手机执行器规范（android-adb-policy）

> 适用：P5 阶段及之后，需要通过 Android 设备读取或操作招聘 App 的动作。
> 定版：2026-10-29 ｜ 对应 `config/settings.json` 的 `mobile_exec` 能力项。
>
> **当前状态：`unverified`。** 2026-10-29 实测本机：`adb` 不在 PATH，常见安装位置
> （`%LOCALAPPDATA%\Android\Sdk\platform-tools`、`C:\Android`、`D:\Android`）均不存在，也未安装 `scrcpy`。
> 因此本文件是**规范先行**，所有条款在设备接入并完成第 8 节验证前一律不生效。

## 0. 为什么手机端要做，以及为什么规则更严

国内招聘（Boss 直聘、猎聘、前程无忧、实习僧等）大量功能只在 App 内提供，网页端残缺。所以手机执行器有实际价值。

但手机端的风险**高于**浏览器端，原因是：

| 浏览器端 | 手机 App 端 |
| --- | --- |
| 误点提交，通常可在平台内撤回或修正 | 给 HR **发出消息不可撤回**，直接影响求职形象 |
| 页面可截图、可读 DOM 复核 | UI 树不稳，App 版本一更新选择器全失效 |
| 可随时关标签页 | 可能误触拨号、支付、授权、订阅 |
| 登录态在浏览器，可弃用 | 登录态绑定设备，误操作波及真实账号 |

所以手机端的总原则比浏览器端更保守：**只读 + 填写，绝不发送。**

## 1. 总原则（四条，冲突时按序）

1. **只读优先于写入，填写优先于提交。** 手机端**禁止**执行任何「发送/投递/打招呼/拨号/支付」类动作，一律由用户本人点。这是与浏览器端的最大差别（浏览器端在用户单独授权后允许点一次提交，手机端不允许）。
2. **定位优先于坐标。** 用 `uiautomator dump` 拿 UI 树定位元素，坐标点击仅在 UI 树取不到时使用，且必须每次重新截图。
3. **USB 单设备，用完断开。** 禁止无线调试、禁止 `adb tcpip`。
4. **截图与 UI 树是隐私载体。** 手机截图含手机号、真实姓名、头像、聊天记录，落盘规则见第 6 节。

## 2. 连接与会话

| 动作 | 命令 | 规则 |
| --- | --- | --- |
| 列出设备 | `adb devices -l` | 每次会话第一条命令。必须恰好 **1 台** `device` 状态；出现 `unauthorized` / `offline` 先让用户处理授权弹窗，不得反复 `adb kill-server` |
| 指定设备 | `adb -s <serial> <cmd>` | 设备数 > 1 时**强制**带 `-s`，禁止省略（否则命令随机落在一台设备上，可能操作错手机） |
| 版本确认 | `adb version`、`adb shell getprop ro.build.version.release` | 记录到报告，Android 版本影响后续命令可用性 |
| 收尾 | `adb kill-server`（可选） | 会话结束建议执行；同时提醒用户关闭 USB 调试 |

**禁止**

- `adb tcpip <port>` / `adb connect <ip>`：把 5555 调试端口暴露到局域网，同网段任何设备可完全控制手机。
- `adb root`、`adb remount`：提权后误操作可损坏系统分区。
- `adb install` / `adb uninstall` / `adb push` 到 `/system`、`/data/local/tmp` 之外的系统路径。
- `adb backup`：可导出应用私有数据，且 Android 12+ 已基本失效；一律不用。
- 未获用户明确许可即连接任何设备。

## 3. 只读探测层（L0，安全）

这一层不需要逐次确认（但仍受第 6 节隐私约束）：

| 目的 | 命令 |
| --- | --- |
| 当前前台页面 | `adb shell dumpsys window \| grep -E "mCurrentFocus\|mFocusedApp"` |
| 当前 Activity（备用） | `adb shell dumpsys activity activities \| grep -E "ResumedActivity\|topResumedActivity"` |
| 已安装招聘类 App | `adb shell pm list packages \| grep -iE "zhipin\|liepin\|51job\|shixiseng\|kanzhun\|maimai"` |
| 屏幕分辨率与密度 | `adb shell wm size`、`adb shell wm density` |
| 截图 | 见下方「截图正确写法」 |
| UI 树 | `adb shell uiautomator dump /sdcard/ui.xml && adb pull /sdcard/ui.xml <本地路径>` |
| 直接输出 UI 树 | `adb exec-out uiautomator dump /dev/tty`（部分 ROM 支持，失败则用上一条） |

**截图正确写法（Windows 上的真实坑）**

```bash
# 推荐：先存设备端再 pull，二进制不经 shell 重定向，绝不会损坏
adb shell screencap -p /sdcard/shot.png && adb pull /sdcard/shot.png logs/screens/xxx.png && adb shell rm /sdcard/shot.png

# 在 Git Bash 下可用，但 PowerShell 下会把二进制当文本处理导致 PNG 损坏
adb exec-out screencap -p > logs/screens/xxx.png
```

> 结论：**统一用「设备端落盘 + pull + 删设备端文件」三步**，不用管道重定向。这样在 PowerShell / cmd / Git Bash 下行为一致。

## 4. 写入层（L1/L2，逐项确认）

| 层级 | 动作 | 命令 | 确认要求 |
| --- | --- | --- | --- |
| L1 导航 | 回到桌面 / 返回 / 启动指定 App | `input keyevent KEYCODE_HOME`(3)、`KEYCODE_BACK`(4)、`am start -n <pkg>/<activity>` 或 `monkey -p <pkg> -c android.intent.category.LAUNCHER 1` | 说明要去哪个 App |
| L2 滚动 | 上滑/下滑 | `input swipe <x1> <y1> <x2> <y2> <duration_ms>` | 说明目的是找到某元素 |
| L2 点击 | 点击已定位元素 | `input tap <x> <y>` | 说明点的是哪个元素、点了会发生什么 |
| L2 输入 | 填文本 | `input text <ASCII>` | 说明填哪个字段、值来自档案哪条 `confirmed` 事实 |

**屏幕唤醒**：优先 `input keyevent KEYCODE_WAKEUP`(224)，**不要**用 `KEYCODE_POWER`(26)——后者是**切换**状态，屏幕本来就亮时会把它锁掉。

### 4.1 中文输入的硬坑（必读）

`adb shell input text` **只支持 ASCII 可打印字符**，直接传中文会失败（静默忽略或报错）。同时空格需转义为 `%s`，`&`、`(`、`)` 等需 URL 编码。这是硬限制，不是配置问题。

三种可行方案，按推荐顺序：

| 方案 | 做法 | 代价 |
| --- | --- | --- |
| ① 交给人 | 需要填中文时，滚动到该字段、聚焦，让用户自己输入 | 零风险，最稳，但打断流程 |
| ② ADBKeyBoard 输入法 | 安装 ADBKeyBoard（开源输入法，监听广播接收 UTF-8 文本），`adb shell am broadcast -a ADB_INPUT_TEXT --es msg '中文'` | 需装第三方输入法并切换默认输入法，属于**修改设备配置**，必须用户明确许可 |
| ③ 剪贴板 | `adb shell cmd clipboard set-text`（仅部分 Android 版本支持）配合长按粘贴 | 版本兼容性差，不稳定 |

> **默认采用方案 ①。** 方案 ② 涉及安装 App 与改系统输入法，按项目铁律必须用户逐次授权，且用完要切回原输入法。
> 本条的可行性在设备接入前**未实测**，标记为待验证项。

### 4.2 禁止的写入动作

| 禁止 | 原因 |
| --- | --- |
| 点击任何「发送」「投递」「打招呼」「立即沟通」「确认」类按钮 | 消息不可撤回，误触直接损害求职形象。此类动作**永远由用户本人完成** |
| `input text` 填入密码、验证码、身份证号 | 凭据不经本 Skill 之手（`security-policy.md`） |
| `input keyevent` 模拟支付/确认键序列 | 可能造成真实扣款 |
| `pm clear <pkg>` | 清空 App 数据，退出登录并丢失本地记录 |
| `settings put` 改任何系统设置 | 影响用户设备全局行为 |
| `input tap` 到拨号键、订阅键、授权弹窗的「始终允许」 | 副作用不可控 |
| 连续盲点（点击后不截图不复核就点下一个） | 极易误触 |

## 5. 必须立即停止的情形

| 停止条件 | 判定 |
| --- | --- |
| 出现验证码、滑块、人脸识别 | 截图或 UI 树含相关文案 |
| 出现登录/注册/实名认证 | 一律停，交由用户 |
| 页面要求读取通讯录、相册、位置权限 | 停，不代点授权 |
| 出现「安全验证」「账号异常」「请稍后再试」 | 停，说明可能触发风控 |
| UI 树取不到目标元素，且坐标点击一次无效 | 停，不重试第 2 次 |
| 设备断开 / `adb devices` 变为 `offline` | 停，不自动重连循环 |

**禁止自动重试**：与浏览器端一致，一次触发即停，不换方案硬绕。

## 6. 截图与 UI 树落盘（隐私）

手机截图的隐私密度远高于网页：常同时包含真实姓名、手机号、头像、聊天记录、身份证照片预览。

| 规则 | 做法 |
| --- | --- |
| 位置 | 只允许 `logs/screens/`（已 `.gitignore`） |
| 命名 | `logs/screens/<UTC时间戳>-<job_id>-android-<用途>.png`，用途取 `read` / `filled` |
| 设备端清理 | 每次 `pull` 后立即 `adb shell rm /sdcard/<file>`，不留副本在手机 |
| UI 树 | 同上，`ui.xml` 存 `logs/screens/`，用完即删；**禁止**把 XML 全文写进报告 |
| 报告引用 | 只写文件名与用途，不转录截图内容 |
| 禁止 | 截图/录屏上传第三方；把含手机号的截图放进 `resumes/`、`reports/`、`docs/` |

## 7. 与浏览器端的分工

| 场景 | 用哪个执行器 |
| --- | --- |
| 企业官网投递、网申表单 | 浏览器（A 路径，用户已登录标签页） |
| 岗位信息批量采集 | 浏览器只读 |
| 仅 App 内提供的功能（打招呼、App 内简历投递、HR 即时沟通） | 手机只读 + 引导用户手动操作 |
| 需要发送消息给 HR | **两个执行器都不做**，永远人工 |

## 8. 从 `unverified` 变 `verified` 的条件（缺一不可）

1. `adb` 已安装且 `adb version` 可执行，路径登记在环境变量或 `config/settings.json`；
2. `adb devices -l` 稳定输出恰好 1 台 `device`；
3. 完成一次**只读闭环**：`dumpsys window` 取到前台页面 + `screencap` 截图成功 + `uiautomator dump` 取到 UI 树，三样都成功；
4. 上述证据写入 `config/settings.json` 的 `mobile_exec.evidence`，含设备型号、Android 版本、时间；
5. 用户本人确认「允许该设备接入」。

未满足全部 5 条时，`mobile_exec` 保持 `unverified`，所有手机操作走 `5.3 降级输出（人工操作清单）`。

## 9. 快速自检（每次手机操作前）

- [ ] `adb devices -l` 是否恰好 1 台且为 `device`？
- [ ] 是否带了 `-s`（多设备时）？
- [ ] 本轮是要「读」还是「写」？写操作是否已说清点哪个元素、会发生什么？
- [ ] 有没有碰到任何「发送/投递/授权/支付」类按钮？（有 → 停，交给人）
- [ ] 需要输入中文吗？（是 → 默认交给人，不要硬用 `input text`）
- [ ] 坐标点击前是否重新截了图？点击后是否复核了？
- [ ] 截图存 `logs/screens/` 了吗？设备上的副本删了吗？
- [ ] 出现验证码/权限弹窗/风控提示时，是否会立即停？
