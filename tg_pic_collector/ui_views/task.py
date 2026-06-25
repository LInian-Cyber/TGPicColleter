from __future__ import annotations

import json
import os

from ..models import normalize_channel_reference
from .common import *
from .common import _UI_DIR, _asset, _divider, _img_label, _muted, _set_margins, _set_round_avatar
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTextEdit,
    QListWidget, QListWidgetItem, QSplitter,
)

DEFAULT_ADVANCED_RULE_NAME = '5. 正文与评论区混合深挖（最多五层）'
DEFAULT_ADVANCED_RULE_CONFIG = {
    'enable_advanced': True,
    'parse_inline_hyperlinks': True,
    'follow_tg_links': {
        'enable': True,
        'max_depth': 5,
        'keywords': [],
    },
}


def _default_advanced_json() -> str:
    return json.dumps(DEFAULT_ADVANCED_RULE_CONFIG, indent=2, ensure_ascii=False)


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
    advanced_rules_changed = Signal(list)

    def __init__(self, parent=None):
        super().__init__("taskPage", parent)
        self._task_busy = False
        self._preview_busy = False
        self._default_save_root = ""
        self._default_mode_label = ""
        self._default_mode_key = ""
        self._default_save_extended_info = False
        self._channel_list = []  # 存储频道列表
        self._custom_advanced_rules: list[dict] = []
        self._page_header("新建下载任务",
                          "默认行为来自 设置，您可在本页按需临时覆盖，上次使用的模式可一键复用。")

        # 提示横幅
        notice = SurfaceCard()
        notice_row = QHBoxLayout()
        self._notice_icon = QLabel()
        set_theme_icon(self._notice_icon, FIF.INFO, 16)
        notice_row.addWidget(self._notice_icon)
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
        acct_row.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignVCenter)
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
        self._acct_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._acct_status.setFixedHeight(36)
        self._switch_btn = PushButton("切换账号", icon=FIF.SYNC)
        self._switch_btn.setMinimumHeight(36)
        self._switch_btn.clicked.connect(self.switch_account_requested)
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
        control_widget = QWidget()
        control_widget.setStyleSheet("background:transparent;")
        control_row = QHBoxLayout(control_widget)
        control_row.setContentsMargins(0, 0, 0, 0)
        control_row.setSpacing(12)
        control_row.addWidget(self._acct_status, 0, Qt.AlignmentFlag.AlignVCenter)
        control_row.addWidget(self._switch_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        acct_row.addWidget(control_widget, 0, Qt.AlignmentFlag.AlignVCenter)
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
        date_row = QHBoxLayout()
        date_row.setSpacing(8)
        self.date_filter_cb = CheckBox("按时间跨度筛选")
        self.date_filter_cb.setToolTip("只匹配这个日期范围内的帖子。结束日期包含当天。")
        self.start_date_edit = DateEdit()
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-1))
        self.start_date_edit.setMinimumHeight(32)
        self.start_date_edit.setEnabled(False)
        self.end_date_edit = DateEdit()
        self.end_date_edit.setDate(QDate.currentDate())
        self.end_date_edit.setMinimumHeight(32)
        self.end_date_edit.setEnabled(False)
        self.date_filter_cb.stateChanged.connect(self._on_date_filter_changed)
        date_row.addWidget(self.date_filter_cb)
        date_row.addWidget(_muted("从", wrap=False))
        date_row.addWidget(self.start_date_edit)
        date_row.addWidget(_muted("到", wrap=False))
        date_row.addWidget(self.end_date_edit)
        date_row.addStretch()
        tag_col.addLayout(date_row)
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
        self.extract_btn_cb = CheckBox("普通模式：追踪帖子正文超链接并下载原图")
        self.extract_btn_cb.setChecked(True)
        self.extract_btn_cb.setToolTip("高级规则启用时，链接追踪由高级 JSON 独立控制。")

        self.btn_keyword_edit = LineEdit()
        self.btn_keyword_edit.setPlaceholderText("正文链接文字包含，如：原图")
        self.btn_keyword_edit.setText("原图")
        self.btn_keyword_edit.setMinimumSize(160, 32)

        # 简单的 UI 交互：勾选才启用输入框
        self.extract_btn_cb.stateChanged.connect(
            lambda: self.btn_keyword_edit.setEnabled(self.extract_btn_cb.isChecked())
        )

        opts_row2.addWidget(self.extract_btn_cb)
        opts_row2.addWidget(self.btn_keyword_edit)
        opts_row2.addStretch()

        opts_row3 = QHBoxLayout()
        opts_row3.setSpacing(12)
        self.save_ext_info_cb = CheckBox("保存图片扩展信息（IGP sidecar）")
        self.save_ext_info_cb.setToolTip(
            "下载成功后在图片旁边生成 .igp.json，保存 Tag、来源帖子、媒体 ID 等信息。"
        )
        opts_row3.addWidget(self.save_ext_info_cb)
        opts_row3.addStretch()

        opts_col.addLayout(opts_row1)
        opts_col.addLayout(opts_row2)
        opts_col.addLayout(opts_row3)
        opts_col.addWidget(_muted("ⓘ  默认行为已记忆，上次选择可自动恢复。"))
        form.addLayout(opts_col, 4, 1)

        # 6. 高级自定义提取规则（JSON 套娃深挖）
        form.addWidget(StrongBodyLabel("6. 高级提取规则（套娃深挖）"), 5, 0)
        adv_row = QHBoxLayout()
        adv_row.setSpacing(12)
        self._adv_json_str: str = _default_advanced_json()
        self._adv_json_badge = _muted(
            f"已启用：{DEFAULT_ADVANCED_RULE_NAME} · 已接管链接追踪"
        )
        self._adv_json_badge.setWordWrap(True)
        self._adv_json_btn = PushButton("配置高级规则", icon=FIF.CODE)
        self._adv_json_btn.setMinimumHeight(36)
        self._adv_json_btn.setMinimumWidth(140)
        self._adv_json_btn.clicked.connect(self._on_open_json_dialog)
        self._adv_json_clear_btn = PushButton("清除", icon=FIF.DELETE)
        self._adv_json_clear_btn.setMinimumHeight(36)
        self._adv_json_clear_btn.clicked.connect(self._on_clear_json_config)
        adv_row.addWidget(self._adv_json_badge, 1)
        adv_row.addWidget(self._adv_json_btn)
        adv_row.addWidget(self._adv_json_clear_btn)
        form.addLayout(adv_row, 5, 1)

        # 操作按钮
        form.addWidget(_divider(), 6, 0, 1, 2)
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
        form.addLayout(btn_row, 7, 0, 1, 2)
        self._tag_empty_notice = QFrame()
        self._tag_empty_notice.setObjectName("tagEmptyNotice")
        self._tag_empty_notice.setStyleSheet(
            "QFrame#tagEmptyNotice{background:#f6f9ff;border:1px solid #dbe8ff;"
            "border-radius:10px;}"
        )
        notice_row = QHBoxLayout(self._tag_empty_notice)
        notice_row.setContentsMargins(12, 8, 12, 8)
        notice_row.setSpacing(8)
        notice_icon = IconWidget(FIF.INFO)
        notice_icon.setFixedSize(18, 18)
        notice_row.addWidget(notice_icon, 0, Qt.AlignmentFlag.AlignTop)
        notice_row.addWidget(_muted(
            "未填写 Tag：将从最新帖子开始按匹配数量处理，保存时使用未分类或频道名规则。"
        ), 1)
        form.addWidget(self._tag_empty_notice, 8, 0, 1, 2)
        self.tag_edit.textChanged.connect(self._update_tag_empty_notice)
        self._update_tag_empty_notice()

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
            ("文件下载间隔", "0.5 秒"),
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
        normalized = normalize_channel_reference(text)
        if normalized and normalized != text:
            self.channel_combo.setText(normalized)
        return normalized
    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择图片保存位置", self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def _on_date_filter_changed(self):
        enabled = self.date_filter_cb.isChecked()
        self.start_date_edit.setEnabled(enabled)
        self.end_date_edit.setEnabled(enabled)

    def _update_tag_empty_notice(self):
        self._tag_empty_notice.setVisible(not self.tag_edit.text().strip())

    def _collect_task_params(self) -> dict:
        params = {
            "channel": self._get_channel_input(),
            "tag": self.tag_edit.text().strip(),
            "save_root": self.path_edit.text().strip(),
            "save_mode": self.mode_combo.currentData(),
            "only_images": self.only_images_cb.isChecked(),
            "skip_duplicates": self.skip_dup_cb.isChecked(),
            "include_replies": self.include_replies_cb.isChecked(),
            "extract_button_link": self.extract_btn_cb.isChecked(),
            "button_keyword": self.btn_keyword_edit.text().strip(),
            "open_after": self.open_after_cb.isChecked(),
            "custom_extract_json": self._adv_json_str,
            "save_extended_info": self.save_ext_info_cb.isChecked(),
        }
        if self.date_filter_cb.isChecked():
            start = self.start_date_edit.date()
            end = self.end_date_edit.date()
            if start > end:
                start, end = end, start
            params["date_from"] = start.toString("yyyy-MM-dd")
            params["date_to"] = end.toString("yyyy-MM-dd")
        return params

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
            link = ch.get("link", "") or ch_id
            avatar_bytes = ch.get("avatar", b"")

            display_text = f"{name}  ·  {link}" if name and link else (link or name or ch_id)

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
                lambda checked=False, text=ch_id: self.channel_combo.setText(text)
            )
            menu.addAction(action)

        if not menu.actions():
            action = Action(FIF.INFO, "暂无可用频道")
            action.setEnabled(False)
            menu.addAction(action)

        # 显示菜单
        menu.exec(self._channel_list_btn.mapToGlobal(self._channel_list_btn.rect().bottomLeft()))

    def _on_start(self):
        self.start_requested.emit(self._collect_task_params())

    def _on_preview(self):
        self.preview_requested.emit(self._collect_task_params())

    def _on_save_template(self):
        """保存当前配置为模板（实际上就是保存到默认设置）"""
        self.save_template_requested.emit(self._collect_task_params())

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
        self.save_ext_info_cb.setChecked(self._default_save_extended_info)
        self._adv_json_str = _default_advanced_json()
        self._adv_json_badge.setText(
            f"已启用：{DEFAULT_ADVANCED_RULE_NAME} · 已接管链接追踪"
        )

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

    def refresh_theme(self):
        set_theme_icon(self._notice_icon, FIF.INFO, 16)

    def set_defaults(
        self,
        save_root: str,
        save_mode_label: str,
        save_mode_key: str = "",
        save_extended_info: bool = False,
    ):
        self._default_save_root = save_root
        self._default_mode_label = save_mode_label
        self._default_mode_key = save_mode_key
        self._default_save_extended_info = save_extended_info
        self.path_edit.setText(save_root)
        self.save_ext_info_cb.setChecked(save_extended_info)
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

    def restore_task_options(self, params: dict):
        """恢复上一次实际执行任务时使用的本次选项。"""
        self.only_images_cb.setChecked(bool(params.get("only_images", True)))
        self.skip_dup_cb.setChecked(bool(params.get("skip_duplicates", True)))
        self.include_replies_cb.setChecked(bool(params.get("include_replies", True)))
        self.extract_btn_cb.setChecked(bool(params.get("extract_button_link", True)))
        self.btn_keyword_edit.setText(str(params.get("button_keyword", "原图")) or "原图")
        self.open_after_cb.setChecked(bool(params.get("open_after", False)))
        self.save_ext_info_cb.setChecked(bool(params.get("save_extended_info", False)))
        date_from = str(params.get("date_from", "") or "")
        date_to = str(params.get("date_to", "") or "")
        self.date_filter_cb.setChecked(bool(date_from or date_to))
        if date_from:
            self.start_date_edit.setDate(QDate.fromString(date_from, "yyyy-MM-dd"))
        if date_to:
            self.end_date_edit.setDate(QDate.fromString(date_to, "yyyy-MM-dd"))
        self._on_date_filter_changed()
        self._adv_json_str = (
            str(params.get("custom_extract_json", "")).strip()
            or _default_advanced_json()
        )
        self._update_advanced_badge(DEFAULT_ADVANCED_RULE_NAME)

    def set_advanced_rules(self, rules: list[dict]):
        self._custom_advanced_rules = [
            {
                "name": str(rule.get("name", "")).strip(),
                "description": str(rule.get("description", "")).strip(),
                "json": str(rule.get("json", "")).strip(),
            }
            for rule in rules
            if isinstance(rule, dict)
            and str(rule.get("name", "")).strip()
            and str(rule.get("json", "")).strip()
        ]

    def add_channel_history(self, channels: list[dict]):
        """添加频道列表到可编辑下拉框"""
        current_text = self.channel_combo.text().strip()
        self._channel_list = channels
        self.channel_combo.clear()

        if not channels:
            self.channel_combo.setText(current_text)
            return

        for ch in channels[:20]:  # 最多显示20个频道
            name = ch.get("name", "")
            ch_id = ch.get("id", "")
            link = ch.get("link", "") or ch_id
            avatar_bytes = ch.get("avatar", b"")

            # 显示为：头像 + 名字 · 链接；真实下载参数仍通过 userData 保存。
            display_text = f"{name}  ·  {link}" if name and link else (link or name or ch_id)

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

        # 刷新候选项时 EditableComboBox 会自动选中第一项，恢复用户原本输入。
        self.channel_combo.setText(current_text)

    def set_rule_summary(
        self,
        filename_template: str,
        preserve_original_name: bool,
        duplicate_mode: str,
        open_after_download: bool,
        concurrency: int,
        file_download_interval: float,
        filename_limit: int,
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
        if "并发下载数" in self._summary_labels:
            self._summary_labels["并发下载数"].setText(str(concurrency))
        if "文件下载间隔" in self._summary_labels:
            self._summary_labels["文件下载间隔"].setText(
                f"{file_download_interval:g} 秒"
            )
        if "文件名长度限制" in self._summary_labels:
            self._summary_labels["文件名长度限制"].setText(str(filename_limit))

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

    # ── 高级 JSON 规则槽函数 ──────────────────────────────────────────────

    def _on_open_json_dialog(self):
        """打开高级提取规则弹窗"""
        dlg = JsonConfigDialog(
            current_json=self._adv_json_str,
            custom_rules=self._custom_advanced_rules,
            parent=self,
        )
        dlg.rules_changed.connect(self._save_custom_advanced_rules)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            raw = dlg.get_json_text()
            if not raw:
                self._adv_json_str = ""
                self._adv_json_badge.setText("未启用 · 点击右侧按钮选择场景模板")
                return
            # 验证是合法 JSON
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as e:
                InfoBar.error(
                    title="JSON 格式错误",
                    content=f"请检查语法后重试：{e}",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                    parent=self,
                )
                return
            self._adv_json_str = raw
            self._save_custom_advanced_rules(dlg.get_custom_rules())
            self._update_advanced_badge(dlg.get_rule_name(), parsed)

    def _on_clear_json_config(self):
        """清除高级规则"""
        self._adv_json_str = ""
        self._adv_json_badge.setText("未启用 · 点击右侧按钮选择场景模板")

    def _save_custom_advanced_rules(self, rules: list[dict]):
        self._custom_advanced_rules = list(rules)
        self.advanced_rules_changed.emit(self._custom_advanced_rules)

    def _update_advanced_badge(self, name: str = "", parsed: dict | None = None):
        if not self._adv_json_str:
            self._adv_json_badge.setText("未启用 · 点击右侧按钮选择场景模板")
            return
        if parsed is None:
            try:
                parsed = json.loads(self._adv_json_str)
            except json.JSONDecodeError:
                parsed = {}
        mode_name = name.strip() or "正文超链接追踪规则"
        self._adv_json_badge.setText(f"已启用：{mode_name} · 已接管链接追踪")





# ══════════════════════════════════════════════════════════════════════════════
# JsonConfigDialog — 高级自定义提取规则弹窗（PySide6）
# 内置正文超链接追踪场景模板 + 自由 JSON 微调
# ══════════════════════════════════════════════════════════════════════════════

class JsonConfigDialog(QDialog):
    """
    高级自定义提取规则面板。

    内置规则均从帖子正文中的 Telegram 超链接开始追踪目标消息媒体。
    """

    rules_changed = Signal(list)

    _TEMPLATES = {
        '1. 正文原图链接（单层追踪）': {
            'enable_advanced': True,
            'description': (
                '【场景】帖子正文中包含「原图」「Full Size」等可点击文字，'
                '链接指向另一个 Telegram 频道帖子。\n\n'
                '【行为】打开正文超链接对应的目标帖子，并下载目标帖媒体。'
            ),
            'parse_inline_hyperlinks': True,
            'follow_tg_links': {
                'enable': True,
                'max_depth': 1,
                'keywords': ['原图', 'Full Size', 'Original'],
            },
        },
        '2. 正文完整资源链接（单层多关键词）': {
            'enable_advanced': True,
            'description': (
                '【场景】正文链接文字可能使用「完整」「高清」「Source」等名称。\n\n'
                '【行为】匹配这些正文超链接，跳转到目标帖子下载媒体。'
            ),
            'parse_inline_hyperlinks': True,
            'follow_tg_links': {
                'enable': True,
                'max_depth': 1,
                'keywords': ['完整', '高清', 'Source', 'Download', '查看'],
            },
        },
        '3. 正文超链接套娃（最多三层）': {
            'enable_advanced': True,
            'description': (
                '【场景】正文链接跳转后的帖子仍然包含正文链接，原图位于更深层帖子。\n\n'
                '【行为】最多连续追踪三层 Telegram 正文超链接并下载媒体。'
            ),
            'parse_inline_hyperlinks': True,
            'follow_tg_links': {
                'enable': True,
                'max_depth': 3,
                'keywords': [],
            },
        },
        '4. 正文全部 TG 帖子链接（最多五层）': {
            'enable_advanced': True,
            'description': (
                '【场景】频道正文链接命名不固定，无法依赖关键词。\n\n'
                '【行为】追踪正文中的全部 Telegram 帖子链接，最多深入五层。'
            ),
            'parse_inline_hyperlinks': True,
            'follow_tg_links': {
                'enable': True,
                'max_depth': 5,
                'keywords': [],
            },
        },
        DEFAULT_ADVANCED_RULE_NAME: {
            **DEFAULT_ADVANCED_RULE_CONFIG,
            'description': (
                '【场景】帖子正文和评论区可能混合出现直接图片、原图链接，'
                '链接目标中还可能继续包含 Telegram 帖子链接。\n\n'
                '【行为】追踪正文与评论区中的全部 Telegram 帖子链接，最多深入五层；'
                '评论区直接图片同时下载。请保持“包含回复中的图片”开启。'
            ),
        },
    }

    def __init__(
        self,
        current_json: str = '',
        custom_rules: list[dict] | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle('高级自定义提取规则（JSON）')
        self.setMinimumSize(1040, 680)
        self._custom_rules = [
            {
                'name': str(rule.get('name', '')).strip(),
                'description': str(rule.get('description', '')).strip(),
                'json': str(rule.get('json', '')).strip(),
            }
            for rule in (custom_rules or [])
            if isinstance(rule, dict)
            and str(rule.get('name', '')).strip()
            and str(rule.get('json', '')).strip()
        ]
        self._selected_custom_index: int | None = None
        self._active_rule_name = ''

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        top_label = BodyLabel(
            '根据目标频道习惯选择对应的场景模板（点击左侧列表自动载入），'
            '右侧 JSON 编辑区可进一步微调。所有规则均只处理 t.me 内部链接，外部链接自动忽略。'
        )
        top_label.setWordWrap(True)
        main_layout.addWidget(top_label)

        # 左右分割
        outer_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：规则列表、名称和可滚动描述
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(StrongBodyLabel('规则列表'))
        self._tpl_list = QListWidget()
        self._tpl_list.setMinimumHeight(220)
        self._tpl_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        list_bg = get_theme_color('#ffffff', '#252a34')
        list_fg = get_theme_color('#1a2233', '#f5f7fb')
        hover_bg = get_theme_color('#eaf3ff', '#344155')
        selected_bg = get_theme_color('#dcecff', '#245a91')
        self._tpl_list.setStyleSheet(
            'QListWidget{'
            f'background:{list_bg};color:{list_fg};border:1px solid {C_BORDER};'
            'border-radius:8px;padding:4px;outline:none;}'
            'QListWidget::item{padding:8px;border:none;border-radius:6px;outline:none;}'
            f'QListWidget::item:hover{{background:{hover_bg};color:{list_fg};border:none;}}'
            f'QListWidget::item:selected{{background:{selected_bg};color:{list_fg};border:none;outline:none;}}'
        )
        left_layout.addWidget(self._tpl_list, 1)

        rule_actions = QHBoxLayout()
        new_btn = PushButton('新建自定义', icon=FIF.ADD)
        delete_btn = PushButton('删除自定义', icon=FIF.DELETE)
        new_btn.clicked.connect(self._new_custom_rule)
        delete_btn.clicked.connect(self._delete_custom_rule)
        rule_actions.addWidget(new_btn)
        rule_actions.addWidget(delete_btn)
        left_layout.addLayout(rule_actions)

        left_layout.addWidget(StrongBodyLabel('规则名称'))
        self._name_edit = LineEdit()
        self._name_edit.setPlaceholderText('例如：某频道原图深挖规则')
        left_layout.addWidget(self._name_edit)

        left_layout.addWidget(StrongBodyLabel('规则描述'))
        self._desc_edit = QTextEdit()
        self._desc_edit.setPlaceholderText('描述这个规则适用于什么频道、按钮或评论区结构。')
        self._desc_edit.setMinimumHeight(150)
        left_layout.addWidget(self._desc_edit, 1)

        # 右侧：JSON 编辑器和保存操作
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        right_layout.addWidget(StrongBodyLabel('JSON 配置'))
        self._text_edit = QTextEdit()
        mono = QFont('Courier New' if os.name == 'nt' else 'Monospace', 10)
        self._text_edit.setFont(mono)
        right_layout.addWidget(self._text_edit, 1)

        editor_actions = QHBoxLayout()
        self._status_label = _muted('')
        format_btn = PushButton('格式化 JSON', icon=FIF.CODE)
        save_rule_btn = PrimaryPushButton('保存当前规则', icon=FIF.SAVE)
        format_btn.clicked.connect(self._format_json)
        save_rule_btn.clicked.connect(self._save_current_rule)
        editor_actions.addWidget(self._status_label, 1)
        editor_actions.addWidget(format_btn)
        editor_actions.addWidget(save_rule_btn)
        right_layout.addLayout(editor_actions)

        outer_splitter.addWidget(left_panel)
        outer_splitter.addWidget(right_panel)
        outer_splitter.setStretchFactor(0, 3)
        outer_splitter.setStretchFactor(1, 5)
        main_layout.addWidget(outer_splitter, 1)

        # 信号绑定
        self._tpl_list.currentItemChanged.connect(self._on_rule_selected)
        self._rebuild_rule_list()

        if current_json:
            self._name_edit.setText('当前正在使用的规则')
            self._desc_edit.setPlainText('这是当前任务页面中已经启用的 JSON，可直接修改并另存为自定义规则。')
            self._text_edit.setPlainText(current_json)
        else:
            self._select_rule_by_name(DEFAULT_ADVANCED_RULE_NAME)

        # 底部按钮
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        apply_btn = PrimaryPushButton('应用到本次下载', self)
        apply_btn.setMinimumWidth(150)
        apply_btn.clicked.connect(self._apply_and_accept)
        cancel_btn = PushButton('取消', self)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(cancel_btn)
        main_layout.addLayout(btn_row)

    def _rebuild_rule_list(self, select_name: str = ''):
        self._tpl_list.blockSignals(True)
        self._tpl_list.clear()
        for name in self._TEMPLATES:
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, ('builtin', name))
            self._tpl_list.addItem(item)
        for index, rule in enumerate(self._custom_rules):
            item = QListWidgetItem(f"自定义 · {rule['name']}")
            item.setData(Qt.ItemDataRole.UserRole, ('custom', index))
            self._tpl_list.addItem(item)
        self._tpl_list.blockSignals(False)
        if select_name:
            self._select_rule_by_name(select_name)

    def _select_rule_by_name(self, name: str):
        # 自定义规则放在列表末尾；倒序查找可优先选中同名的自定义副本。
        for row in range(self._tpl_list.count() - 1, -1, -1):
            item = self._tpl_list.item(row)
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and (
                (data[0] == 'builtin' and data[1] == name)
                or (
                    data[0] == 'custom'
                    and self._custom_rules[data[1]]['name'] == name
                )
            ):
                self._tpl_list.setCurrentItem(item)
                return

    def _on_rule_selected(self, item: QListWidgetItem | None, _previous=None):
        if item is None:
            return
        kind, value = item.data(Qt.ItemDataRole.UserRole)
        if kind == 'builtin':
            tpl = self._TEMPLATES[value]
            self._selected_custom_index = None
            self._name_edit.setText(value)
            self._desc_edit.setPlainText(tpl.get('description', ''))
            payload = {k: v for k, v in tpl.items() if k != 'description'}
            self._text_edit.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            self._selected_custom_index = int(value)
            rule = self._custom_rules[self._selected_custom_index]
            self._name_edit.setText(rule['name'])
            self._desc_edit.setPlainText(rule['description'])
            self._text_edit.setPlainText(rule['json'])
        self._status_label.setText('')

    def _new_custom_rule(self):
        self._tpl_list.clearSelection()
        self._tpl_list.setCurrentRow(-1)
        self._selected_custom_index = None
        self._name_edit.clear()
        self._desc_edit.clear()
        self._text_edit.setPlainText(
            json.dumps({'enable_advanced': True}, indent=2, ensure_ascii=False)
        )
        self._status_label.setText('填写名称、描述和 JSON 后点击“保存当前规则”。')
        self._name_edit.setFocus()

    def _delete_custom_rule(self):
        if self._selected_custom_index is None:
            self._status_label.setText('内置规则不能删除；可先另存为自定义规则。')
            return
        self._custom_rules.pop(self._selected_custom_index)
        self._selected_custom_index = None
        self._rebuild_rule_list()
        self._new_custom_rule()
        self.rules_changed.emit(self.get_custom_rules())
        self._status_label.setText('自定义规则已删除。')

    def _parse_json(self) -> dict | None:
        try:
            parsed = json.loads(self.get_json_text())
        except json.JSONDecodeError as exc:
            self._status_label.setText(f'JSON 格式错误：第 {exc.lineno} 行，第 {exc.colno} 列')
            return None
        if not isinstance(parsed, dict):
            self._status_label.setText('JSON 顶层必须是对象。')
            return None
        return parsed

    def _format_json(self):
        parsed = self._parse_json()
        if parsed is None:
            return
        self._text_edit.setPlainText(json.dumps(parsed, indent=2, ensure_ascii=False))
        self._status_label.setText('JSON 已格式化。')

    def _save_current_rule(self):
        name = self._name_edit.text().strip()
        if not name:
            self._status_label.setText('请先填写规则名称。')
            self._name_edit.setFocus()
            return
        parsed = self._parse_json()
        if parsed is None:
            return
        rule = {
            'name': name,
            'description': self._desc_edit.toPlainText().strip(),
            'json': json.dumps(parsed, indent=2, ensure_ascii=False),
        }
        if self._selected_custom_index is not None:
            self._custom_rules[self._selected_custom_index] = rule
        else:
            existing = next(
                (
                    index for index, current in enumerate(self._custom_rules)
                    if current['name'] == name
                ),
                None,
            )
            if existing is None:
                self._custom_rules.append(rule)
            else:
                self._custom_rules[existing] = rule
        self._active_rule_name = name
        self._text_edit.setPlainText(rule['json'])
        self._rebuild_rule_list(name)
        self.rules_changed.emit(self.get_custom_rules())
        self._status_label.setText('自定义规则已保存。')

    def _apply_and_accept(self):
        if self._parse_json() is None:
            return
        self._active_rule_name = self._name_edit.text().strip() or '自定义规则'
        self.accept()

    def get_json_text(self) -> str:
        return self._text_edit.toPlainText().strip()

    def get_custom_rules(self) -> list[dict]:
        return list(self._custom_rules)

    def get_rule_name(self) -> str:
        return self._active_rule_name
