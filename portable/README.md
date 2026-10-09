# WorkBuddy DDL 管家 · 跨电脑部署包

公开版本：2026.10.09。适用于安装了 WorkBuddy 的 Windows x64 电脑。

## 最快部署：三个入口

1. **完整解压**到一个固定文件夹。新电脑先打开并登录 WorkBuddy，连接自己的 QQ 机器人，然后退出 WorkBuddy。
2. 双击 **setup.cmd**。它自动识别本机 WorkBuddy Python／Node，部署工具、回复规范、QQ依赖、MCP和原生定时任务。默认工作目录是当前 Windows 用户的 `WorkBuddy/Claw`。
3. 打开 WorkBuddy，使用上述工作目录；给已连接机器人发一句话，再双击 **qq-setup.cmd**。必要时手机QQ扫码授权同一机器人。脚本发送一条测试卡片，只有取得真实平台回执后才启用定时推送。

在 QQ 收到测试卡片后，再发“我这周有什么”，核实**收件、查询和回复**都正常。测试发送成功不等于所有定时任务已经运行过。

在 WorkBuddy 中可以直接说：

> 读取当前工作目录 ddl-manager/AGENT.md 和 ddl-manager/回复格式规范.md，启用 DDL 管家。使用持久化工具管理事项，QQ回复采用18类固定Markdown格式，定时任务使用WorkBuddy内置调度。先查询真实状态，说明已验证和未验证项；不要重复创建已有定时任务。

## 包含的资源

| 目录／入口 | 内容 |
| :--- | :--- |
| app | 当前运行代码：持久化、修改恢复、重复事项、官网雷达、摘要、发送去重、数据库快照 |
| app/回复格式规范.md | 18类固定回复格式及完整示例 |
| app/qq-bot-connect | WorkBuddy本地技能适配 |
| app/runtime | QQ SDK、扫码连接器、二维码库及依赖、许可证；无需重新下载npm依赖 |
| personal-backup（可选） | 仅在本机自行添加的私人迁移数据；公开包不提供 |
| resources | 系统架构流程图 |
| check.cmd | 本地自检；不发送QQ消息、不创建真实测试任务 |
| export-data.cmd | 后续导出SQLite一致性数据副本 |
| manifest.json | 安装文件SHA-256清单，安装前自动校验 |

公开包**不含个人待办资料**，首次安装创建空白数据库。没有包含QQ密钥、DPAPI授权文件、WorkBuddy登录缓存、发送回执或聊天日志。QQ授权绑定Windows本机用户，不能直接拷贝旧授权来使用。

## 数据迁移

公开包默认首次安装创建空白数据库。只有自行添加 `personal-backup/ddl.sqlite3` 时才导入该本地备份；不要提交私人备份到GitHub。已有DDL数据库、QQ配置和推送开关不会被覆盖。旧发送队列、编号上下文与提醒去重记录在迁移副本中已清空，避免新电脑补发旧消息。

想从空白开始，在PowerShell运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -Fresh
```

`-Fresh`只控制**首次安装是否导入备份**，不会删除或清空已有数据库。两个电脑的SQLite数据不会自动同步。作为正式运行设备切换时，停用旧电脑这套DDL定时任务，避免两边同时提醒。

后续数据导出可运行 `export-data.cmd`。恢复数据库前先暂停本套定时任务、退出WorkBuddy，保留当前数据库备份，再用一致性导出副本替换数据库；重新连接核实本机QQ并清理旧发送队列。

## 原生定时任务

默认创建：每天08:00早间摘要、每天21:30晚间复盘、每4小时校园机会雷达，均按北京时间。

安装器使用当前已登录用户的WorkBuddy本地调度数据；要求**WorkBuddy已退出**，修改前自动备份。只修改本套3个任务，不创建Windows计划任务或外部Gateway。

没有识别到登录账号，或新版WorkBuddy的表结构不匹配时，安装器会保留主系统安装结果并说明定时任务尚未注册。先登录／连接QQ、退出后重跑setup.cmd；仍不支持时按照部署目录中生成的 **原生定时任务.md**，在WorkBuddy“定时任务”页创建3项。已自动注册的任务不要重复创建。

电脑需开机且WorkBuddy保持登录运行，本地定时任务才能执行。界面显示任务已注册与实际执行成功是两项验证。

## 环境与路径

不需要Codex或OpenClaw Gateway。使用新电脑现有的 WorkBuddy Python（3.10及以上）和 Node（建议WorkBuddy自带22版）。Release ZIP 的QQ依赖已打包，但登录、QQ发送和校园通知抓取仍需要网络。源码检出后先在 `app/runtime` 运行 `npm ci`，再运行 setup.cmd。

如果WorkBuddy尚未下载Python／Node，先在WorkBuddy新建普通本地任务，让它初始化本地Python和Node环境，再安装。

自定义位置时：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -WorkspacePath 'D:\学习助手\Claw' -PythonPath 'D:\运行环境\python.exe' -NodePath 'D:\运行环境\node.exe'
```

WorkBuddy用户配置目录默认 `%USERPROFILE%/.workbuddy`，特殊环境可追加 `-WorkBuddyHome '实际目录'`。安装后保持 `installed.json` 与安装包同目录，它记录各入口使用的本机位置。

## QQ设置常见情况

- 本机只有一个已启用的QQ机器人时自动选择它；多个机器人不猜测目标。
- 从本机入站日志提取真实 `userOpenId`。没有日志或多个目标时先在WorkBuddy核实目标，可运行 `qq-setup.ps1 -OpenId '本机真实32位OpenID'`。
- `ROBOT1.0_...`是消息ID；`claw:user:...`是内部会话键，都不能当QQ私聊目标。
- WorkBuddy保存的加密授权不会被强行解密；需要时通过打包的连接器扫码取得本机发送授权。扫码后如果WorkBuddy原收件连接需要刷新，在WorkBuddy里恢复连接，再同时核查收件和发送。
- 未取得真实回执时推送保持关闭；不把终端输出或任务完成标记当成QQ送达。

## 自检与验收

运行check.cmd检查本地数据库工具、回复模板测试和QQ SDK加载。QQ状态只表示本机配置与已有回执，不保证当前网络和授权仍有效。

部署验收顺序：QQ查询能返回真实数据 → 新电脑测试卡片确实收到且表格清晰 → WorkBuddy显示3个原生定时任务 → 首次定时执行后检查运行记录与QQ实际收件。

此包已在当前电脑的隔离临时目录验证部署、路径替换、重复安装、数据库保护、MCP、模板和依赖加载；尚未在你另一台实体电脑上运行。不同WorkBuddy版本可能需要按上述说明在界面补建定时任务。
