from __future__ import annotations

import sys
from pathlib import Path

from ..config import (
    DEFAULT_CHUNK_CONCURRENCY,
    DEFAULT_CONCURRENCY,
    DEFAULT_FILE_DOWNLOAD_INTERVAL,
    DEFAULT_FILENAME_LIMIT,
    DEFAULT_MAX_POSTS,
    DEFAULT_PREVIEW_MAX_RESULTS,
    DEFAULT_SAVE_ROOT,
)
from ..network import proxy_label, yande_proxy_warning
from .common import *
from .common import _UI_DIR, _asset, _divider, _img_label, _muted, _set_margins

class SettingsPage(ScrollPage):
    save_requested = Signal(dict)   # emit settings dict
    network_test_requested = Signal(dict)
    data_dir_open_requested = Signal()
    logout_requested = Signal()
    cache_clear_requested = Signal()
    language_preview_requested = Signal(str)
    channel_cache_refresh_requested = Signal()
    channel_cache_delete_requested = Signal(str)
    channel_cache_clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("settingsPage", parent)
        self._page_header("设置", "管理默认下载行为、保存规则、会话与主题外观",
                          illus="settings-illustration.png", illus_w=260, illus_h=100)

        # Tab 切换（真实 SegmentedWidget）
        self._seg = SegmentedWidget()
        self._stack = QStackedWidget()
        tabs = [
            ("常规", self._build_general()),
            ("下载默认值", self._build_download_defaults()),
            ("保存规则", self._build_save_rules()),
            ("会话与安全", self._build_session()),
            ("外观", self._build_appearance()),
        ]
        for i, (name, widget) in enumerate(tabs):
            self._stack.addWidget(widget)
            self._seg.addItem(
                routeKey=f"tab_{i}",
                text=name,
                onClick=lambda checked=False, idx=i: self._stack.setCurrentIndex(idx),
            )
        self._seg.setCurrentItem("tab_0")
        self.root.addWidget(self._seg)
        self._stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._stack.currentChanged.connect(self.refresh_layout)
        self.root.addWidget(self._stack)
        QTimer.singleShot(0, self.refresh_layout)

        # 底部操作栏
        foot = SurfaceCard()
        foot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        foot_row = QHBoxLayout()
        foot_row.addWidget(_muted("ⓘ  设置仅在本机生效，不会上传到云端。"))
        foot_row.addStretch()

        restore_btn = PushButton("恢复默认", icon=FIF.RETURN)
        restore_btn.clicked.connect(self._restore_defaults)

        save_btn = PrimaryPushButton("保存设置", icon=FIF.SAVE)
        save_btn.clicked.connect(self._on_save)

        # ✨ 统一将两个按钮的尺寸设置为相同的最小宽高（例如宽 140，高 36）
        for button in (restore_btn, save_btn):
            button.setMinimumSize(140, 36)

        foot_row.addWidget(restore_btn)
        foot_row.addWidget(save_btn)
        foot.body.addLayout(foot_row)
        self.root.addWidget(foot, 0, Qt.AlignmentFlag.AlignTop)

    def _sync_stack_height(self, *_):
        stack = getattr(self, "_stack", None)
        if stack is None:
            return
        page = stack.currentWidget()
        if page is None:
            return
        width = max(1, stack.width())
        layout = page.layout()
        if layout is not None:
            layout.activate()
        heights = [page.sizeHint().height(), page.minimumSizeHint().height(), 1]
        if layout is not None:
            heights.append(layout.sizeHint().height())
            if layout.hasHeightForWidth() and width > 1:
                heights.append(layout.heightForWidth(width))
        height = max(heights)
        if stack.minimumHeight() == height and stack.maximumHeight() == height:
            return
        stack.setMinimumHeight(height)
        stack.setMaximumHeight(height)
        stack.updateGeometry()
        self._content.updateGeometry()

    def refresh_layout(self, *_):
        self._sync_stack_height()
        QTimer.singleShot(0, self._sync_stack_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_stack"):
            self.refresh_layout()

    # ── Tab 页面构建
    def _build_general(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        _set_margins(layout, (0, 12, 0, 0), 14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 2)

        # 下载默认值
        dl = SurfaceCard("下载默认值")
        dl.body.addWidget(StrongBodyLabel("默认保存目录"))
        path_row = QHBoxLayout()
        self.path_edit = LineEdit()
        browse_btn = PushButton("浏览", icon=FIF.FOLDER)
        browse_btn.clicked.connect(self._choose_dir)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_btn)
        dl.body.addLayout(path_row)
        dl.body.addWidget(StrongBodyLabel("默认保存模式"))
        self.mode_combo = ComboBox()
        for text, key in [
            ("按频道 / Tag 建立文件夹", "channel_tag"),
            ("按 Tag 建立文件夹", "tag"),
            ("按 Tag / 帖子建立文件夹", "post"),
            ("全部保存到同一文件夹", "flat"),
        ]:
            self.mode_combo.addItem(text, userData=key)
        dl.body.addWidget(self.mode_combo)
        self._save_mode_preview_lbl = _muted("")
        dl.body.addWidget(self._save_mode_preview_lbl)
        self.path_edit.textChanged.connect(self._update_save_mode_preview)
        self.mode_combo.currentIndexChanged.connect(self._update_save_mode_preview)
        dl.body.addWidget(_muted("按每个 Tag 自动创建独立文件夹，便于分类管理。"))
        dl.body.addWidget(StrongBodyLabel("每次最多匹配帖子数量"))
        self.max_posts = SpinBox()
        self.max_posts.setRange(1, 5000)
        self.max_posts.setValue(DEFAULT_MAX_POSTS)
        self.max_posts.setMinimumSize(180, 36)
        dl.body.addWidget(self.max_posts)
        dl.body.addWidget(_muted(
            "该数值限制每次任务最多处理的匹配帖子数量，不是图片数量；"
            "每篇帖子内符合条件的图片和正文原图链接都会继续处理。"
        ))
        dl.body.addWidget(StrongBodyLabel("搜索预览最多展示帖子数"))
        self.preview_max_results = SpinBox()
        self.preview_max_results.setRange(10, 500)
        self.preview_max_results.setValue(DEFAULT_PREVIEW_MAX_RESULTS)
        self.preview_max_results.setMinimumSize(180, 36)
        dl.body.addWidget(self.preview_max_results)
        dl.body.addWidget(_muted(
            "超过该数量的匹配帖子仍会计入总数，但不会加载评论区图片和缩略图。"
        ))
        grid.addWidget(dl, 0, 0)

        # 启动行为
        launch = SurfaceCard("应用行为")
        for label, desc, attr in [
            ("启动时恢复上次下载配置", "应用启动时自动恢复上次会话和下载配置。", "restore_cb"),
            ("默认沿用上次模式", "新建任务时自动沿用上一次使用的保存模式。", "last_mode_cb"),
            ("新建任务时自动带入最近 Tag", "从最近使用的 Tag 列表中自动填充。", "auto_tag_cb"),
            ("显示系统完成通知", "扫描完成和下载完成时显示系统级通知。", "notification_sw"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(12)
            text_v = QVBoxLayout()
            text_v.setSpacing(2)
            text_v.addWidget(StrongBodyLabel(label))
            text_v.addWidget(_muted(desc))
            row.addLayout(text_v, 1)
            sw = SwitchButton()
            sw.setChecked(True)
            setattr(self, attr, sw)
            row.addWidget(sw)
            launch.body.addLayout(row)
            launch.body.addWidget(_divider())
        launch.body.addWidget(StrongBodyLabel("点击窗口关闭按钮时"))
        close_behavior_row = QHBoxLayout()
        close_behavior_row.setSpacing(18)
        self._close_behavior_radios: dict[str, RadioButton] = {}
        for text, key in [
            ("首次询问", "ask"),
            ("最小化到托盘", "minimize"),
            ("退出应用", "exit"),
        ]:
            rb = RadioButton(text)
            self._close_behavior_radios[key] = rb
            close_behavior_row.addWidget(rb)
        close_behavior_row.addStretch()
        self._close_behavior_radios["ask"].setChecked(True)
        launch.body.addLayout(close_behavior_row)

        launch.body.addWidget(_muted("当选择“首次询问”时，弹窗内也可以决定是否记住本次选择。"))
        close_remember_row = QHBoxLayout()
        close_remember_row.setSpacing(18)
        self._close_remember_radios: dict[bool, RadioButton] = {}
        for text, key in [("记住选择", True), ("仅本次", False)]:
            rb = RadioButton(text)
            self._close_remember_radios[key] = rb
            close_remember_row.addWidget(rb)
        close_remember_row.addStretch()
        self._close_remember_radios[False].setChecked(True)
        launch.body.addLayout(close_remember_row)
        grid.addWidget(launch, 0, 1)

        # 当前默认摘要（右侧固定列）
        self._summary_side = SurfaceCard("当前默认摘要", "以下为当前默认设置，新建下载任务将应用这些配置。")
        self._summary_path_lbl = _muted("保存目录\n-")
        self._summary_mode_lbl = _muted("保存模式\n-")
        self._summary_dup_lbl = _muted("重复文件处理\n-")
        self._summary_fn_lbl = _muted("文件命名规则\n-")
        for lbl in (self._summary_path_lbl, self._summary_mode_lbl,
                    self._summary_dup_lbl, self._summary_fn_lbl):
            self._summary_side.body.addWidget(lbl)
        self._summary_side.body.addStretch()
        grid.addWidget(self._summary_side, 0, 2, 3, 1)

        layout.addLayout(grid)
        return w

    def _build_download_defaults(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        _set_margins(layout, (0, 12, 0, 0), 14)
        card = SurfaceCard("并发与速率")
        card.body.addWidget(StrongBodyLabel("并发下载数"))
        self.concurrency_spin = SpinBox()
        self.concurrency_spin.setRange(1, 20)
        self.concurrency_spin.setValue(DEFAULT_CONCURRENCY)
        self.concurrency_spin.setMinimumSize(140, 36)
        card.body.addWidget(self.concurrency_spin)
        card.body.addWidget(StrongBodyLabel("Telegram 单文件分片数"))
        self.chunk_concurrency_spin = SpinBox()
        self.chunk_concurrency_spin.setRange(1, 8)
        self.chunk_concurrency_spin.setValue(DEFAULT_CHUNK_CONCURRENCY)
        self.chunk_concurrency_spin.setMinimumSize(140, 36)
        self.chunk_concurrency_spin.setToolTip("大文件可尝试 2-4；不稳定或限流时保持 1。")
        card.body.addWidget(self.chunk_concurrency_spin)
        card.body.addWidget(StrongBodyLabel("单个文件下载后等待（秒）"))
        self.interval_spin = DoubleSpinBox()
        self.interval_spin.setRange(0, 10)
        self.interval_spin.setSingleStep(0.1)
        self.interval_spin.setDecimals(1)
        self.interval_spin.setValue(DEFAULT_FILE_DOWNLOAD_INTERVAL)
        self.interval_spin.setMinimumSize(140, 36)
        card.body.addWidget(self.interval_spin)
        card.body.addWidget(_muted(
            "该间隔用于每个媒体文件下载后的冷却；Telegram 搜索、读取帖子等请求不使用此间隔。"
        ))
        card.body.addWidget(StrongBodyLabel("文件名长度限制"))
        self.fn_len_spin = SpinBox()
        self.fn_len_spin.setRange(20, 255)
        self.fn_len_spin.setValue(DEFAULT_FILENAME_LIMIT)
        self.fn_len_spin.setMinimumSize(140, 36)
        card.body.addWidget(self.fn_len_spin)
        layout.addWidget(card)
        layout.addStretch()
        return w

    def _build_save_rules(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        _set_margins(layout, (0, 12, 0, 0), 14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        # Tag 为空时处理
        tag_empty = SurfaceCard("Tag 为空时的处理", "当未识别到 Tag 时的默认处理方式。")
        self.tag_empty_combo = ComboBox()
        for text, key in [
            ("保存到【未分类】文件夹", "uncategorized"),
            ("跳过该帖子", "skip"),
            ("使用频道名作为 Tag", "channel"),
        ]:
            self.tag_empty_combo.addItem(text, userData=key)
        tag_empty.body.addWidget(self.tag_empty_combo)
        grid.addWidget(tag_empty, 0, 0)

        # 重复文件处理
        dup = SurfaceCard("重复文件处理", "检测到同名文件时的处理策略。")
        dup_row = QHBoxLayout()
        self._dup_radios: dict[str, RadioButton] = {}
        for text, key in [("跳过", "skip"), ("覆盖", "overwrite"), ("重命名", "rename")]:
            rb = RadioButton(text)
            self._dup_radios[key] = rb
            dup_row.addWidget(rb)
        dup_row.addStretch()
        self._dup_radios["skip"].setChecked(True)
        dup.body.addLayout(dup_row)
        grid.addWidget(dup, 0, 1)

        # 文件命名规则
        fn = SurfaceCard("文件命名规则")
        fn.body.addWidget(StrongBodyLabel("命名模板"))
        self.filename_edit = LineEdit()
        self.filename_edit.setPlaceholderText("{tag}/{date}/{index}_{id}.{ext}")
        self.filename_edit.setText("{tag}/{date}/{index}_{id}.{ext}")
        fn.body.addWidget(self.filename_edit)
        preserve_row = QHBoxLayout()
        preserve_text = QVBoxLayout()
        preserve_text.addWidget(StrongBodyLabel("优先保留原文件名"))
        preserve_text.addWidget(_muted("媒体包含原始文件名时直接使用；Telegram 照片无原名时使用命名模板。"))
        preserve_row.addLayout(preserve_text, 1)
        self.preserve_original_sw = SwitchButton()
        self.preserve_original_sw.setChecked(True)
        preserve_row.addWidget(self.preserve_original_sw)
        fn.body.addLayout(preserve_row)
        preview_row = QHBoxLayout()
        self._filename_preview_lbl = _muted("预览：旅行/20260610_190654_5678.jpg")
        preview_row.addWidget(self._filename_preview_lbl)
        preview_btn = PushButton("预览", icon=FIF.VIEW)
        # ✨ 取消写死的 70 宽度，改为最小宽度 90（或者 100），高度统一为 36
        preview_btn.setMinimumSize(90, 36)
        preview_btn.clicked.connect(self._preview_filename)
        preview_row.addWidget(preview_btn)
        fn.body.addLayout(preview_row)
        grid.addWidget(fn, 1, 0)

        # 完成后自动打开
        auto_open = SurfaceCard("下载完成后自动打开目录", "任务完成后自动打开保存目录。")
        ao_row = QHBoxLayout()
        self.auto_open_sw = SwitchButton()
        self.auto_open_sw.setChecked(True)
        ao_row.addWidget(self.auto_open_sw)
        ao_row.addStretch()
        auto_open.body.addLayout(ao_row)
        grid.addWidget(auto_open, 1, 1)

        layout.addLayout(grid)
        layout.addStretch()
        return w

    def _build_session(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        _set_margins(layout, (0, 12, 0, 0), 14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 1)

        # API 凭据
        api_card = SurfaceCard("API 凭据", "API 凭据仅用于连接 Telegram，并保存在本机。")
        self._session_loaded_badge = QLabel(" 未加载 ")
        # ✨ 新增：强制对齐和最小尺寸，防止文字被切割
        self._session_loaded_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._session_loaded_badge.setMinimumSize(64, 26)

        self._session_loaded_badge.setStyleSheet(
            "background:#e53935;color:white;border-radius:13px;font-size:12px;font-weight:bold;"
        )
        if tr := api_card.title_row():
            tr.addWidget(self._session_loaded_badge)
        self._session_status_label = BodyLabel("当前会话可正常使用。")
        api_card.body.addWidget(self._session_status_label)

        api_card.body.addWidget(StrongBodyLabel("API ID"))
        self.api_id_edit = LineEdit()
        self.api_id_edit.setPlaceholderText("API ID（从 my.telegram.org 获取）")
        api_card.body.addWidget(self.api_id_edit)

        api_card.body.addWidget(StrongBodyLabel("API Hash"))
        self.api_hash_edit = PasswordLineEdit()
        self.api_hash_edit.setPlaceholderText("API Hash")
        api_card.body.addWidget(self.api_hash_edit)

        api_card.body.addWidget(StrongBodyLabel("本地会话名称"))
        self.session_edit = LineEdit()
        self.session_edit.setPlaceholderText("default")
        api_card.body.addWidget(self.session_edit)

        api_card.body.addWidget(StrongBodyLabel("会话存储位置"))
        sess_path_row = QHBoxLayout()
        self.session_path_edit = LineEdit()
        sess_path_row.addWidget(self.session_path_edit, 1)
        browse_s = PushButton("浏览", icon=FIF.FOLDER)
        browse_s.clicked.connect(self._choose_session_dir)
        sess_path_row.addWidget(browse_s)
        api_card.body.addLayout(sess_path_row)

        enc_row = QHBoxLayout()
        enc_row.addWidget(StrongBodyLabel("本地加密存储"))
        enc_row.addStretch()
        self.encrypt_sw = SwitchButton()
        self.encrypt_sw.setChecked(sys.platform == "win32")
        self.encrypt_sw.setEnabled(sys.platform == "win32")
        enc_row.addWidget(self.encrypt_sw)
        api_card.body.addLayout(enc_row)
        encryption_note = (
            "使用 Windows DPAPI 加密存储会话文件。"
            if sys.platform == "win32"
            else "当前系统不支持 Windows DPAPI，会话文件由当前用户目录权限保护。"
        )
        api_card.body.addWidget(_muted(encryption_note))

        proxy_card = SurfaceCard("网络代理", "用于 Telegram 连接和 Yande 网络请求，避免必须开启网卡/TUN 全局代理。")
        proxy_row = QHBoxLayout()
        proxy_text = QVBoxLayout()
        proxy_text.setSpacing(2)
        proxy_text.addWidget(StrongBodyLabel("自动读取系统代理"))
        proxy_text.addWidget(_muted("开启后会读取系统或环境变量中的 HTTP/HTTPS/ALL_PROXY。"))
        proxy_row.addLayout(proxy_text, 1)
        self.use_system_proxy_sw = SwitchButton()
        self.use_system_proxy_sw.setChecked(True)
        proxy_row.addWidget(self.use_system_proxy_sw)
        proxy_card.body.addLayout(proxy_row)

        proxy_card.body.addWidget(StrongBodyLabel("自定义代理地址（可选）"))
        self.proxy_url_edit = LineEdit()
        self.proxy_url_edit.setPlaceholderText("例如：http://127.0.0.1:7890 或 socks5://127.0.0.1:7890")
        proxy_card.body.addWidget(self.proxy_url_edit)
        proxy_card.body.addWidget(_muted(
            "Telegram 支持 HTTP/SOCKS 代理；Yande 下载建议填写 HTTP 或 mixed 端口。"
        ))
        self._proxy_preview_lbl = _muted("")
        proxy_card.body.addWidget(self._proxy_preview_lbl)
        proxy_actions = QHBoxLayout()
        proxy_actions.addStretch()
        test_proxy_btn = PushButton("测试网络代理", icon=FIF.SYNC)
        test_proxy_btn.setMinimumHeight(36)
        test_proxy_btn.clicked.connect(lambda: self.network_test_requested.emit(self._collect()))
        proxy_actions.addWidget(test_proxy_btn)
        proxy_card.body.addLayout(proxy_actions)
        self.proxy_url_edit.textChanged.connect(self._update_proxy_preview)
        try:
            self.use_system_proxy_sw.checkedChanged.connect(self._update_proxy_preview)
        except AttributeError:
            self.use_system_proxy_sw.toggled.connect(self._update_proxy_preview)
        self._update_proxy_preview()
        api_card.body.addWidget(proxy_card)

        ops_row = QHBoxLayout()

        logout_btn = PushButton("登出当前账号", icon=FIF.POWER_BUTTON)
        logout_btn.clicked.connect(self.logout_requested)

        cache_btn = PushButton("清理缓存", icon=FIF.DELETE)
        cache_btn.clicked.connect(self.cache_clear_requested)

        data_dir_btn = PushButton("打开本地数据目录", icon=FIF.FOLDER)
        data_dir_btn.clicked.connect(self.data_dir_open_requested)

        # ✨ 1. 统一将两个按钮的尺寸设置为相同的最小宽高（宽 140，高 36）
        # ✨ 2. 删除了原有的 setStyleSheet("color:#e53935;")，恢复原生的高级质感与交互反馈
        for button in (logout_btn, cache_btn, data_dir_btn):
            button.setMinimumSize(140, 36)

        ops_row.addWidget(logout_btn)
        ops_row.addWidget(cache_btn)
        ops_row.addWidget(data_dir_btn)
        ops_row.addStretch()
        api_card.body.addLayout(ops_row)
        grid.addWidget(api_card, 0, 0, 1, 2)

        guide_card = SurfaceCard(
            "如何申请 Telegram API",
            "二维码和手机号登录都属于第三方客户端登录，因此都需要 API ID 与 API Hash。",
        )
        for step in [
            "1. 打开 my.telegram.org，使用 Telegram 手机号登录。",
            "2. 输入 Telegram 客户端收到的验证码。",
            "3. 进入 API development tools。",
            "4. 填写 App title 与 Short name，提交创建应用。",
            "5. 将 App api_id 和 App api_hash 填到左侧并保存。",
        ]:
            guide_card.body.addWidget(_muted(step))
        guide_card.body.addWidget(_divider())
        guide_card.body.addWidget(_muted(
            "申请 API ID / API Hash 时请使用家宽或手机流量等真实网络；代理、机房或机场节点可能无法创建应用。"
        ))
        guide_card.body.addWidget(_muted("API Hash 相当于应用密钥，请勿发送给他人。"))
        api_link = HyperlinkButton(
            "https://my.telegram.org/apps",
            "打开 my.telegram.org",
            icon=FIF.LINK,
        )
        api_link.setMinimumHeight(36)
        guide_card.body.addWidget(api_link)
        guide_card.body.addStretch()
        grid.addWidget(guide_card, 0, 2)

        layout.addLayout(grid)
        cache_card = SurfaceCard("频道缓存", "缓存最近搜索/加载到的频道名称、头像和链接；可手动刷新或删除。")
        cache_actions = QHBoxLayout()
        cache_actions.addWidget(_muted("粘贴 t.me/c/.../123 时会自动识别频道部分并写入缓存。"))
        cache_actions.addStretch()
        refresh_btn = PushButton("刷新频道信息", icon=FIF.SYNC)
        clear_btn = PushButton("清空频道缓存", icon=FIF.DELETE)
        refresh_btn.clicked.connect(self.channel_cache_refresh_requested)
        clear_btn.clicked.connect(self.channel_cache_clear_requested)
        cache_actions.addWidget(refresh_btn)
        cache_actions.addWidget(clear_btn)
        cache_card.body.addLayout(cache_actions)

        self._channel_cache_table = PassiveTableWidget(0, 4)
        self._channel_cache_table.setHorizontalHeaderLabels(["名称", "频道/ID", "链接", "操作"])
        self._channel_cache_table.verticalHeader().hide()
        self._channel_cache_table.horizontalHeader().setStretchLastSection(False)
        self._channel_cache_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._channel_cache_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._channel_cache_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._channel_cache_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._channel_cache_table.setColumnWidth(3, 72)
        self._channel_cache_table.setMinimumHeight(220)
        self._channel_cache_table.setShowGrid(False)
        self._channel_cache_table.setAlternatingRowColors(False)
        self._channel_cache_table.refresh_theme()
        cache_card.body.addWidget(self._channel_cache_table)
        layout.addWidget(cache_card)
        layout.addStretch()
        return w

    def _build_appearance(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        _set_margins(layout, (0, 12, 0, 0), 14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        # 主题
        theme_card = SurfaceCard("主题模式")
        theme_row = QHBoxLayout()
        self._theme_radios: dict[str, RadioButton] = {}
        for text, key in [("跟随系统", "auto"), ("浅色", "light"), ("深色", "dark")]:
            rb = RadioButton(text)
            self._theme_radios[key] = rb
            theme_row.addWidget(rb)
        theme_row.addStretch()
        self._theme_radios["auto"].setChecked(True)
        theme_card.body.addLayout(theme_row)
        theme_card.body.addWidget(_muted("明暗主题切换当前可用，保存设置后立即生效。"))
        grid.addWidget(theme_card, 0, 0)

        # 动画与圆角
        anim_card = SurfaceCard(
            "界面效果 · Coming soon",
            "动画和圆角风格切换仍在开发中，当前使用应用默认样式。",
        )
        for label, desc, attr in [
            ("启用动画效果", "提供更流畅的界面动效体验。", "anim_sw"),
            ("圆角样式", "使用圆角卡片与控件样式（推荐）。", "round_sw"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(12)
            text_v = QVBoxLayout()
            text_v.setSpacing(2)
            text_v.addWidget(StrongBodyLabel(label))
            text_v.addWidget(_muted(desc))
            row.addLayout(text_v, 1)
            sw = SwitchButton()
            sw.setChecked(True)
            sw.setEnabled(False)
            setattr(self, attr, sw)
            row.addWidget(sw)
            anim_card.body.addLayout(row)
            anim_card.body.addWidget(_divider())
        grid.addWidget(anim_card, 0, 1)

        # 语言
        lang_card = SurfaceCard("语言（Language）", "选择界面语言，切换后立即生效。")
        self.lang_combo = ComboBox()
        self.lang_combo.addItem("简体中文", userData="zh_CN")
        self.lang_combo.addItem("English", userData="en_US")
        self.lang_combo.currentIndexChanged.connect(
            lambda: self.language_preview_requested.emit(
                self.lang_combo.currentData() or "zh_CN"
            )
        )
        lang_card.body.addWidget(self.lang_combo)
        grid.addWidget(lang_card, 1, 0)

        # 预览图
        preview_card = SurfaceCard()
        preview_card.body.addWidget(
            _img_label("download-illustration.png", 260, 160),
            alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid.addWidget(preview_card, 1, 1)

        layout.addLayout(grid)
        layout.addStretch()
        return w

    def _update_save_mode_preview(self):
        root_text = self.path_edit.text().strip() or DEFAULT_SAVE_ROOT
        mode = self.mode_combo.currentData() or "channel_tag"
        root = Path(root_text)
        examples = {
            "channel_tag": root / "示例频道" / "Nicole" / "20260617_post1024.jpg",
            "tag": root / "Nicole" / "20260617_post1024.jpg",
            "post": root / "Nicole" / "post_1024" / "20260617_post1024.jpg",
            "flat": root / "20260617_post1024.jpg",
        }
        path = examples.get(mode, examples["channel_tag"])
        if hasattr(self, "_save_mode_preview_lbl"):
            self._save_mode_preview_lbl.setText(f"示例保存路径：{path}")

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择默认保存目录", self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def _choose_session_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择会话存储位置")
        if d:
            self.session_path_edit.setText(d)

    def _update_proxy_preview(self, *_):
        if not hasattr(self, "_proxy_preview_lbl"):
            return
        proxy_url = self.proxy_url_edit.text().strip()
        use_system = self.use_system_proxy_sw.isChecked()
        try:
            telegram = proxy_label(proxy_url, use_system, "telegram")
            yande = proxy_label(proxy_url, use_system, "http")
            warning = yande_proxy_warning(proxy_url, use_system)
            text = f"当前实际代理：Telegram {telegram}；Yande {yande}"
            if warning:
                text += f"\n{warning}"
        except ValueError as exc:
            text = f"代理配置有误：{exc}"
        self._proxy_preview_lbl.setText(text)

    def _on_save(self):
        self.save_requested.emit(self._collect())

    def _preview_filename(self):
        template = self.filename_edit.text().strip()
        try:
            result = template.format(
                tag="旅行",
                date="20260610_190654",
                post_id="1024",
                comment_id="5678",
                index="5678",
                id="5678",
                ext="jpg",
            )
            self._filename_preview_lbl.setText(f"预览：{result}")
        except (KeyError, ValueError, IndexError):
            self._filename_preview_lbl.setText("预览：格式错误，请检查模板变量")

    def _restore_defaults(self):
        self.path_edit.setText(DEFAULT_SAVE_ROOT)
        self.max_posts.setValue(DEFAULT_MAX_POSTS)
        self.preview_max_results.setValue(DEFAULT_PREVIEW_MAX_RESULTS)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData("channel_tag")))
        self.preserve_original_sw.setChecked(True)
        self.concurrency_spin.setValue(DEFAULT_CONCURRENCY)
        self.chunk_concurrency_spin.setValue(DEFAULT_CHUNK_CONCURRENCY)
        self.interval_spin.setValue(DEFAULT_FILE_DOWNLOAD_INTERVAL)
        self.fn_len_spin.setValue(DEFAULT_FILENAME_LIMIT)
        self.tag_empty_combo.setCurrentIndex(
            max(0, self.tag_empty_combo.findData("uncategorized"))
        )
        self.restore_cb.setChecked(True)
        self.last_mode_cb.setChecked(True)
        self.auto_tag_cb.setChecked(True)
        self.notification_sw.setChecked(True)
        self._close_behavior_radios["ask"].setChecked(True)
        self._close_remember_radios[False].setChecked(True)
        self.use_system_proxy_sw.setChecked(True)
        self.proxy_url_edit.clear()

    def _collect(self) -> dict:
        mode = self.mode_combo.currentData() or "channel_tag"
        dup = next((k for k, rb in self._dup_radios.items() if rb.isChecked()), "skip")
        theme = next((k for k, rb in self._theme_radios.items() if rb.isChecked()), "auto")
        return {
            "save_root": self.path_edit.text().strip(),
            "save_mode": mode,
            "max_posts": self.max_posts.value(),
            "preview_max_results": self.preview_max_results.value(),
            "concurrency": self.concurrency_spin.value(),
            "chunk_concurrency": self.chunk_concurrency_spin.value(),
            "file_download_interval": float(self.interval_spin.value()),
            "filename_limit": self.fn_len_spin.value(),
            "empty_tag_action": self.tag_empty_combo.currentData() or "uncategorized",
            "restore_on_launch": self.restore_cb.isChecked(),
            "use_last_mode": self.last_mode_cb.isChecked(),
            "auto_fill_tag": self.auto_tag_cb.isChecked(),
            "enable_system_notifications": self.notification_sw.isChecked(),
            "close_behavior": next(
                (key for key, rb in self._close_behavior_radios.items() if rb.isChecked()),
                "ask",
            ),
            "remember_close_behavior": self._close_remember_radios[True].isChecked(),
            "skip_duplicates": dup,
            "filename_template": self.filename_edit.text().strip(),
            "preserve_original_name": self.preserve_original_sw.isChecked(),
            "api_id": self.api_id_edit.text().strip(),
            "api_hash": self.api_hash_edit.text().strip(),
            "session_name": self.session_edit.text().strip() or "default",
            "session_path": self.session_path_edit.text().strip(),
            "use_system_proxy": self.use_system_proxy_sw.isChecked(),
            "proxy_url": self.proxy_url_edit.text().strip(),
            "theme_mode": theme,
            "lang": self.lang_combo.currentData() or "zh_CN",
            "open_after_download": self.auto_open_sw.isChecked(),
            "use_dpapi_encryption": self.encrypt_sw.isChecked(),
        }

    # ── Setters
    def set_defaults(self, d: dict):
        if "save_root" in d:
            self.path_edit.setText(d["save_root"])
            self._summary_path_lbl.setText(f"保存目录\n{d['save_root']}")
        if "save_mode" in d:
            idx = self.mode_combo.findData(d["save_mode"])
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
            self._summary_mode_lbl.setText(f"保存模式\n{self.mode_combo.currentText()}")
        if "api_id" in d:
            self.api_id_edit.setText(d["api_id"])
        if "api_hash" in d:
            self.api_hash_edit.setText(d["api_hash"])
        if "session_name" in d:
            self.session_edit.setText(d["session_name"])
        if "session_path" in d:
            self.session_path_edit.setText(str(d["session_path"]))
        if "use_system_proxy" in d:
            self.use_system_proxy_sw.setChecked(bool(d["use_system_proxy"]))
        if "proxy_url" in d:
            self.proxy_url_edit.setText(str(d["proxy_url"] or ""))
        self._update_proxy_preview()
        if "theme_mode" in d:
            rb = self._theme_radios.get(d["theme_mode"])
            if rb:
                rb.setChecked(True)
        if "max_posts" in d:
            self.max_posts.setValue(int(d["max_posts"]))
        if "preview_max_results" in d:
            self.preview_max_results.setValue(int(d["preview_max_results"]))
        if "concurrency" in d:
            self.concurrency_spin.setValue(int(d["concurrency"]))
        if "chunk_concurrency" in d:
            self.chunk_concurrency_spin.setValue(int(d["chunk_concurrency"]))
        if "file_download_interval" in d:
            self.interval_spin.setValue(float(d["file_download_interval"]))
        if "filename_limit" in d:
            self.fn_len_spin.setValue(int(d["filename_limit"]))
        if "empty_tag_action" in d:
            idx = self.tag_empty_combo.findData(d["empty_tag_action"])
            if idx >= 0:
                self.tag_empty_combo.setCurrentIndex(idx)
        if "restore_on_launch" in d:
            self.restore_cb.setChecked(bool(d["restore_on_launch"]))
        if "use_last_mode" in d:
            self.last_mode_cb.setChecked(bool(d["use_last_mode"]))
        if "auto_fill_tag" in d:
            self.auto_tag_cb.setChecked(bool(d["auto_fill_tag"]))
        if "enable_system_notifications" in d:
            self.notification_sw.setChecked(bool(d["enable_system_notifications"]))
        if "close_behavior" in d:
            rb = self._close_behavior_radios.get(d["close_behavior"])
            if rb:
                rb.setChecked(True)
        if "remember_close_behavior" in d:
            self._close_remember_radios[bool(d["remember_close_behavior"])].setChecked(True)
        if "skip_duplicates" in d:
            key = d["skip_duplicates"]
            if isinstance(key, bool):
                key = "skip" if key else "rename"
            rb = self._dup_radios.get(key)
            if rb:
                rb.setChecked(True)
            labels = {"skip": "跳过", "overwrite": "覆盖", "rename": "自动重命名"}
            self._summary_dup_lbl.setText(f"重复文件处理\n{labels.get(key, key)}")
        if "filename_template" in d:
            self.filename_edit.setText(d["filename_template"])
            self._summary_fn_lbl.setText(f"文件命名规则\n{d['filename_template']}")
        if "preserve_original_name" in d:
            self.preserve_original_sw.setChecked(bool(d["preserve_original_name"]))
            if d["preserve_original_name"]:
                self._summary_fn_lbl.setText("文件命名规则\n优先保留原名")
        if "open_after_download" in d:
            self.auto_open_sw.setChecked(bool(d["open_after_download"]))
        if "lang" in d:
            idx = self.lang_combo.findData(d["lang"])
            if idx >= 0:
                self.lang_combo.setCurrentIndex(idx)
        if "enable_animations" in d:
            self.anim_sw.setChecked(bool(d["enable_animations"]))
        if "enable_rounded_corners" in d:
            self.round_sw.setChecked(bool(d["enable_rounded_corners"]))
        if "use_dpapi_encryption" in d:
            self.encrypt_sw.setChecked(
                sys.platform == "win32" and bool(d["use_dpapi_encryption"])
            )
        self._update_save_mode_preview()
        QTimer.singleShot(0, self._sync_stack_height)

    def set_channel_cache(self, rows: list[dict]):
        if not hasattr(self, "_channel_cache_table"):
            return
        self._channel_cache_table.setUpdatesEnabled(False)
        self._channel_cache_table.setRowCount(0)
        for item in rows:
            channel_id = str(item.get("id", "")).strip()
            if not channel_id:
                continue
            row = self._channel_cache_table.rowCount()
            self._channel_cache_table.insertRow(row)
            name = str(item.get("name", "") or "未命名频道")
            link = str(item.get("link", "") or channel_id)
            values = [name, channel_id, link]
            for col, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                table_item.setToolTip(value)
                self._channel_cache_table.setItem(row, col, table_item)

            delete_btn = ToolButton(FIF.DELETE)
            delete_btn.setFixedSize(28, 28)
            delete_btn.setToolTip("删除这条频道缓存")
            delete_btn.clicked.connect(
                lambda checked=False, cid=channel_id: self.channel_cache_delete_requested.emit(cid)
            )
            ops_widget = QWidget()
            ops_layout = QHBoxLayout(ops_widget)
            ops_layout.setContentsMargins(4, 4, 4, 4)
            ops_layout.addStretch()
            ops_layout.addWidget(delete_btn)
            ops_layout.addStretch()
            self._channel_cache_table.setCellWidget(row, 3, ops_widget)
            self._channel_cache_table.setRowHeight(row, 38)
        self._channel_cache_table.setUpdatesEnabled(True)
        QTimer.singleShot(0, self._sync_stack_height)

    def refresh_theme(self):
        if hasattr(self, "_channel_cache_table"):
            self._channel_cache_table.refresh_theme()

    def set_session_status(self, loaded: bool, message: str = ""):
        if loaded:
            self._session_loaded_badge.setText("已加载")
            self._session_loaded_badge.setStyleSheet(
                f"background:{C_GREEN};color:white;border-radius:13px;font-size:12px;font-weight:bold;")
        else:
            self._session_loaded_badge.setText("未加载")
            self._session_loaded_badge.setStyleSheet(
                "background:#e53935;color:white;border-radius:13px;font-size:12px;font-weight:bold;")

        if message:
            self._session_status_label.setText(message)


# ──────────────────────────────────────────────────────────────
#  关于页
# ──────────────────────────────────────────────────────────────
