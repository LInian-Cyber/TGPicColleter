"""Lightweight runtime translations for the desktop UI."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractButton,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QTableWidget,
    QWidget,
)


SUPPORTED_LANGUAGES = {"zh_CN", "en_US"}

_EN = {
    "首页": "Home",
    "下载任务": "Download",
    "登录中心": "Sign in",
    "下载历史": "History",
    "设置": "Settings",
    "关于": "About",
    "切换主题": "Switch theme",
    "切换深色/浅色模式": "Switch dark/light mode",
    "Telegram 评论区图片下载器": "Telegram Comment Image Downloader",
    "欢迎使用 Telegram 评论区图片下载器": "Welcome to Telegram Comment Image Downloader",
    "基于 Telethon 的高效工具，支持从频道评论区批量下载图片，": "A fast Telethon-based tool for downloading images from channel comments.",
    "按 Tag 管理、智能去重、安全稳定，轻松保存精彩内容。": "Organize by Tag, deduplicate intelligently, and save content reliably.",
    "安全 · 稳定 · 高效": "Secure · Stable · Efficient",
    "未登录": "Not signed in",
    "已登录": "Signed in",
    "● 已登录": "● Signed in",
    "前往登录": "Sign in",
    "退出登录": "Sign out",
    "退出当前账号": "Sign out",
    "当前未登录 Telethon 账号，部分功能受限": "No Telethon account is signed in; some features are unavailable.",
    "所有会话数据仅保存在本地，安全加密存储": "All session data is encrypted and stored locally.",
    "今日下载": "Downloaded today",
    "累计下载": "Total downloads",
    "任务总数": "Tasks",
    "已保存 Tag": "Saved Tags",
    "磁盘占用": "Disk usage",
    "最近活跃时间": "Last active",
    "张图片": "images",
    "个任务": "tasks",
    "个标签": "tags",
    "最近 7 天下载趋势": "Downloads in the last 7 days",
    "最近 7 周下载趋势": "Downloads in the last 7 weeks",
    "按天": "Daily",
    "按周": "Weekly",
    "最近任务": "Recent tasks",
    "查看全部": "View all",
    "快速操作": "Quick actions",
    "新建下载任务": "New download",
    "继续上次任务": "Resume last task",
    "打开保存目录": "Open save folder",
    "默认设置摘要": "Default settings",
    "默认保存目录：-": "Default save folder: -",
    "默认保存模式：-": "Default save mode: -",
    "前往设置": "Open settings",
    "常用 Tag": "Frequent Tags",
    "暂无常用 Tag，完成带 Tag 的下载任务后会显示在这里。": "No frequent Tags yet. They will appear after a tagged download.",
    "暂无记录": "No records yet",
    "任务名称": "Task",
    "关键词": "Keyword",
    "状态": "Status",
    "进度": "Progress",
    "更新时间": "Updated",
    "操作": "Actions",
    "当前任务": "Active tasks",
    "历史记录": "History",
    "运行日志": "Logs",
    "全部暂停": "Pause all",
    "清空任务": "Clear tasks",
    "清空历史": "Clear history",
    "打开日志文件": "Open log",
    "打开日志目录": "Open log folder",
    "下载进度": "Download progress",
    "文件结果": "File results",
    "频道": "Channel",
    "匹配帖子": "Matched posts",
    "下载图片": "Downloaded images",
    "完成时间": "Completed",
    "扫描中": "Scanning",
    "下载中": "Downloading",
    "排队中": "Queued",
    "已暂停": "Paused",
    "已完成": "Completed",
    "已取消": "Cancelled",
    "继续": "Resume",
    "暂停": "Pause",
    "删除": "Delete",
    "关闭": "Close",
    "取消": "Cancel",
    "浏览": "Browse",
    "登录您的 Telegram 账号以使用全部功能": "Sign in to Telegram to use all features",
    "扫码登录（推荐）": "QR sign-in (recommended)",
    "使用 Telegram 手机端扫描二维码登录": "Scan the QR code with the Telegram mobile app",
    "请使用 Telegram 扫码登录": "Scan with Telegram",
    "刷新二维码": "Refresh QR code",
    "二维码 2 分钟内有效": "The QR code is valid for 2 minutes",
    "手机号登录": "Phone sign-in",
    "使用手机号接收验证码登录": "Sign in with a verification code sent to your phone",
    "国家 / 地区": "Country / Region",
    "手机号": "Phone number",
    "验证码": "Verification code",
    "发送验证码": "Send code",
    "两步验证密码（如已开启）": "Two-step verification password (if enabled)",
    "登录": "Sign in",
    "设备与会话信息": "Device and session",
    "当前状态": "Current status",
    "会话类型": "Session type",
    "数据存储位置": "Data location",
    "本地加密存储": "Encrypted local storage",
    "账户信息": "Account",
    "用户名": "Username",
    "请输入不含区号的手机号，或输入 + 开头完整号码": "Enter a phone number without country code, or a full number beginning with +",
    "请输入验证码": "Enter verification code",
    "请输入两步验证密码（可选）": "Enter two-step verification password (optional)",
    "设置仅在本机生效，不会上传到云端。": "Settings apply only on this device and are never uploaded.",
    "恢复默认": "Restore defaults",
    "保存设置": "Save settings",
    "常规": "General",
    "下载默认值": "Download defaults",
    "保存规则": "Save rules",
    "会话与安全": "Session & security",
    "外观": "Appearance",
    "主题模式": "Theme mode",
    "跟随系统": "Use system setting",
    "浅色": "Light",
    "深色": "Dark",
    "主题切换会立即预览，保存设置后会记住您的选择。": "Theme changes are previewed instantly and saved when you save settings.",
    "明暗主题切换当前可用，保存设置后立即生效。": "Choose a theme and save settings to apply it.",
    "界面效果 · Coming soon": "Interface effects · Coming soon",
    "语言（Language）": "Language",
    "选择界面语言，切换后立即生效。": "Choose the interface language. Changes apply instantly.",
    "简体中文": "简体中文",
    "English": "English",
    "默认保存目录": "Default save folder",
    "保存模式": "Save mode",
    "每次最多检查帖子数量": "Maximum posts checked per scan",
    "搜索预览最多展示帖子数": "Maximum posts shown in preview",
    "并发下载数量": "Concurrent downloads",
    "文件下载间隔": "Download interval",
    "文件名长度限制": "Filename length limit",
    "重复文件处理": "Duplicate file handling",
    "跳过": "Skip",
    "覆盖": "Overwrite",
    "自动重命名": "Rename automatically",
    "保留原名": "Preserve original filename",
    "文件命名规则": "Filename pattern",
    "会话存储位置": "Session storage location",
    "会话名称": "Session name",
    "系统通知": "System notifications",
    "启用系统通知": "Enable system notifications",
    "管理默认下载行为、保存规则、会话与主题外观": "Manage download defaults, save rules, sessions, and appearance",
    "应用行为": "Application behavior",
    "当前默认摘要": "Current defaults",
    "以下为当前默认设置，新建下载任务将应用这些配置。": "New download tasks will use the following defaults.",
    "并发与速率": "Concurrency & speed",
    "Tag 为空时的处理": "When Tag is empty",
    "当未识别到 Tag 时的默认处理方式。": "Default behavior when no Tag is detected.",
    "检测到同名文件时的处理策略。": "What to do when a file with the same name exists.",
    "下载完成后自动打开目录": "Open folder after download",
    "任务完成后自动打开保存目录。": "Open the save folder automatically when a task finishes.",
    "API 凭据": "API credentials",
    "API 凭据仅用于连接 Telegram，并保存在本机。": "API credentials are used only to connect to Telegram and are stored locally.",
    "未加载": "Not loaded",
    "已加载": "Loaded",
    "当前会话可正常使用。": "The current session is ready.",
    "本地会话名称": "Local session name",
    "API Hash 相当于应用密钥，请勿发送给他人。": "API Hash is an application secret. Do not share it.",
    "登出当前账号": "Sign out",
    "清理缓存": "Clear cache",
    "如何申请 Telegram API": "How to obtain Telegram API credentials",
    "二维码和手机号登录都属于第三方客户端登录，因此都需要 API ID 与 API Hash。": "QR and phone sign-in both require an API ID and API Hash for third-party clients.",
    "打开 my.telegram.org": "Open my.telegram.org",
    "启用动画效果": "Enable animations",
    "提供更流畅的界面动效体验。": "Use smoother interface animations.",
    "圆角样式": "Rounded corners",
    "使用圆角卡片与控件样式（推荐）。": "Use rounded cards and controls (recommended).",
    "按频道 / Tag 建立文件夹": "Create folders by channel / Tag",
    "按 Tag 建立文件夹": "Create folders by Tag",
    "按 Tag / 帖子建立文件夹": "Create folders by Tag / post",
    "全部保存到同一文件夹": "Save everything in one folder",
    "按每个 Tag 自动创建独立文件夹，便于分类管理。": "Create a separate folder for each Tag.",
    "该数值限制每次从频道中检查的帖子数量，不是图片数量；每篇帖子内符合条件的图片和正文原图链接都会继续处理。": "Limits the number of posts checked per scan, not the number of images. Matching images and resource links inside each post are still processed.",
    "超过该数量的匹配帖子仍会计入总数，但不会加载评论区图片和缩略图。": "Additional matched posts still count toward the total, but their comment images and thumbnails are not loaded.",
    "启动时恢复上次下载配置": "Restore the last download settings on startup",
    "应用启动时自动恢复上次会话和下载配置。": "Restore the previous session and download settings when the app starts.",
    "默认沿用上次模式": "Use the previous mode by default",
    "新建任务时自动沿用上一次使用的保存模式。": "Use the last save mode for new tasks.",
    "新建任务时自动带入最近 Tag": "Fill in the most recent Tag",
    "从最近使用的 Tag 列表中自动填充。": "Fill from the recently used Tag list.",
    "显示系统完成通知": "Show completion notifications",
    "扫描完成和下载完成时显示系统级通知。": "Show native notifications when scanning and downloading finish.",
    "并发下载数": "Concurrent downloads",
    "单个文件下载后等待（秒）": "Wait after each file (seconds)",
    "文件名长度限制": "Filename length limit",
    "保存到【未分类】文件夹": "Save to the Unsorted folder",
    "跳过该帖子": "Skip the post",
    "使用频道名作为 Tag": "Use channel name as Tag",
    "重命名": "Rename",
    "命名模板": "Filename template",
    "优先保留原文件名": "Prefer original filename",
    "媒体包含原始文件名时直接使用；Telegram 照片无原名时使用命名模板。": "Use the original media filename when available; use the template for Telegram photos.",
    "新建下载任务": "New download task",
    "默认行为来自 设置，您可在本页按需临时覆盖，上次使用的模式可一键复用。": "Defaults come from Settings. You can override them for this task or reuse the previous mode.",
    "1. 频道 / 用户名 / ID": "1. Channel / username / ID",
    "2. Tag 关键词（可选）": "2. Tag keyword (optional)",
    "3. 保存位置": "3. Save location",
    "4. 保存模式（本次下载覆盖）": "4. Save mode (task override)",
    "5. 本次下载选项（仅此生效）": "5. Download options (this task only)",
    "6. 高级提取规则（套娃深挖）": "6. Advanced extraction rule (deep traversal)",
    "当前账号": "Current account",
    "● 未登录": "● Not signed in",
    "切换账号": "Switch account",
    "搜索预览": "Search preview",
    "打开目录": "Open folder",
    "本次更改": "Task overrides",
    "仅下载图片": "Download images only",
    "跳过重复文件": "Skip duplicate files",
    "包含回复中的图片": "Include images in replies",
    "完成后打开目录": "Open folder when finished",
    "普通模式：追踪帖子正文超链接并下载原图": "Standard mode: follow post links and download source media",
    "高级规则启用时，链接追踪由高级 JSON 独立控制。": "When an advanced rule is enabled, its JSON controls link traversal.",
    "配置高级规则": "Configure advanced rules",
    "开始下载": "Start download",
    "保存为模板": "Save as template",
    "重置本次覆盖": "Reset task overrides",
    "取消任务": "Cancel task",
    "暂无运行中的任务": "No active task",
    "选择图片保存位置": "Choose image save location",
    "保存位置": "Save location",
    "文件命名": "Filename",
    "未启用 · 点击右侧按钮选择场景模板": "Disabled · Choose a scenario template",
    "正文超链接追踪规则": "Post link traversal rule",
    "高级自定义提取规则（JSON）": "Advanced extraction rule (JSON)",
    "新建自定义": "New custom rule",
    "删除自定义": "Delete custom rule",
    "格式化 JSON": "Format JSON",
    "保存当前规则": "Save current rule",
    "应用到本次下载": "Apply to this download",
    "规则列表": "Rules",
    "规则名称": "Rule name",
    "规则描述": "Rule description",
    "JSON 配置": "JSON configuration",
    "当前正在使用的规则": "Rule currently in use",
    "内置规则不能删除；可先另存为自定义规则。": "Built-in rules cannot be deleted. Save a custom copy first.",
    "暂无可用频道": "No channels available",
    "开启": "On",
    "关闭": "Off",
    "优先保留原名": "Prefer original filename",
    "任务与历史": "Tasks & history",
    "集中查看当前任务、下载记录与运行日志": "View active tasks, download history, and logs",
    "操作成功": "Success",
    "需要处理一下": "Action required",
    "提示": "Notice",
    "设置已保存": "Settings saved",
    "搜索预览": "Search preview",
    "取消搜索": "Cancel search",
    "仅预览，不保存": "Preview only, do not save",
    "正在准备搜索…": "Preparing search…",
    "搜索预览失败": "Search preview failed",
    "暂无搜索结果": "No search results",
    "没有找到匹配的帖子": "No matching posts found",
    "配置高级规则": "Configure advanced rules",
    "清除": "Clear",
    "开始下载": "Start download",
    "搜索预览结果": "Preview search results",
    "下载完成": "Download complete",
    "扫描完成": "Scan complete",
    "任务结束": "Task finished",
    "等待连接 Telegram": "Waiting for Telegram",
    "打开主界面": "Open main window",
    "暂停下载": "Pause download",
    "继续下载": "Resume download",
    "停止下载": "Stop download",
    "关闭应用": "Quit application",
}

_PREFIX_EN = {
    "默认保存目录：": "Default save folder: ",
    "默认保存模式：": "Default save mode: ",
    "保存目录": "Save folder",
    "保存模式": "Save mode",
    "文件命名规则": "Filename pattern",
    "数据中心": "Data center",
    "会话存储位置": "Session storage location",
    "帖子 #": "Post #",
    "预览：": "Preview: ",
    "已启用：": "Enabled: ",
}

_COUNTRIES = {
    "中国": "China", "中国香港": "Hong Kong, China", "中国澳门": "Macao, China",
    "中国台湾": "Taiwan, China", "美国 / 加拿大": "United States / Canada",
    "英国": "United Kingdom", "法国": "France", "德国": "Germany", "意大利": "Italy",
    "西班牙": "Spain", "葡萄牙": "Portugal", "俄罗斯": "Russia", "乌克兰": "Ukraine",
    "波兰": "Poland", "荷兰": "Netherlands", "比利时": "Belgium", "瑞士": "Switzerland",
    "奥地利": "Austria", "瑞典": "Sweden", "挪威": "Norway", "丹麦": "Denmark",
    "芬兰": "Finland", "爱尔兰": "Ireland", "冰岛": "Iceland", "捷克": "Czechia",
    "匈牙利": "Hungary", "罗马尼亚": "Romania", "希腊": "Greece", "土耳其": "Türkiye",
    "以色列": "Israel", "阿联酋": "United Arab Emirates", "沙特阿拉伯": "Saudi Arabia",
    "印度": "India", "巴基斯坦": "Pakistan", "孟加拉国": "Bangladesh",
    "斯里兰卡": "Sri Lanka", "日本": "Japan", "韩国": "South Korea", "新加坡": "Singapore",
    "马来西亚": "Malaysia", "泰国": "Thailand", "越南": "Vietnam", "菲律宾": "Philippines",
    "印度尼西亚": "Indonesia", "澳大利亚": "Australia", "新西兰": "New Zealand",
    "巴西": "Brazil", "墨西哥": "Mexico", "阿根廷": "Argentina", "智利": "Chile",
    "哥伦比亚": "Colombia", "秘鲁": "Peru", "南非": "South Africa", "埃及": "Egypt",
    "尼日利亚": "Nigeria", "肯尼亚": "Kenya",
}


def translate(text: str, lang: str) -> str:
    """Translate a UI string while leaving user-provided content untouched."""
    if lang != "en_US" or not text:
        return text
    stripped = text.strip()
    translated = _EN.get(stripped)
    if translated is not None:
        return text.replace(stripped, translated, 1)
    for source, target in _PREFIX_EN.items():
        if stripped.startswith(source):
            return text.replace(source, target, 1)
    for source, target in sorted(_COUNTRIES.items(), key=lambda item: len(item[0]), reverse=True):
        if source in stripped and stripped.startswith("🌐"):
            return text.replace(source, target, 1)
    return text


def _translated_source(obj, property_name: str, current: str, lang: str) -> str:
    source_property = f"_i18n_{property_name}"
    source = obj.property(source_property)
    if not isinstance(source, str):
        source = current
        obj.setProperty(source_property, source)
    else:
        if current not in {source, translate(source, "en_US")}:
            source = current
            obj.setProperty(source_property, source)
    return translate(source, lang)


def apply_language(root: QWidget, lang: str) -> None:
    """Retranslate the existing widget tree without rebuilding the window."""
    lang = lang if lang in SUPPORTED_LANGUAGES else "zh_CN"
    objects = [root, *root.findChildren(QWidget), *root.findChildren(QAction)]
    for obj in objects:
        if isinstance(obj, (QLabel, QAbstractButton, QAction)):
            current = obj.text()
            obj.setText(_translated_source(obj, "text", current, lang))
        elif (
            not isinstance(obj, (QLineEdit, QPlainTextEdit))
            and hasattr(obj, "text")
            and hasattr(obj, "setText")
        ):
            try:
                current = obj.text()
                if obj.property("_i18n_text") is not None or translate(current, "en_US") != current:
                    obj.setText(_translated_source(obj, "text", current, lang))
            except (AttributeError, RuntimeError, TypeError):
                pass

        if isinstance(obj, (QLineEdit, QPlainTextEdit)):
            current = obj.placeholderText()
            obj.setPlaceholderText(
                _translated_source(obj, "placeholder", current, lang)
            )

        if isinstance(obj, QWidget):
            title = obj.windowTitle()
            if title:
                obj.setWindowTitle(_translated_source(obj, "title", title, lang))
            tooltip = obj.toolTip()
            if tooltip:
                obj.setToolTip(_translated_source(obj, "tooltip", tooltip, lang))

        if hasattr(obj, "count") and hasattr(obj, "itemText") and hasattr(obj, "setItemText"):
            try:
                for index in range(obj.count()):
                    current = obj.itemText(index)
                    key = f"item_{index}"
                    obj.setItemText(index, _translated_source(obj, key, current, lang))
            except (AttributeError, RuntimeError, TypeError):
                pass

        if isinstance(obj, QTableWidget):
            for column in range(obj.columnCount()):
                item = obj.horizontalHeaderItem(column)
                if item is None:
                    continue
                source = item.data(Qt.ItemDataRole.UserRole)
                if not isinstance(source, str):
                    source = item.text()
                    item.setData(Qt.ItemDataRole.UserRole, source)
                item.setText(translate(source, lang))
