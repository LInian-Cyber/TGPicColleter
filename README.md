# TG Pic Collector

TG Pic Collector 是一个使用 Telethon、PySide6 与 PySide6-Fluent-Widgets 编写的 Telegram 图片下载桌面工具。它可以按频道和 Tag 搜索帖子，预览命中的帖子、评论区图片与原图链接，并把图片按规则保存到本地。

本项目不是 Telegram 官方产品，也不受 Telegram 官方认可。下载和使用内容时，请遵守目标频道规则、内容版权要求与 Telegram API Terms。

## 功能

- 支持手机号验证码登录、二维码登录、两步验证、本地 Session 恢复。
- 支持多账号本地会话列表，已登录账号可免扫码切换。
- 支持频道用户名、频道 ID、`t.me/...`、`t.me/c/.../消息ID` 输入。
- 支持按 Tag 搜索，也支持不填 Tag 扫描全部帖子。
- 支持日期范围筛选、最多检查帖子数、搜索预览最多展示数量。
- 支持下载帖子评论区图片、回复图片、正文超链接、按钮链接和评论区原图链接。
- 支持高级提取规则，用于 SFW/NSFW、正文链接、评论链接、套娃跳转等复杂频道结构。
- 支持扫描与下载并行队列、下载速度、队列剩余、ETA、暂停、继续、停止。
- 支持保存模式、保留原名、自定义命名、重复文件处理、扩展信息 sidecar。
- 支持下载历史、任务记录、日志查看、频道缓存管理。
- 支持首页统计、下载趋势、常用 Tag、系统托盘、Windows 系统通知。
- 支持浅色、深色、跟随系统主题，以及中英文界面切换。
- 支持 IGP / 元数据导出。
- 支持 Yande.re 图片搜索、预览、原图下载、登录 Cookie、child post 合并和 IGP sidecar。

## 支持平台

| 平台 | 发布包 | 说明 |
| --- | --- | --- |
| Windows x64 | `.zip` | 支持 DPAPI 会话加密 |
| Linux x64 | `.tar.gz` | 解压后运行 |
| macOS Intel | `.zip` | 未签名，首次运行可能需要手动放行 |
| macOS Apple Silicon | `.zip` | 未签名，首次运行可能需要手动放行 |

## 从源码运行

建议使用 Python 3.11。

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python main.py
```

Windows PowerShell 激活虚拟环境后，也可以运行：

```powershell
.\.venv\Scripts\python.exe main.py
```

首次使用前，在 https://my.telegram.org/apps 创建应用并获取 `API ID` 和 `API Hash`，然后在应用的“设置 -> 会话与安全”中填写凭据。二维码和手机号登录都需要这两个凭据。

## 使用说明

1. 在“设置 -> 会话与安全”填写 Telegram `API ID`、`API Hash`。
2. 在“登录中心”使用二维码或手机号登录。
3. 在“下载任务”填写频道、Tag、保存目录和本次下载选项。
4. 可先点“搜索预览”，确认命中来源、缩略图和追踪链路。
5. 点击“开始下载”，下载完成后可打开目录或在历史中查看记录。

常见配置：

- “每次最多检查帖子数量”限制本次从频道里匹配多少篇帖子，不是图片数量。
- “搜索预览最多展示帖子数”只影响预览弹窗，不影响实际下载总数。
- “包含回复中的图片”控制是否读取评论区/回复区。
- “追踪帖子正文超链接并下载原图”会追踪正文、按钮、评论中的 Telegram 帖子链接，并下载目标帖子的真实媒体。
- “高级提取规则”适合复杂频道，例如 A 帖正文跳 B、A/B 评论链接再跳 C/D 原图资源帖。

## 本地数据与安全

- 配置、API 凭据、账号列表与 Telethon Session 保存在操作系统用户应用数据目录，不会写入项目目录或打进安装包。
- Windows 可启用 DPAPI 加密 Session；macOS 与 Linux 当前依赖用户目录权限保护。
- 不要提交 `tg-api.txt`、`.session`、`.env`、登录验证码、两步验证密码、手机号或任何真实 API 凭据。
- 报告安全问题时，请通过 GitHub Security Advisories 私下提交，不要在公开 issue 中附带敏感信息。

已忽略的本地文件包括 `.venv/`、`build/`、`dist/`、`tg-api.txt`、`.session`、`ui/` 设计稿和本地临时目录。

## 本地打包

PyInstaller 不能交叉编译。要构建某个平台的应用，必须在该平台运行构建命令。

```bash
python -m pip install -r requirements-build.txt
python -m PyInstaller --noconfirm --clean TG-Pic-Collector.spec
```

Windows 也可以使用：

```powershell
.\build_exe.ps1
```

默认构建为启动更快、运行更稳定的 `onedir`。Windows 如需单文件版本可运行：

```powershell
.\build_exe.ps1 -OneFile
```

## GitHub Actions 发布

仓库包含 `.github/workflows/release.yml`，会在不同系统的 GitHub Runner 上分别构建，不能也不需要在本机安装另外两个操作系统。

首次发布：

```bash
git add .
git commit -m "Prepare release"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
git tag v2.4
git push origin v2.4
```

推送 `v*` 标签后，在 GitHub 的 Actions 页面可以查看四个平台的构建进度。全部完成后，工作流会自动创建对应标签的 Release，并上传四个压缩包。

也可以在 Actions -> Build release -> Run workflow 手动构建。手动运行只生成可下载的 Actions Artifacts，不会创建正式 Release。

## 贡献

欢迎提交 issue 和 pull request。

- 从 `main` 创建功能分支。
- 不要提交 Telegram API 凭据、手机号、登录验证码、两步验证密码或 Session 文件。
- 保持 UI 与项目现有 Fluent 桌面风格一致。
- PR 中请说明用户可见变化、平台影响和验证方式。

贡献代码将按本项目许可证发布。

## 更新记录

### v2.4

- 新增 Yande.re 页面，支持按 Tag、评分、分数、日期、Post 链接/ID 搜索预览与原图下载。
- 支持 Yande 登录 Cookie、child post 合并、并发下载、失败重试和 `.igp.json` sidecar。
- 完善 Telegram 高级规则追踪，支持正文链接、评论区资源链接、SFW/NSFW 套娃跳转和真实媒体下载。
- 修复 Telegram 手动删除已下载文件后无法再次下载的问题，缺失文件会自动重新入队。
- 修复 Telegram 下载误收贴纸的问题，排除普通贴纸、动态贴纸和 video sticker。
- 优化任务与历史、搜索预览、托盘菜单、关闭行为、频道缓存、日志筛选和系统通知体验。
- 改进暗色主题、tooltip、设置页布局、表格滚动和任务按钮状态。
- 增加 GitHub Actions、PyInstaller spec、发布配置和忽略规则。

### v2.3.1

- 增加保存为模板、重置本次覆盖、继续上次任务。
- 增加 Windows DPAPI 会话加密。
- 增加动画、圆角、语言等设置项。
- 优化任务页面表单布局和按钮尺寸。

## 第三方组件

主要依赖：

- PySide6：LGPL-3.0/GPL-3.0
- PySide6-Fluent-Widgets：开源使用 GPL-3.0
- Telethon：MIT
- PyInstaller：GPL-2.0 with special exception
- qrcode / Pillow / cryptg：以各自上游许可证为准

二进制发布包包含第三方组件，请以依赖包元数据和上游项目许可证为准。

## 许可证

本项目使用 GPL-3.0-only 发布，因为开源版本使用的 PySide6-Fluent-Widgets 采用 GPL-3.0。

完整许可证文本见 `LICENSE`。
