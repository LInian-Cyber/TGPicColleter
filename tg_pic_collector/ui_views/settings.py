from __future__ import annotations

from .common import *
from .common import _UI_DIR, _asset, _divider, _img_label, _muted, _set_margins

class SettingsPage(ScrollPage):
    save_requested = Signal(dict)   # emit settings dict
    logout_requested = Signal()
    cache_clear_requested = Signal()

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
        self.root.addWidget(self._stack)

        # 底部操作栏
        foot = SurfaceCard()
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
        self.root.addWidget(foot)

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
        dl.body.addWidget(_muted("按每个 Tag 自动创建独立文件夹，便于分类管理。"))
        dl.body.addWidget(StrongBodyLabel("默认检查帖子数量"))
        self.max_posts = SpinBox()
        self.max_posts.setRange(1, 5000)
        self.max_posts.setValue(200)
        self.max_posts.setMinimumSize(140, 36)
        dl.body.addWidget(self.max_posts)
        grid.addWidget(dl, 0, 0)

        # 启动行为
        launch = SurfaceCard("启动行为")
        for label, desc, attr in [
            ("启动时恢复上次下载配置", "应用启动时自动恢复上次会话和下载配置。", "restore_cb"),
            ("默认沿用上次模式", "新建任务时自动沿用上一次使用的保存模式。", "last_mode_cb"),
            ("新建任务时自动带入最近 Tag", "从最近使用的 Tag 列表中自动填充。", "auto_tag_cb"),
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
        self.concurrency_spin.setValue(6)
        self.concurrency_spin.setMinimumSize(140, 36)
        card.body.addWidget(self.concurrency_spin)
        card.body.addWidget(StrongBodyLabel("单个文件下载后等待（秒）"))
        self.interval_spin = DoubleSpinBox()
        self.interval_spin.setRange(0, 10)
        self.interval_spin.setSingleStep(0.1)
        self.interval_spin.setDecimals(1)
        self.interval_spin.setValue(1.0)
        self.interval_spin.setMinimumSize(140, 36)
        card.body.addWidget(self.interval_spin)
        card.body.addWidget(_muted(
            "该间隔用于每个媒体文件下载后的冷却；Telegram 搜索、读取帖子等请求不使用此间隔。"
        ))
        card.body.addWidget(StrongBodyLabel("文件名长度限制"))
        self.fn_len_spin = SpinBox()
        self.fn_len_spin.setRange(20, 255)
        self.fn_len_spin.setValue(100)
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
        self.encrypt_sw.setChecked(True)
        enc_row.addWidget(self.encrypt_sw)
        api_card.body.addLayout(enc_row)
        api_card.body.addWidget(_muted("使用系统 DPAPI 加密存储会话文件。"))

        ops_row = QHBoxLayout()

        logout_btn = PushButton("登出当前账号", icon=FIF.POWER_BUTTON)
        logout_btn.clicked.connect(self.logout_requested)

        cache_btn = PushButton("清理缓存", icon=FIF.DELETE)
        cache_btn.clicked.connect(self.cache_clear_requested)

        # ✨ 1. 统一将两个按钮的尺寸设置为相同的最小宽高（宽 140，高 36）
        # ✨ 2. 删除了原有的 setStyleSheet("color:#e53935;")，恢复原生的高级质感与交互反馈
        for button in (logout_btn, cache_btn):
            button.setMinimumSize(140, 36)

        ops_row.addWidget(logout_btn)
        ops_row.addWidget(cache_btn)
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
        grid.addWidget(theme_card, 0, 0)

        # 动画与圆角
        anim_card = SurfaceCard("界面效果")
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
            setattr(self, attr, sw)
            row.addWidget(sw)
            anim_card.body.addLayout(row)
            anim_card.body.addWidget(_divider())
        grid.addWidget(anim_card, 0, 1)

        # 语言
        lang_card = SurfaceCard("语言（Language）")
        self.lang_combo = ComboBox()
        self.lang_combo.addItem("简体中文", userData="zh_CN")
        self.lang_combo.addItem("English", userData="en_US")
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

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择默认保存目录", self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def _choose_session_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择会话存储位置")
        if d:
            self.session_path_edit.setText(d)

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
        self.path_edit.setText("")
        self.max_posts.setValue(200)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData("channel_tag")))
        self.preserve_original_sw.setChecked(True)
        self.concurrency_spin.setValue(6)
        self.interval_spin.setValue(1.0)
        self.fn_len_spin.setValue(100)
        self.tag_empty_combo.setCurrentIndex(
            max(0, self.tag_empty_combo.findData("uncategorized"))
        )
        self.restore_cb.setChecked(True)
        self.last_mode_cb.setChecked(True)
        self.auto_tag_cb.setChecked(True)

    def _collect(self) -> dict:
        mode = self.mode_combo.currentData() or "channel_tag"
        dup = next((k for k, rb in self._dup_radios.items() if rb.isChecked()), "skip")
        theme = next((k for k, rb in self._theme_radios.items() if rb.isChecked()), "auto")
        return {
            "save_root": self.path_edit.text().strip(),
            "save_mode": mode,
            "max_posts": self.max_posts.value(),
            "concurrency": self.concurrency_spin.value(),
            "file_download_interval": float(self.interval_spin.value()),
            "filename_limit": self.fn_len_spin.value(),
            "empty_tag_action": self.tag_empty_combo.currentData() or "uncategorized",
            "restore_on_launch": self.restore_cb.isChecked(),
            "use_last_mode": self.last_mode_cb.isChecked(),
            "auto_fill_tag": self.auto_tag_cb.isChecked(),
            "skip_duplicates": dup,
            "filename_template": self.filename_edit.text().strip(),
            "preserve_original_name": self.preserve_original_sw.isChecked(),
            "api_id": self.api_id_edit.text().strip(),
            "api_hash": self.api_hash_edit.text().strip(),
            "session_name": self.session_edit.text().strip() or "default",
            "session_path": self.session_path_edit.text().strip(),
            "theme_mode": theme,
            "lang": self.lang_combo.currentData(),
            "open_after_download": self.auto_open_sw.isChecked(),
            "enable_animations": self.anim_sw.isChecked(),
            "enable_rounded_corners": self.round_sw.isChecked(),
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
        if "theme_mode" in d:
            rb = self._theme_radios.get(d["theme_mode"])
            if rb:
                rb.setChecked(True)
        if "max_posts" in d:
            self.max_posts.setValue(int(d["max_posts"]))
        if "concurrency" in d:
            self.concurrency_spin.setValue(int(d["concurrency"]))
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
            self.encrypt_sw.setChecked(bool(d["use_dpapi_encryption"]))

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
