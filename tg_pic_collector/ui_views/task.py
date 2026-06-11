from __future__ import annotations

from .common import *
from .common import _UI_DIR, _asset, _divider, _img_label, _muted, _set_margins, _set_round_avatar

class TaskPage(ScrollPage):
    # ── Signals
    start_requested = Signal(dict)   # emit task params dict
    cancel_requested = Signal()
    open_current_folder_requested = Signal(str)
    switch_account_requested = Signal()
    settings_requested = Signal()
    preview_requested = Signal(dict)
    save_template_requested = Signal(dict)
    resume_task_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("taskPage", parent)
        self._task_busy = False
        self._preview_busy = False
        self._default_save_root = ""
        self._default_mode_label = ""
        self._default_mode_key = ""
        self._channel_list = []  # 存储频道列表
        self._page_header("新建下载任务",
                          "默认行为来自 设置，您可在本页按需临时覆盖，上次使用的模式可一键复用。")

        # 提示横幅
        notice = SurfaceCard()
        notice_row = QHBoxLayout()
        ico = QLabel()
        ico.setPixmap(FIF.INFO.icon().pixmap(16, 16))
        notice_row.addWidget(ico)
        notice_row.addWidget(BodyLabel(
            "  默认保存模式：沿用上次设置，可在本页临时覆盖；更多默认规则请前往 设置。"))
        notice_row.addStretch()
        notice.body.addLayout(notice_row)
        self.root.addWidget(notice)

        # 账号栏
        self._acct_card = SurfaceCard()
        acct_row = QHBoxLayout()
        self._avatar = QLabel("●")
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setFixedSize(42, 42)
        self._avatar.setObjectName("taskAccountAvatar")
        acct_row.addWidget(self._avatar)
        acct_info = QVBoxLayout()
        acct_info.setSpacing(2)
        self._acct_title_row = QHBoxLayout()
        self._acct_label = BodyLabel("当前账号")
        self._acct_label.setStyleSheet("font-weight:600;")
        self._acct_phone = _muted("未登录")
        self._acct_title_row.addWidget(self._acct_label)
        self._acct_title_row.addSpacing(8)
        self._acct_phone_label = BodyLabel("")
        self._acct_title_row.addWidget(self._acct_phone_label)
        self._acct_title_row.addStretch()
        self._acct_status = BodyLabel("● 未登录")
        self._acct_status.setObjectName("accountStatus")
        self._acct_title_row.addWidget(self._acct_status)
        acct_info.addLayout(self._acct_title_row)
        # 数据中心 / 会话位置
        detail_row = QHBoxLayout()
        self._dc_label = _muted("数据中心  —")
        self._dc_label.setWordWrap(False)
        self._session_label = _muted("会话存储位置  本地安全存储")
        self._session_label.setWordWrap(False)
        detail_row.addWidget(self._dc_label)
        detail_row.addSpacing(24)
        detail_row.addWidget(self._session_label)
        detail_row.addStretch()
        acct_info.addLayout(detail_row)
        acct_row.addLayout(acct_info, 1)
        self._switch_btn = PushButton("切换账号", icon=FIF.SYNC)
        self._switch_btn.clicked.connect(self.switch_account_requested)
        acct_row.addWidget(self._switch_btn)
        self._acct_card.body.addLayout(acct_row)
        self.root.addWidget(self._acct_card)

        # 主体：表单 + 右侧摘要
        body = QHBoxLayout()
        body.setSpacing(14)
        form_card = SurfaceCard()

        # 表单网格
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(16)
        form.setColumnStretch(1, 1)

        # 1. 频道
        form.addWidget(StrongBodyLabel("1. 频道 / 用户名 / ID"), 0, 0)
        self.channel_combo = EditableComboBox()
        self.channel_combo.setPlaceholderText("例如：@wallpapers，直接输入或从下拉历史选择")
        self.channel_combo.setMinimumHeight(36)
        # 移除 channel_row 包装，直接放入表单网格
        form.addWidget(self.channel_combo, 0, 1)

        # 2. Tag
        form.addWidget(StrongBodyLabel("2. Tag 关键词（可选）"), 1, 0)
        tag_col = QVBoxLayout()
        tag_col.setSpacing(6)
        tag_top = QHBoxLayout()
        self.tag_edit = LineEdit()
        self.tag_edit.setPlaceholderText("例如：壁纸")
        self._preview_btn = TransparentPushButton("搜索预览", icon=FIF.SEARCH)
        self._preview_btn.setMinimumHeight(36)
        self._preview_btn.clicked.connect(self._on_preview)
        tag_top.addWidget(self.tag_edit, 1)
        tag_top.addWidget(self._preview_btn)
        tag_col.addLayout(tag_top)
        self._common_tags_row = QHBoxLayout()
        self._common_tags_row.setSpacing(6)
        tag_col.addLayout(self._common_tags_row)
        self.set_common_tags([])
        form.addLayout(tag_col, 1, 1)

        # 3. 保存位置
        form.addWidget(StrongBodyLabel("3. 保存位置"), 2, 0)
        path_row = QHBoxLayout()
        self.path_edit = LineEdit()
        self._open_folder_btn = PushButton("打开目录", icon=FIF.FOLDER)
        self._open_folder_btn.clicked.connect(
            lambda: self.open_current_folder_requested.emit(self.path_edit.text().strip())
        )
        self._change_path_btn = PushButton("本次更改", icon=FIF.EDIT)
        self._change_path_btn.clicked.connect(self._choose_dir)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self._open_folder_btn)
        path_row.addWidget(self._change_path_btn)
        form.addLayout(path_row, 2, 1)

        # 4. 保存模式
        form.addWidget(StrongBodyLabel("4. 保存模式（本次下载覆盖）"), 3, 0)
        mode_row = QHBoxLayout()
        self.mode_combo = ComboBox()
        self.mode_combo.setMinimumWidth(300)
        mode_row.addWidget(self.mode_combo, 1)
        mode_row.addStretch()
        form.addLayout(mode_row, 3, 1)

        # 5. 本次下载选项
        form.addWidget(StrongBodyLabel("5. 本次下载选项（仅此生效）"), 4, 0)
        opts_col = QVBoxLayout()
        opts_col.setSpacing(8)

        # 第一排：常规勾选项
        opts_row1 = QHBoxLayout()
        opts_row1.setSpacing(24)
        self.only_images_cb = CheckBox("仅下载图片")
        self.only_images_cb.setChecked(True)
        self.skip_dup_cb = CheckBox("跳过重复文件")
        self.skip_dup_cb.setChecked(True)
        self.include_replies_cb = CheckBox("包含回复中的图片")
        self.include_replies_cb.setChecked(True)
        self.open_after_cb = CheckBox("完成后打开目录")

        opts_row1.addWidget(self.only_images_cb)
        opts_row1.addWidget(self.skip_dup_cb)
        opts_row1.addWidget(self.include_replies_cb)
        opts_row1.addWidget(self.open_after_cb)
        opts_row1.addStretch()

        # 第二排：✨ 自动提取按钮链接的组合控件
        opts_row2 = QHBoxLayout()
        opts_row2.setSpacing(12)
        self.extract_btn_cb = CheckBox("提取底部按钮链接作为原图")
        self.extract_btn_cb.setChecked(True)

        self.btn_keyword_edit = LineEdit()
        self.btn_keyword_edit.setPlaceholderText("按钮文字包含，如：原图")
        self.btn_keyword_edit.setText("原图")
        self.btn_keyword_edit.setMinimumSize(160, 32)

        # 简单的 UI 交互：勾选才启用输入框
        self.extract_btn_cb.stateChanged.connect(
            lambda: self.btn_keyword_edit.setEnabled(self.extract_btn_cb.isChecked())
        )

        opts_row2.addWidget(self.extract_btn_cb)
        opts_row2.addWidget(self.btn_keyword_edit)
        opts_row2.addStretch()

        opts_col.addLayout(opts_row1)
        opts_col.addLayout(opts_row2)
        opts_col.addWidget(_muted("ⓘ  默认行为已记忆，上次选择可自动恢复。"))
        form.addLayout(opts_col, 4, 1)

        # 操作按钮
        form.addWidget(_divider(), 5, 0, 1, 2)
        btn_row = QHBoxLayout()
        self._start_btn = PrimaryPushButton("  开始下载", icon=FIF.DOWNLOAD)
        self._start_btn.clicked.connect(self._on_start)
        self._save_tpl_btn = PushButton("  保存为模板", icon=FIF.SAVE)
        self._save_tpl_btn.clicked.connect(self._on_save_template)
        self._reset_btn = PushButton("  重置本次覆盖", icon=FIF.RETURN)
        self._reset_btn.clicked.connect(self._on_reset)
        for button in (self._start_btn, self._save_tpl_btn, self._reset_btn):
            button.setMinimumSize(140, 36)
        self._cancel_btn = PushButton("  取消任务", icon=FIF.CANCEL)
        self._cancel_btn.setMinimumSize(140, 36)  # ✨ 替换 setFixedHeight(40)
        self._cancel_btn.hide()
        self._cancel_btn.clicked.connect(self.cancel_requested)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._save_tpl_btn)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._cancel_btn)
        form.addLayout(btn_row, 6, 0, 1, 2)

        form_card.body.addLayout(form)
        body.addWidget(form_card, 3)

        # 右侧默认设置摘要
        summary_card = SurfaceCard("默认设置摘要")
        self._settings_link = TransparentPushButton("前往设置", icon=FIF.SETTING)
        self._settings_link.setMinimumHeight(36)
        self._settings_link.clicked.connect(self.settings_requested)
        if tr := summary_card.title_row():
            tr.addWidget(self._settings_link)
        items = [
            ("保存位置", "D:\\TelegramDownloads"),
            ("保存模式", "按 Tag 建文件夹"),
            ("文件命名", "{tag}_{date}_{index}"),
            ("仅下载图片", "开启"),
            ("跳过重复文件", "开启"),
            ("包含回复中的图片", "关闭"),
            ("完成后打开目录", "关闭"),
            ("并发下载数", "6"),
            ("文件下载间隔", "1.0 秒"),
            ("文件名长度限制", "100"),
        ]
        self._summary_labels: dict[str, QLabel] = {}
        for key, val in items:
            row2 = QHBoxLayout()
            row2.setSpacing(6)
            k_lbl = _muted(key)
            k_lbl.setFixedWidth(100)
            v_lbl = BodyLabel(val)
            v_lbl.setStyleSheet("font-size:12px;")
            row2.addWidget(k_lbl)
            row2.addWidget(v_lbl, 1)
            self._summary_labels[key] = v_lbl
            summary_card.body.addLayout(row2)
        summary_card.body.addWidget(_muted("ⓘ 以上为全局默认规则，可在本页临时覆盖。"))
        summary_card.body.addStretch()
        body.addWidget(summary_card, 1)
        self.root.addLayout(body)

        # 当前任务只保留轻量状态条，完整队列统一放在“下载历史”页。
        self._task_status_card = SurfaceCard("当前任务")
        self._progress_bar = ProgressBar()
        self._progress_bar.setRange(0, 0)
        self._detail_label = _muted("暂无运行中的任务")
        self._task_status_card.body.addWidget(self._progress_bar)
        self._task_status_card.body.addWidget(self._detail_label)
        self._task_status_card.hide()
        self.root.addWidget(self._task_status_card)
        self.root.addStretch()

    def _get_channel_input(self) -> str:
        """辅助方法：智能获取频道ID"""
        text = self.channel_combo.text().strip()
        # 如果用户是从下拉框选的，提取出 userData (真实的 @username 或 ID)
        idx = self.channel_combo.findText(text)
        if idx >= 0:
            return self.channel_combo.itemData(idx) or text
        # 如果是用户纯手打的，直接返回手打文字
        return text
    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择图片保存位置", self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def _show_channel_menu(self):
        """显示频道选择菜单"""
        if not self._channel_list:
            InfoBar.info(
                title="提示",
                content="请先登录以加载频道列表",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        # 创建菜单
        menu = RoundMenu(parent=self)

        for ch in self._channel_list[:20]:  # 最多显示20个频道
            name = ch.get("name", "")
            ch_id = ch.get("id", "")
            avatar_bytes = ch.get("avatar", b"")

            display_text = f"{name} ({ch_id})" if name and ch_id else (ch_id or name)

            # 创建菜单项
            if avatar_bytes:
                pixmap = QPixmap()
                if pixmap.loadFromData(avatar_bytes):
                    # 缩放为16x16的圆形头像（菜单项较小）
                    scaled = pixmap.scaled(
                        16, 16,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    rounded = QPixmap(16, 16)
                    rounded.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(rounded)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addEllipse(0, 0, 16, 16)
                    painter.setClipPath(path)
                    painter.drawPixmap(0, 0, scaled)
                    painter.end()

                    icon = QIcon(rounded)
                    action = Action(icon, display_text)
                else:
                    action = Action(FIF.PEOPLE, display_text)
            else:
                action = Action(FIF.PEOPLE, display_text)

            # 连接点击事件
            action.triggered.connect(
                lambda checked=False, text=ch_id: self.channel_edit.setText(text)
            )
            menu.addAction(action)

        if not menu.actions():
            action = Action(FIF.INFO, "暂无可用频道")
            action.setEnabled(False)
            menu.addAction(action)

        # 显示菜单
        menu.exec(self._channel_list_btn.mapToGlobal(self._channel_list_btn.rect().bottomLeft()))

    def _on_start(self):
        params = {
            "channel": self._get_channel_input(),  # ✨ 改用辅助方法提取
            "tag": self.tag_edit.text().strip(),
            "save_root": self.path_edit.text().strip(),
            "save_mode": self.mode_combo.currentData(),
            "only_images": self.only_images_cb.isChecked(),
            "skip_duplicates": self.skip_dup_cb.isChecked(),
            "include_replies": self.include_replies_cb.isChecked(),
            "extract_button_link": self.extract_btn_cb.isChecked(),
            "button_keyword": self.btn_keyword_edit.text().strip(),
            "open_after": self.open_after_cb.isChecked(),
        }
        self.start_requested.emit(params)

    def _on_preview(self):
        self.preview_requested.emit(
            {
                "channel": self._get_channel_input(),  # ✨ 改用辅助方法提取
                "tag": self.tag_edit.text().strip(),
            }
        )

    def _on_save_template(self):
        """保存当前配置为模板（实际上就是保存到默认设置）"""
        params = {
            "save_root": self.path_edit.text().strip(),
            "save_mode": self.mode_combo.currentData(),
            "only_images": self.only_images_cb.isChecked(),
            "skip_duplicates": self.skip_dup_cb.isChecked(),
            "include_replies": self.include_replies_cb.isChecked(),
            "extract_button_link": self.extract_btn_cb.isChecked(),
            "button_keyword": self.btn_keyword_edit.text().strip(),
            "open_after": self.open_after_cb.isChecked(),
        }
        self.save_template_requested.emit(params)

    def _on_reset(self):
        """重置本次覆盖，恢复到默认设置"""
        self.path_edit.setText(self._default_save_root)
        idx = self.mode_combo.findData(self._default_mode_key)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self.only_images_cb.setChecked(True)
        self.skip_dup_cb.setChecked(True)
        self.include_replies_cb.setChecked(True)
        self.extract_btn_cb.setChecked(True)
        self.btn_keyword_edit.setText("原图")
        self.open_after_cb.setChecked(False)

    # ── Setters
    def set_account(self, name: str = "", phone: str = "", dc: str = ""):
        if name:
            self._acct_phone_label.setText(f"Telethon 用户 · {phone}")
            self._acct_status.setText("● 已登录")
            self._acct_status.setProperty("statusType", "success")
            self._acct_status.setStyle(self._acct_status.style())
            if dc:
                self._dc_label.setText(f"数据中心  {dc}")
        else:
            self._acct_phone_label.setText("")
            self._acct_status.setText("● 未登录")
            self._acct_status.setProperty("statusType", "muted")
            self._acct_status.setStyle(self._acct_status.style())

    def set_user_avatar(self, avatar_bytes: bytes):
        _set_round_avatar(self._avatar, avatar_bytes, 42)

    def set_defaults(self, save_root: str, save_mode_label: str,
                     save_mode_key: str = ""):
        self._default_save_root = save_root
        self._default_mode_label = save_mode_label
        self._default_mode_key = save_mode_key
        self.path_edit.setText(save_root)
        if "保存位置" in self._summary_labels:
            self._summary_labels["保存位置"].setText(save_root)
        if "保存模式" in self._summary_labels:
            self._summary_labels["保存模式"].setText(save_mode_label)
        # sync combo
        idx = self.mode_combo.findData(save_mode_key)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)

    def restore_last_params(self, channel: str, tag: str):
        """恢复上次的任务参数"""
        self.channel_combo.setText(channel)  # ✨ 换成 combo 的 setText
        self.tag_edit.setText(tag)

    def add_channel_history(self, channels: list[dict]):
        """添加频道列表到可编辑下拉框"""
        self._channel_list = channels
        self.channel_combo.clear()

        if not channels:
            return

        for ch in channels[:20]:  # 最多显示20个频道
            name = ch.get("name", "")
            ch_id = ch.get("id", "")
            avatar_bytes = ch.get("avatar", b"")

            # 显示文本，例如: 精彩壁纸 (@wallpapers)
            display_text = f"{name} ({ch_id})" if name and ch_id else (ch_id or name)

            if avatar_bytes:
                pixmap = QPixmap()
                if pixmap.loadFromData(avatar_bytes):
                    # 缩放为16x16的圆形头像
                    scaled = pixmap.scaled(
                        16, 16,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    rounded = QPixmap(16, 16)
                    rounded.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(rounded)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addEllipse(0, 0, 16, 16)
                    painter.setClipPath(path)
                    painter.drawPixmap(0, 0, scaled)
                    painter.end()

                    icon = QIcon(rounded)
                    # ✨ 核心修复：将第一个参数改为文字 display_text，并通过关键字显式传递 icon
                    self.channel_combo.addItem(display_text, icon=icon, userData=ch_id)
                    continue

            # ✨ 同样确保第一个参数是文字
            self.channel_combo.addItem(display_text, userData=ch_id)

    def set_rule_summary(
        self,
        filename_template: str,
        preserve_original_name: bool,
        duplicate_mode: str,
        open_after_download: bool,
    ):
        if "文件命名" in self._summary_labels:
            self._summary_labels["文件命名"].setText(
                "优先保留原名" if preserve_original_name else filename_template
            )
        if "跳过重复文件" in self._summary_labels:
            duplicate_labels = {"skip": "开启", "overwrite": "覆盖", "rename": "自动重命名"}
            self._summary_labels["跳过重复文件"].setText(
                duplicate_labels.get(duplicate_mode, duplicate_mode)
            )
        if "完成后打开目录" in self._summary_labels:
            self._summary_labels["完成后打开目录"].setText(
                "开启" if open_after_download else "关闭"
            )

    def add_mode_item(self, text: str, key: str):
        self.mode_combo.addItem(text, userData=key)

    def set_common_tags(self, tags: list[str]):
        while self._common_tags_row.count():
            item = self._common_tags_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._common_tags_row.addWidget(_muted("常用 Tag："))
        if not tags:
            self._common_tags_row.addWidget(_muted("暂无"))
        else:
            for tag in tags[:6]:
                text = tag if tag.startswith("#") else f"#{tag}"
                pill = TagPill(text)
                pill.clicked.connect(
                    lambda checked=False, value=tag: self.tag_edit.setText(value.lstrip("#"))
                )
                self._common_tags_row.addWidget(pill)
        self._common_tags_row.addStretch()

    def set_busy(self, busy: bool):
        self._task_busy = busy
        self._task_status_card.setVisible(busy)
        self._cancel_btn.setVisible(busy)
        self._sync_action_states()

    def set_preview_busy(self, busy: bool):
        self._preview_busy = busy
        self._preview_btn.setText("正在预览…" if busy else "搜索预览")
        self._sync_action_states()

    def _sync_action_states(self):
        busy = self._task_busy or self._preview_busy
        self._start_btn.setDisabled(busy)
        self._preview_btn.setDisabled(busy)

    def set_detail(self, text: str):
        self._detail_label.setText(text)

    def set_progress(self, downloaded: int, skipped: int, total: int):
        completed = downloaded + skipped
        if total <= 0:
            self._progress_bar.setRange(0, 0)
            self._progress_bar.setValue(0)
        else:
            self._progress_bar.setRange(0, total)
            self._progress_bar.setValue(completed)
