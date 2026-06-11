# TG Pic Collector

一个使用 Telethon、PySide6 与 PySide6-Fluent-Widgets 编写的桌面工具。它会按标签搜索频道帖子，遍历帖子的评论区，并下载其中的图片。

应用包含首页仪表盘、下载任务、登录中心、下载历史、设置与关于页面，支持扫码登录、手机号验证码登录、两步验证和本地 Session 恢复。

## 启动

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

首次使用前，在 [my.telegram.org](https://my.telegram.org) 创建应用并获取 `API ID` 和 `API Hash`，然后在应用的“设置 → 会话与安全”中填写凭据。保存设置后，可在“登录中心”扫码或使用手机号登录。

## 说明

- 账号需要有权访问目标频道及其关联评论区。
- 标签搜索基于 Telegram 服务端搜索，并再次检查帖子文本是否包含标签。
- 可按自定义按钮关键词提取频道帖子底部的 URL，并保存为可双击打开的 `.url` 快捷方式。
- 已存在的同名图片会自动跳过。
- 会话和配置保存在操作系统的应用配置目录，不会写入项目目录。
- 请遵守目标频道规则、版权要求与 Telegram 使用条款。

## 基础测试

```powershell
.\.venv\Scripts\python.exe -m unittest
```

## 打包 Windows EXE

推荐构建为 `onedir`，启动速度更快、运行更稳定：

```powershell
.\build_exe.ps1
```

输出位置：`dist\TG Pic Collector\TG Pic Collector.exe`

如需单文件版本：

```powershell
.\build_exe.ps1 -OneFile
```

单文件版本首次启动会先解压运行资源，因此速度会稍慢。应用配置、API 凭据与 Telethon Session 不会打进 EXE，仍保存在当前 Windows 用户的应用配置目录中。

发布给其他用户前，请确认遵守 PySide6、QFluentWidgets、Telethon 及其他依赖的许可证要求。
