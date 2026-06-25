from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QDialog

from ..i18n import translate
from .common import *
from .common import _divider, _muted, _set_margins


IGP_SECTION_OPTIONS = [
    {
        "key": "image",
        "label": "图片基础信息",
        "description": "文件名、MIME、尺寸、大小与 SHA-256。",
        "default": True,
    },
    {
        "key": "tags",
        "label": "Tags",
        "description": "任务 Tag、Telegram 话题标签和来源标签。",
        "default": True,
    },
    {
        "key": "telegram",
        "label": "Telegram 来源",
        "description": "频道、帖子、消息、媒体 ID 与来源链接。",
        "default": True,
    },
    {
        "key": "text",
        "label": "帖子文本",
        "description": "匹配帖子、评论或资源消息中的文本。",
        "default": True,
    },
    {
        "key": "download",
        "label": "下载记录",
        "description": "本地文件名与保存目录等导入记录。",
        "default": True,
    },
    {
        "key": "*",
        "label": "其它扩展字段",
        "description": "保留未来新增或第三方写入的未知 metadata 段。",
        "default": True,
    },
]


class IGPExportOptionsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("IGP 打包选项")
        self.setMinimumSize(560, 460)
        self._section_checks: dict[str, CheckBox] = {}

        layout = QVBoxLayout(self)
        _set_margins(layout, (18, 18, 18, 18), 14)

        layout.addWidget(SubtitleLabel("选择要写入 IGP 的信息"))
        layout.addWidget(_muted("原图始终会进入 .igp；下面只控制附加 metadata 段。"))

        for option in IGP_SECTION_OPTIONS:
            row = QHBoxLayout()
            row.setSpacing(12)
            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            text_col.addWidget(StrongBodyLabel(option["label"]))
            text_col.addWidget(_muted(option["description"]))
            check = CheckBox()
            check.setChecked(bool(option.get("default", True)))
            self._section_checks[str(option["key"])] = check
            row.addLayout(text_col, 1)
            row.addWidget(check, 0, Qt.AlignmentFlag.AlignVCenter)
            layout.addLayout(row)

        layout.addWidget(_divider())

        checksum_row = QHBoxLayout()
        checksum_text = QVBoxLayout()
        checksum_text.setSpacing(2)
        checksum_text.addWidget(StrongBodyLabel("校验清单"))
        checksum_text.addWidget(_muted("额外写入 checksums.json，用于之后校验包内文件完整性。"))
        self._checksum_cb = CheckBox()
        self._checksum_cb.setChecked(True)
        checksum_row.addLayout(checksum_text, 1)
        checksum_row.addWidget(self._checksum_cb, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(checksum_row)

        actions = QHBoxLayout()
        actions.addStretch()
        minimal_btn = PushButton("最小包", icon=FIF.RETURN)
        all_btn = PushButton("全选", icon=FIF.ACCEPT)
        cancel_btn = PushButton("取消")
        export_btn = PrimaryPushButton("开始导出", icon=FIF.SAVE)
        minimal_btn.clicked.connect(self._select_minimal)
        all_btn.clicked.connect(self._select_all)
        cancel_btn.clicked.connect(self.reject)
        export_btn.clicked.connect(self.accept)
        actions.addWidget(minimal_btn)
        actions.addWidget(all_btn)
        actions.addWidget(cancel_btn)
        actions.addWidget(export_btn)
        layout.addLayout(actions)

    def _select_all(self):
        for check in self._section_checks.values():
            check.setChecked(True)
        self._checksum_cb.setChecked(True)

    def _select_minimal(self):
        for key, check in self._section_checks.items():
            check.setChecked(key in {"image", "tags"})
        self._checksum_cb.setChecked(True)

    def values(self) -> dict:
        return {
            "metadata_sections": [
                key for key, check in self._section_checks.items()
                if check.isChecked()
            ],
            "include_checksums": self._checksum_cb.isChecked(),
        }


class ExportPage(ScrollPage):
    export_requested = Signal(dict)
    open_output_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__("exportPage", parent)
        self._mode = "igp"
        self._last_output_dir = ""
        self._language = "zh_CN"
        self._page_header(
            "导出",
            "将已下载图片与 IGP sidecar 融合为元数据图片或 .igp 包。",
            illus="download-illustration.png",
        )

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_form(), 3)
        body.addWidget(self._build_summary(), 2)
        self.root.addLayout(body)
        self.root.addWidget(self._build_results())
        self.root.addStretch()

    def _build_form(self) -> QWidget:
        card = SurfaceCard("导出配置")

        card.body.addWidget(StrongBodyLabel("来源"))
        source_row = QHBoxLayout()
        self.source_edit = LineEdit()
        self.source_edit.setPlaceholderText("选择图片、.igp.json 或包含它们的目录")
        source_file_btn = PushButton("选择文件", icon=FIF.DOCUMENT)
        source_dir_btn = PushButton("选择目录", icon=FIF.FOLDER)
        source_file_btn.clicked.connect(self._choose_source_file)
        source_dir_btn.clicked.connect(self._choose_source_dir)
        source_row.addWidget(self.source_edit, 1)
        source_row.addWidget(source_file_btn)
        source_row.addWidget(source_dir_btn)
        card.body.addLayout(source_row)

        self.recursive_cb = CheckBox("递归扫描子目录")
        self.recursive_cb.setToolTip("来源为目录时，递归查找所有匹配的图片 + .igp.json。")
        card.body.addWidget(self.recursive_cb)

        card.body.addWidget(StrongBodyLabel("输出目录"))
        output_row = QHBoxLayout()
        self.output_edit = LineEdit()
        self.output_edit.setPlaceholderText("留空则输出到原文件所在目录")
        output_btn = PushButton("浏览", icon=FIF.FOLDER)
        output_btn.clicked.connect(self._choose_output_dir)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(output_btn)
        card.body.addLayout(output_row)

        card.body.addWidget(_divider())
        card.body.addWidget(StrongBodyLabel("导出模式"))
        self.igp_radio = RadioButton("IGP 格式")
        self.metadata_radio = RadioButton("嵌入图片元数据")
        self.igp_radio.setChecked(True)
        self.igp_radio.toggled.connect(lambda checked: checked and self._set_mode("igp"))
        self.metadata_radio.toggled.connect(lambda checked: checked and self._set_mode("metadata"))

        for radio, desc in [
            (self.igp_radio, "生成单图 .igp 包，可选择写入哪些扩展信息。"),
            (self.metadata_radio, "生成带 IGP metadata 的 JPEG/PNG 副本。"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(radio)
            row.addWidget(_muted(desc), 1)
            card.body.addLayout(row)

        card.body.addWidget(_divider())
        action_row = QHBoxLayout()
        action_row.addStretch()
        export_btn = PrimaryPushButton("开始导出", icon=FIF.SAVE)
        export_btn.clicked.connect(self._on_export)
        action_row.addWidget(export_btn)
        card.body.addLayout(action_row)
        return card

    def _build_summary(self) -> QWidget:
        card = SurfaceCard("说明")
        card.body.addWidget(_muted("只会处理严格匹配的文件对："))
        card.body.addWidget(StrongBodyLabel("photo.jpg + photo.jpg.igp.json"))
        card.body.addWidget(_muted("孤立图片或孤立 sidecar 会跳过，不会生成输出。"))
        card.body.addWidget(_divider())
        card.body.addWidget(StrongBodyLabel("当前状态"))
        self._status_label = _muted("等待导出任务。")
        card.body.addWidget(self._status_label)
        self._open_output_btn = PushButton("打开输出目录", icon=FIF.FOLDER)
        self._open_output_btn.setEnabled(False)
        self._open_output_btn.clicked.connect(self._open_output)
        card.body.addWidget(self._open_output_btn)
        card.body.addStretch()
        return card

    def _build_results(self) -> QWidget:
        card = SurfaceCard("导出结果")
        self._result_table = PassiveTableWidget(0, 5)
        self._result_table.setHorizontalHeaderLabels(["文件", "模式", "状态", "输出", "说明"])
        self._result_table.verticalHeader().hide()
        self._result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._result_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._result_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._result_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._result_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._result_table.setColumnWidth(1, 110)
        self._result_table.setColumnWidth(2, 90)
        self._result_table.setMinimumHeight(260)
        card.body.addWidget(self._result_table)
        return card

    def _set_mode(self, mode: str):
        self._mode = mode
        if mode == "igp":
            self.metadata_radio.setChecked(False)
        else:
            self.igp_radio.setChecked(False)

    def _choose_source_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("选择图片或 IGP sidecar"),
            self.source_edit.text().strip() or "",
            "Images and sidecars (*.jpg *.jpeg *.png *.webp *.avif *.gif *.bmp *.tif *.tiff *.igp.json);;All files (*.*)",
        )
        if path:
            self.source_edit.setText(path)

    def _choose_source_dir(self):
        path = QFileDialog.getExistingDirectory(
            self,
            self._tr("选择来源目录"),
            self.source_edit.text().strip() or "",
        )
        if path:
            self.source_edit.setText(path)

    def _choose_output_dir(self):
        path = QFileDialog.getExistingDirectory(
            self,
            self._tr("选择输出目录"),
            self.output_edit.text().strip() or self.source_edit.text().strip() or "",
        )
        if path:
            self.output_edit.setText(path)

    def _on_export(self):
        source = self.source_edit.text().strip()
        if not source:
            self._status_label.setText("请先选择来源。")
            return
        options = {}
        if self._mode == "igp":
            dialog = IGPExportOptionsDialog(self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            options = dialog.values()
        self.export_requested.emit(
            {
                "source_path": source,
                "output_path": self.output_edit.text().strip(),
                "mode": self._mode,
                "recursive": self.recursive_cb.isChecked(),
                "igp_options": options,
            }
        )

    def _open_output(self):
        path = self.output_edit.text().strip() or self._last_output_dir
        if path:
            self.open_output_requested.emit(path)

    def set_export_result(self, summary: str, rows: list[dict]):
        self._status_label.setText(summary)
        self._last_output_dir = ""
        for row in rows:
            output = str(row.get("output", "") or "")
            if output:
                self._last_output_dir = str(Path(output).parent)
                break
        self._open_output_btn.setEnabled(bool(self.output_edit.text().strip()) or bool(self._last_output_dir))
        self._result_table.setUpdatesEnabled(False)
        self._result_table.setRowCount(0)
        for row in rows:
            r = self._result_table.rowCount()
            self._result_table.insertRow(r)
            values = [
                str(row.get("file", "")),
                str(row.get("mode", "")),
                str(row.get("status", "")),
                str(row.get("output", "")),
                str(row.get("message", "")),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self._result_table.setItem(r, col, item)
        self._result_table.resizeRowsToContents()
        self._result_table.setUpdatesEnabled(True)

    def refresh_theme(self):
        self._result_table.refresh_theme()

    def set_language(self, lang: str):
        self._language = lang

    def _tr(self, text: str) -> str:
        return translate(text, self._language)
