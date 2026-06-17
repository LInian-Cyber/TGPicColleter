# TG Pic Collector

TG Pic Collector 是一个使用 Telethon、PySide6 与 PySide6-Fluent-Widgets 编写的桌面工具。它可以按 Tag 搜索频道帖子，预览命中的对话与图片，并下载帖子及评论区中的图片。

支持二维码登录、手机号验证码登录、两步验证、本地 Session 恢复、自定义保存规则、下载历史，以及按按钮关键词提取原图链接。

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

首次使用前，在 [my.telegram.org](https://my.telegram.org/apps) 创建应用并获取 `API ID` 和 `API Hash`，然后在应用的“设置 -> 会话与安全”中填写凭据。二维码和手机号登录都需要这两个凭据。

## 使用说明

- 账号需要有权访问目标频道及其关联评论区。
- Tag 搜索基于 Telegram 服务端搜索，并再次检查帖子文本。
- 按钮链接在 Windows 保存为 `.url`，macOS 保存为 `.webloc`，Linux 保存为 `.desktop`。
- 配置、API 凭据与 Telethon Session 保存在操作系统的用户应用数据目录，不会写入项目目录或打进安装包。
- Windows 可使用 DPAPI 加密 Session；macOS 与 Linux 当前依赖用户目录权限保护。

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

默认构建为启动更快、运行更稳定的 `onedir`。Windows 如需单文件版本可运行 `.\build_exe.ps1 -OneFile`。

## 使用 GitHub Actions 发布

仓库包含 [`.github/workflows/release.yml`](.github/workflows/release.yml)，会在不同系统的 GitHub Runner 上分别构建，不能也不需要在本机安装另外两个操作系统。

首次发布：

```bash
git add .
git commit -m "Prepare v2.3.1 release"
git branch -M main
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
git tag v2.3.1
git push origin v2.3.1
```

推送 `v*` 标签后，在 GitHub 的 **Actions** 页面可以查看四个平台的构建进度。全部完成后，工作流会自动创建对应标签的 **Release**，并上传四个压缩包。

也可以在 **Actions -> Build release -> Run workflow** 手动构建。手动运行只生成可下载的 Actions Artifacts，不会创建正式 Release。

## 发布注意事项

- 不要提交 `tg-api.txt`、`.session`、`.env` 或任何真实 API 凭据。
- macOS 发布包当前没有 Apple Developer 签名和公证，Gatekeeper 可能提示无法验证开发者。
- Linux 当前发布便携压缩包，不是 AppImage、Flatpak 或系统安装包。
- 下载和使用内容时，请遵守目标频道规则、内容版权要求与 [Telegram API Terms](https://core.telegram.org/api/terms)。
- 本项目不是 Telegram 官方产品，也不受 Telegram 官方认可。

## 开源许可

本项目使用 [GNU GPL-3.0](LICENSE) 发布，因为开源版本使用的 PySide6-Fluent-Widgets 采用 GPL-3.0。第三方依赖说明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
