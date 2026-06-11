from __future__ import annotations

from .common import *
from .common import _UI_DIR, _asset, _divider, _img_label, _muted, _set_margins, _set_round_avatar

class HomePage(ScrollPage):
    # ── Signals（外部监听）
    new_task_requested = Signal()
    resume_task_requested = Signal()
    login_requested = Signal()
    open_folder_requested = Signal()
    history_requested = Signal()
    settings_requested = Signal()
    trend_period_changed = Signal(str)
    common_tag_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__("homePage", parent)

        # Hero 卡片
        hero = SurfaceCard()
        hero.setMinimumHeight(148)
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(6)
        tl = TitleLabel("欢迎使用 Telegram 评论区图片下载器")
        tl.setObjectName("heroTitle")
        text.addWidget(tl)
        text.addWidget(BodyLabel("基于 Telethon 的高效工具，支持从频道评论区批量下载图片，"))
        text.addWidget(BodyLabel("按 Tag 管理、智能去重、安全稳定，轻松保存精彩内容。"))
        text.addStretch()
        row.addLayout(text, 1)
        row.addWidget(_img_label("download-illustration.png", 280, 120))
        hero.body.addLayout(row)
        self.root.addWidget(hero)

        # 账号状态卡片
        self._account_card = SurfaceCard()
        acct_row = QHBoxLayout()
        acct_row.setSpacing(14)
        # 头像
        self._avatar = QLabel("●")
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setFixedSize(50, 50)
        self._avatar.setObjectName("accountAvatar")
        acct_row.addWidget(self._avatar)
        # 文字
        acct_text = QVBoxLayout()
        acct_text.setSpacing(4)
        self._acct_name = SubtitleLabel("未登录")
        self._acct_sub = _muted("当前未登录 Telethon 账号，部分功能受限")
        acct_text.addWidget(self._acct_name)
        acct_text.addWidget(self._acct_sub)
        acct_row.addLayout(acct_text, 1)
        # 安全提示
        shield_row = QHBoxLayout()
        shield_row.setSpacing(6)
        shield_ico = QLabel()
        shield_ico.setPixmap(FIF.ACCEPT.icon().pixmap(16, 16))
        shield_row.addWidget(shield_ico)
        shield_row.addWidget(_muted("所有会话数据仅保存在本地，安全加密存储"))
        acct_row.addLayout(shield_row)
        acct_row.addSpacing(16)
        self._login_btn = PrimaryPushButton("前往登录", icon=FIF.PEOPLE)
        self._login_btn.clicked.connect(self.login_requested)
        acct_row.addWidget(self._login_btn)
        self._account_card.body.addLayout(acct_row)
        self.root.addWidget(self._account_card)

        # 统计卡片行
        stat_row = QHBoxLayout()
        self._stat_today = StatCard("今日下载", "0", "张图片", FIF.DOWNLOAD)
        self._stat_total = StatCard("累计下载", "0", "张图片", FIF.ALBUM)
        self._stat_tasks = StatCard("任务总数", "0", "个任务", FIF.DOCUMENT)
        self._stat_tags = StatCard("已保存 Tag", "0", "个标签", FIF.TAG)
        self._stat_disk = StatCard("磁盘占用", "0", "B", FIF.FOLDER)
        self._stat_active = StatCard("最近活跃时间", "-", "", FIF.HISTORY)
        for c in (self._stat_today, self._stat_total, self._stat_tasks,
                  self._stat_tags, self._stat_disk, self._stat_active):
            stat_row.addWidget(c)
        self.root.addLayout(stat_row)

        # 中部三列
        mid = QHBoxLayout()
        mid.setSpacing(14)

        # 趋势图
        self._trend_card = SurfaceCard("最近 7 天下载趋势")
        # 右上角「按天」下拉
        self._period_combo = ComboBox()
        self._period_combo.addItem("按天", userData="day")
        self._period_combo.addItem("按周", userData="week")
        self._period_combo.setFixedWidth(80)
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)
        if tr := self._trend_card.title_row():
            tr.addWidget(self._period_combo)
        self._trend_chart = TrendChart()
        self._trend_card.body.addWidget(self._trend_chart)
        mid.addWidget(self._trend_card, 4)

        # 最近任务
        recent_card = SurfaceCard("最近任务")
        see_all = HyperlinkButton("", "查看全部")
        see_all.clicked.connect(self.history_requested)
        if tr := recent_card.title_row():
            tr.addWidget(see_all)
        self._recent_table = PassiveTableWidget(0, 4)
        self._recent_table.setHorizontalHeaderLabels(["任务名称", "状态", "进度", "更新时间"])
        self._recent_table.verticalHeader().hide()
        self._recent_table.horizontalHeader().setStretchLastSection(True)
        self._recent_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._recent_table.setFixedHeight(190)
        self._recent_table.setShowGrid(False)
        self._recent_table.setAlternatingRowColors(False)
        self._recent_table.setStyleSheet(
            "QTableWidget{border:none;background:transparent;}"
            "QTableWidget::item:selected,QTableWidget::item:hover{background:transparent;}"
        )
        recent_card.body.addWidget(self._recent_table)
        mid.addWidget(recent_card, 5)

        # 快速操作
        quick_card = SurfaceCard("快速操作")
        self._btn_new_task = PrimaryPushButton("  新建下载任务", icon=FIF.DOWNLOAD)
        self._btn_new_task.setFixedHeight(36)
        self._btn_new_task.clicked.connect(self.new_task_requested)
        self._btn_resume = PushButton("  继续上次任务", icon=FIF.PLAY)
        self._btn_resume.setFixedHeight(36)
        self._btn_resume.clicked.connect(self.resume_task_requested)
        self._btn_open_folder = PushButton("  打开保存目录", icon=FIF.FOLDER)
        self._btn_open_folder.setFixedHeight(36)
        self._btn_open_folder.clicked.connect(self.open_folder_requested)
        quick_card.body.addWidget(self._btn_new_task)
        quick_card.body.addWidget(self._btn_resume)
        quick_card.body.addWidget(self._btn_open_folder)
        quick_card.body.addStretch()
        mid.addWidget(quick_card, 3)
        self.root.addLayout(mid)

        # 底部三列
        foot = QHBoxLayout()
        foot.setSpacing(14)
        # 默认设置摘要
        self._summary_card = SurfaceCard("默认设置摘要")
        self._summary_path = _muted("默认保存目录：-")
        self._summary_mode = _muted("默认保存模式：-")
        self._summary_card.body.addWidget(self._summary_path)
        self._summary_card.body.addWidget(self._summary_mode)
        self._settings_btn = TransparentPushButton("前往设置", icon=FIF.SETTING)
        self._settings_btn.setMinimumHeight(36)
        self._settings_btn.clicked.connect(self.settings_requested)
        self._summary_card.body.addWidget(self._settings_btn)
        foot.addWidget(self._summary_card, 1)
        # 常用 Tag
        self._tags_card = SurfaceCard("常用 Tag")
        self._tags_row = QHBoxLayout()
        self._tags_row.setSpacing(8)
        self._tags_card.body.addLayout(self._tags_row)
        foot.addWidget(self._tags_card, 1)
        self.set_common_tags([])
        # 使用提示
        tips_card = SurfaceCard("使用提示")
        tips_card.body.addWidget(
            _muted("在 设置 中可配置默认行为、过滤规则与保存模式，让下载更符合您的需求。")
        )
        foot.addWidget(tips_card, 1)
        self.root.addLayout(foot)
        self.root.addStretch()

    # ── Setters（由外部调用）
    def set_account(self, name: str = "", phone: str = ""):
        if name:
            self._acct_name.setText(name)
            self._acct_sub.setText(f"Telethon 用户 · {phone or '本地会话已连接'}")
            self._login_btn.setText("账号详情")
        else:
            self._acct_name.setText("未登录")
            self._acct_sub.setText("当前未登录 Telethon 账号，部分功能受限")
            self._login_btn.setText("前往登录")

    def set_user_avatar(self, avatar_bytes: bytes):
        _set_round_avatar(self._avatar, avatar_bytes, 50)

    def set_summary(self, save_root: str, save_mode_label: str):
        self._summary_path.setText(f"默认保存目录：{save_root}")
        self._summary_mode.setText(f"默认保存模式：{save_mode_label}")

    def set_stats(self, today: int, total: int, tasks: int,
                  tags: int, disk_str: str, last_active: str):
        self._stat_today.set_value(str(today), "较昨日实时统计")
        self._stat_total.set_value(str(total), "累计总数")
        self._stat_tasks.set_value(str(tasks), "全部任务")
        self._stat_tags.set_value(str(tags), "自定义标签")
        self._stat_disk.set_value(disk_str, "本地存储占用")
        self._stat_active.set_value(last_active, "最近完成时间")

    def _on_period_changed(self, index: int):
        period = self._period_combo.itemData(index) or "day"
        self._trend_card.title_label.setText(
            "最近 7 周下载趋势" if period == "week" else "最近 7 天下载趋势"
        )
        self.trend_period_changed.emit(period)

    def set_trend(self, values: list[int], labels: list[str] | None = None):
        self._trend_chart.set_data(values, labels)

    def set_common_tags(self, tags: list[str]):
        while self._tags_row.count():
            item = self._tags_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._tags_card.title_label.setText(f"常用 Tag（{len(tags)}）" if tags else "常用 Tag")
        if not tags:
            self._tags_row.addWidget(_muted("暂无常用 Tag，完成带 Tag 的下载任务后会显示在这里。"))
        else:
            for tag in tags[:8]:
                text = tag if tag.startswith("#") else f"#{tag}"
                pill = TagPill(text)
                pill.clicked.connect(
                    lambda checked=False, value=tag: self.common_tag_requested.emit(value)
                )
                self._tags_row.addWidget(pill)
        self._tags_row.addStretch()

    def set_recent_tasks(self, rows: list[dict]):
        """rows: list of {name, status, progress, time}"""
        self._recent_table.setRowCount(0)
        status_colors = {
            "已完成": C_GREEN, "下载中": C_BLUE,
            "已暂停": C_ORANGE, "已取消": C_MUTED,
        }
        for rec in rows[:5]:
            r = self._recent_table.rowCount()
            self._recent_table.insertRow(r)
            # 名称
            self._recent_table.setItem(r, 0, QTableWidgetItem(rec.get("name", "-")))
            # 状态（带颜色）
            status = rec.get("status", "已完成")
            status_item = QTableWidgetItem(status)
            color = status_colors.get(status, C_MUTED)
            status_item.setForeground(QColor(color))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._recent_table.setItem(r, 1, status_item)
            # 进度（进度条 + 百分比，横向排列）
            # 进度（百分比叠加在进度条上方居中显示）
            prog = rec.get("progress", 100)
            prog_widget = QWidget()
            prog_widget.setStyleSheet("background: transparent;")
            prog_widget.setContentsMargins(0, 0, 0, 0)

            # 用 QStackedLayout 或直接 resizeEvent 叠加；这里用 QGridLayout 最简洁
            stack = QGridLayout(prog_widget)
            stack.setContentsMargins(8, 0, 8, 0)
            stack.setSpacing(0)

            bar = InlineProgress(prog)
            bar.setMinimumWidth(80)
            bar.setFixedHeight(14)

            pct_label = QLabel(f"{prog}%")
            pct_label.setStyleSheet(
                "color: white; font-size: 10px; font-weight: 600; background: transparent;"
            )
            pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            # 两者放在同一格，label 叠在 bar 上面
            stack.addWidget(bar, 0, 0)
            stack.addWidget(pct_label, 0, 0)

            self._recent_table.setCellWidget(r, 2, prog_widget)
            self._recent_table.setRowHeight(r, 40)
            # 时间
            self._recent_table.setItem(r, 3, QTableWidgetItem(rec.get("time", "-")))


# ──────────────────────────────────────────────────────────────
#  下载任务页
# ──────────────────────────────────────────────────────────────
