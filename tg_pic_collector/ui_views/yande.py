from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QKeySequence

from .common import *
from .common import _divider, _muted


class CopyableResultTable(PassiveTableWidget):
    def __init__(self, rows: int, columns: int, parent=None):
        super().__init__(rows, columns, parent)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            item = self.itemAt(event.position().toPoint())
            if item and item.column() == self.columnCount() - 1:
                self.open_item(item.text())
                event.accept()
                return
        QTableWidget.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event):
        QTableWidget.mouseReleaseEvent(self, event)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            return
        super().keyPressEvent(event)

    def copy_selection(self):
        indexes = sorted(self.selectedIndexes(), key=lambda idx: (idx.row(), idx.column()))
        if not indexes:
            current = self.currentItem()
            if current:
                QApplication.clipboard().setText(current.text())
            return
        rows: dict[int, dict[int, str]] = {}
        for index in indexes:
            item = self.item(index.row(), index.column())
            rows.setdefault(index.row(), {})[index.column()] = item.text() if item else ""
        text = "\n".join(
            "\t".join(cols.get(col, "") for col in range(min(cols), max(cols) + 1))
            for _, cols in rows.items()
        )
        QApplication.clipboard().setText(text)

    def open_item(self, value: str):
        text = str(value or "").strip()
        if not text:
            return
        if text.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(text))
            return
        path = Path(text)
        if path.exists():
            QDesktopServices.openUrl(path.resolve().as_uri())


class YandePage(ScrollPage):
    preview_requested = Signal(dict)
    download_requested = Signal(dict)
    cancel_requested = Signal()
    open_folder_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__("yandePage", parent)
        self._busy = False
        self._last_save_root = ""
        self._current_rows: list[dict] = []
        self._page_header(
            "Yande 图片下载",
            "按 Tags、评分、分数与日期筛选 yande.re 图片，下载原图并保存 Tags 元数据。",
            illus="download-illustration.png",
        )

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(self._build_query_card(), 3)
        right_col = QVBoxLayout()
        right_col.setSpacing(14)
        right_col.addWidget(self._build_save_card())
        right_col.addWidget(self._build_action_card())
        body.addLayout(right_col, 2)
        self.root.addLayout(body)
        self.root.addWidget(self._build_results_card())
        self.root.addStretch()

    def _build_query_card(self) -> QWidget:
        card = SurfaceCard("1. 搜索条件", "这里决定从 yande.re 找哪些帖子；不会保存文件。")

        card.body.addWidget(StrongBodyLabel("Yande 登录态 Cookie（可选，用于 E 级内容）"))
        self.cookie_edit = QPlainTextEdit()
        self.cookie_edit.setPlaceholderText(
            "浏览器登录 yande.re 后，复制请求头 Cookie 到这里。\n"
            "不填也能下载公开内容；需要 E 级内容时通常必须填写登录态 Cookie。"
        )
        self.cookie_edit.setMaximumHeight(92)
        self.cookie_edit.setStyleSheet(plain_text_qss())
        card.body.addWidget(self.cookie_edit)
        self.remember_cookie_cb = CheckBox("记住 Cookie（仅保存在本机 config.json）")
        self.remember_cookie_cb.setChecked(True)
        card.body.addWidget(self.remember_cookie_cb)
        card.body.addWidget(_muted("提示：Cookie 等同网页登录态，请不要分享给别人；开源仓库不会包含本地配置。"))

        card.body.addWidget(_divider())
        card.body.addWidget(StrongBodyLabel("Tags 关键词"))
        self.tags_edit = LineEdit()
        self.tags_edit.setPlaceholderText("主要输入 Tags，例如：yuzuna_hiyo animal_ears；也可粘贴单张 Post 链接或 ID")
        self.tags_edit.textChanged.connect(self._clear_preview_cache)
        card.body.addWidget(self.tags_edit)
        card.body.addWidget(_muted(
            "搜索入口固定为 yande.re/post.json?tags=...；粘贴 Post 链接只是单张下载的快捷方式。"
        ))

        self._common_tags_row = QHBoxLayout()
        self._common_tags_row.setSpacing(6)
        card.body.addLayout(self._common_tags_row)
        self.set_common_tags([])

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        grid.addWidget(StrongBodyLabel("评分过滤"), 0, 0)
        self.rating_combo = ComboBox()
        for label, value in [
            ("全部", "all"),
            ("Safe", "safe"),
            ("Questionable", "questionable"),
            ("Explicit（需要登录态）", "explicit"),
        ]:
            self.rating_combo.addItem(label, userData=value)
        grid.addWidget(self.rating_combo, 0, 1)
        self.rating_combo.currentIndexChanged.connect(self._clear_preview_cache)

        grid.addWidget(StrongBodyLabel("最低分数"), 1, 0)
        self.min_score_spin = SpinBox()
        self.min_score_spin.setRange(-9999, 9999)
        self.min_score_spin.setValue(0)
        self.min_score_spin.valueChanged.connect(self._clear_preview_cache)
        grid.addWidget(self.min_score_spin, 1, 1)

        grid.addWidget(StrongBodyLabel("最多加载帖子数"), 2, 0)
        self.limit_spin = SpinBox()
        self.limit_spin.setRange(1, 1000)
        self.limit_spin.setValue(30)
        self.limit_spin.valueChanged.connect(self._clear_preview_cache)
        grid.addWidget(self.limit_spin, 2, 1)

        grid.addWidget(StrongBodyLabel("起始页"), 3, 0)
        self.page_spin = SpinBox()
        self.page_spin.setRange(1, 10000)
        self.page_spin.setValue(1)
        self.page_spin.valueChanged.connect(self._clear_preview_cache)
        grid.addWidget(self.page_spin, 3, 1)

        grid.addWidget(StrongBodyLabel("图片来源"), 4, 0)
        self.source_combo = ComboBox()
        for label, value in [
            ("原图 file_url（最高质量，推荐）", "file"),
            ("View larger / JPEG（高质量 JPG）", "jpeg"),
            ("预览 sample", "sample"),
        ]:
            self.source_combo.addItem(label, userData=value)
        grid.addWidget(self.source_combo, 4, 1)
        self.source_combo.currentIndexChanged.connect(self._clear_preview_cache)
        card.body.addLayout(grid)
        card.body.addWidget(_muted("说明：file_url 对应 yande.re API 里的原始文件地址，通常就是侧边栏 Download larger version。"))

        self.children_cb = CheckBox("搜索时同时包含 child post")
        self.children_cb.setChecked(True)
        self.children_cb.setToolTip("对应页面提示 This post has a child post 时，会额外抓取 parent:<id> 的子图。")
        self.children_cb.stateChanged.connect(self._clear_preview_cache)
        card.body.addWidget(self.children_cb)

        date_row = QHBoxLayout()
        date_row.setSpacing(8)
        self.date_filter_cb = CheckBox("按发布日期筛选")
        self.start_date_edit = DateEdit()
        self.start_date_edit.setDate(QDate.currentDate().addMonths(-1))
        self.start_date_edit.setEnabled(False)
        self.end_date_edit = DateEdit()
        self.end_date_edit.setDate(QDate.currentDate())
        self.end_date_edit.setEnabled(False)
        self.date_filter_cb.stateChanged.connect(self._on_date_filter_changed)
        self.start_date_edit.dateChanged.connect(self._clear_preview_cache)
        self.end_date_edit.dateChanged.connect(self._clear_preview_cache)
        date_row.addWidget(self.date_filter_cb)
        date_row.addWidget(_muted("从", wrap=False))
        date_row.addWidget(self.start_date_edit)
        date_row.addWidget(_muted("到", wrap=False))
        date_row.addWidget(self.end_date_edit)
        date_row.addStretch()
        card.body.addLayout(date_row)

        return card

    def _build_save_card(self) -> QWidget:
        card = SurfaceCard("2. 下载设置", "这里决定文件保存位置和附带信息；搜索预览不会写入文件。")
        card.body.addWidget(StrongBodyLabel("保存目录"))
        path_row = QHBoxLayout()
        self.save_root_edit = LineEdit()
        browse_btn = PushButton("浏览", icon=FIF.FOLDER)
        browse_btn.clicked.connect(self._choose_save_root)
        open_btn = PushButton("打开", icon=FIF.FOLDER)
        open_btn.clicked.connect(lambda: self.open_folder_requested.emit(self.save_root_edit.text().strip()))
        path_row.addWidget(self.save_root_edit, 1)
        path_row.addWidget(browse_btn)
        path_row.addWidget(open_btn)
        card.body.addLayout(path_row)

        card.body.addWidget(StrongBodyLabel("保存模式"))
        self.save_mode_combo = ComboBox()
        self.save_mode_combo.addItem("按 Tags 建文件夹", userData="tag_folder")
        self.save_mode_combo.addItem("全部保存到同一文件夹", userData="flat")
        card.body.addWidget(self.save_mode_combo)

        self.skip_existing_cb = CheckBox("跳过已存在文件")
        self.skip_existing_cb.setChecked(True)
        self.save_ext_info_cb = CheckBox("保存图片扩展信息（IGP sidecar）")
        self.save_ext_info_cb.setChecked(True)
        self.save_ext_info_cb.setToolTip(
            "下载成功后在图片旁边生成 .igp.json，保存 Tags、Post ID、来源链接、评分等信息。"
        )
        for cb in (self.skip_existing_cb, self.save_ext_info_cb):
            card.body.addWidget(cb)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.addWidget(StrongBodyLabel("请求间隔（秒）"), 0, 0)
        self.interval_spin = DoubleSpinBox()
        self.interval_spin.setRange(0.0, 10.0)
        self.interval_spin.setSingleStep(0.1)
        self.interval_spin.setValue(0.3)
        grid.addWidget(self.interval_spin, 0, 1)
        grid.addWidget(StrongBodyLabel("同时下载文件数"), 1, 0)
        self.file_concurrency_spin = SpinBox()
        self.file_concurrency_spin.setRange(1, 8)
        self.file_concurrency_spin.setValue(1)
        self.file_concurrency_spin.setToolTip("同时下载多张图片；网络不稳时建议 1-3。")
        grid.addWidget(self.file_concurrency_spin, 1, 1)
        grid.addWidget(StrongBodyLabel("单文件分片数"), 2, 0)
        self.chunk_threads_spin = SpinBox()
        self.chunk_threads_spin.setRange(1, 32)
        self.chunk_threads_spin.setValue(8)
        self.chunk_threads_spin.setToolTip("使用 HTTP Range 分片下载；服务器不支持时会自动退回普通下载。")
        grid.addWidget(self.chunk_threads_spin, 2, 1)
        card.body.addLayout(grid)
        card.body.addWidget(_muted(
            "稳定下载建议：同时 3 张、间隔 0.3 秒、分片数 8。启用扩展信息后，"
            "每张图会生成：原图 + .igp.json 元数据。"
        ))

        card.body.addStretch()
        return card

    def _build_action_card(self) -> QWidget:
        card = SurfaceCard("3. 操作与状态")
        card.body.addWidget(_muted("先用“搜索预览”确认结果；确认无误后再点“开始下载”。"))
        self.status_label = _muted("等待搜索。")
        card.body.addWidget(self.status_label)
        self.progress_bar = ProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        card.body.addWidget(self.progress_bar)

        action_row = QHBoxLayout()
        self.preview_btn = PushButton("搜索预览", icon=FIF.SEARCH)
        self.download_btn = PrimaryPushButton("下载当前结果", icon=FIF.DOWNLOAD)
        self.download_btn.setToolTip("如果表格里已有预览结果，会直接下载这些结果；否则先按当前条件搜索再下载。")
        self.cancel_btn = PushButton("停止", icon=FIF.CANCEL)
        self.cancel_btn.setEnabled(False)
        self.preview_btn.clicked.connect(lambda: self.preview_requested.emit(self.params()))
        self.download_btn.clicked.connect(lambda: self.download_requested.emit(self.params()))
        self.cancel_btn.clicked.connect(self.cancel_requested)
        action_row.addWidget(self.preview_btn)
        action_row.addWidget(self.download_btn)
        action_row.addWidget(self.cancel_btn)
        card.body.addLayout(action_row)
        card.body.addStretch()
        return card

    def _build_results_card(self) -> QWidget:
        card = SurfaceCard("搜索结果 / 下载结果", "未预览时点击下载会先按当前条件搜索。")
        self.table = CopyableResultTable(0, 8)
        self.table.setHorizontalHeaderLabels(["ID", "关系", "评分", "分数", "尺寸", "Tags", "状态", "文件/链接"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(0, 82)
        self.table.setColumnWidth(1, 88)
        self.table.setColumnWidth(2, 70)
        self.table.setColumnWidth(3, 62)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(6, 82)
        self.table.setMinimumHeight(340)
        self.table.refresh_theme()
        card.body.addWidget(self.table)
        return card

    def _on_date_filter_changed(self):
        enabled = self.date_filter_cb.isChecked()
        self.start_date_edit.setEnabled(enabled)
        self.end_date_edit.setEnabled(enabled)
        self._clear_preview_cache()

    def _clear_preview_cache(self):
        self._current_rows = []
        if hasattr(self, "status_label") and not self._busy:
            if hasattr(self, "table"):
                self.table.setRowCount(0)
            if hasattr(self, "progress_bar"):
                self.progress_bar.setRange(0, 1)
                self.progress_bar.setValue(0)
            self.status_label.setText("搜索条件已变化，请重新预览，或直接按当前条件下载。")

    def _choose_save_root(self):
        path = QFileDialog.getExistingDirectory(self, "选择 Yande 图片保存目录", self.save_root_edit.text())
        if path:
            self.save_root_edit.setText(path)

    def set_defaults(self, save_root: str, cookie: str = "", tags: str = "", common_tags: list[str] | None = None):
        self.save_root_edit.setText(save_root)
        self._last_save_root = save_root
        self.cookie_edit.setPlainText(cookie)
        self.tags_edit.setText(tags)
        self.set_common_tags(common_tags or [])

    def set_common_tags(self, tags: list[str]):
        while self._common_tags_row.count():
            item = self._common_tags_row.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        shown = [tag for tag in tags if tag][:10]
        if not shown:
            self._common_tags_row.addWidget(_muted("常用 Yande Tags：暂无"))
        else:
            self._common_tags_row.addWidget(_muted("常用 Yande Tags：", wrap=False))
            for tag in shown:
                pill = TagPill(tag if tag.startswith("#") else f"#{tag}")
                pill.clicked.connect(lambda checked=False, value=tag: self.tags_edit.setText(value.lstrip("#")))
                self._common_tags_row.addWidget(pill)
        self._common_tags_row.addStretch()

    def params(self) -> dict:
        params = {
            "cookie": self.cookie_edit.toPlainText().strip(),
            "remember_cookie": self.remember_cookie_cb.isChecked(),
            "tags": self.tags_edit.text().strip(),
            "rating": self.rating_combo.currentData(),
            "min_score": int(self.min_score_spin.value()),
            "limit": int(self.limit_spin.value()),
            "page": int(self.page_spin.value()),
            "image_source": self.source_combo.currentData(),
            "include_children": self.children_cb.isChecked(),
            "save_root": self.save_root_edit.text().strip(),
            "save_mode": self.save_mode_combo.currentData(),
            "skip_existing": self.skip_existing_cb.isChecked(),
            "save_extended_info": self.save_ext_info_cb.isChecked(),
            "interval": float(self.interval_spin.value()),
            "file_concurrency": int(self.file_concurrency_spin.value()),
            "chunk_threads": int(self.chunk_threads_spin.value()),
            "rows": list(self._current_rows),
        }
        if self.date_filter_cb.isChecked():
            start = self.start_date_edit.date()
            end = self.end_date_edit.date()
            if start > end:
                start, end = end, start
            params["date_from"] = start.toString("yyyy-MM-dd")
            params["date_to"] = end.toString("yyyy-MM-dd")
        return params

    def set_busy(self, busy: bool):
        self._busy = busy
        self.preview_btn.setEnabled(not busy)
        self.download_btn.setEnabled(not busy)
        self.cancel_btn.setEnabled(busy)
        if busy:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, max(1, self.progress_bar.maximum()))

    def set_progress(self, completed: int, total: int, message: str):
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(min(completed, max(1, total)))
        self.status_label.setText(message)

    def set_rows(self, rows: list[dict]):
        self._current_rows = [dict(row) for row in rows]
        self.table.setRowCount(0)
        for row_data in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                str(row_data.get("id", "")),
                str(row_data.get("relation", "")),
                str(row_data.get("rating", "")),
                str(row_data.get("score", "")),
                str(row_data.get("size", "")),
                str(row_data.get("tags", "")),
                str(row_data.get("status", "")),
                str(row_data.get("post_url", "")),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 38)
        self.status_label.setText(f"已加载 {len(rows)} 条结果。")

    def update_row(self, index: int, status: str, message: str):
        if index < 0 or index >= self.table.rowCount():
            return
        self.table.setItem(index, 6, QTableWidgetItem(status))
        item = QTableWidgetItem(message)
        item.setToolTip(message)
        self.table.setItem(index, 7, item)

    def refresh_theme(self):
        self.cookie_edit.setStyleSheet(plain_text_qss())
        self.table.refresh_theme()
