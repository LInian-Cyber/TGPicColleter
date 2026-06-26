from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QCursor

from .common import *
from .common import _UI_DIR, _asset, _divider, _img_label, _muted, _set_margins


class _TaskDetailTip(QFrame):
    def __init__(self):
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._label = QLabel("")
        self._label.setWordWrap(True)
        self._label.setMaximumWidth(560)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.addWidget(self._label)
        self.refresh_theme()

    def refresh_theme(self):
        if isDarkTheme():
            background, foreground, border = "#252a34", "#f5f7fb", "#3f4756"
        else:
            background, foreground, border = "#ffffff", "#142033", "#dbe3f1"
        self.setStyleSheet(
            "QFrame{"
            f"background:{background};border:1px solid {border};border-radius:10px;"
            "}"
            "QLabel{"
            f"color:{foreground};background:transparent;border:none;font-size:12px;"
            "}"
        )

    def show_text(self, text: str):
        if not text:
            self.hide()
            return
        self._label.setText(text)
        self.adjustSize()
        pos = QCursor.pos() + QPoint(16, 18)
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            pos.setX(min(max(rect.left() + 6, pos.x()), rect.right() - self.width() - 6))
            pos.setY(min(max(rect.top() + 6, pos.y()), rect.bottom() - self.height() - 6))
        self.move(pos)
        self.show()


class HistoryPage(ScrollPage):
    clear_requested = Signal()
    open_folder_requested = Signal()
    pause_task_requested = Signal(int)
    delete_task_requested = Signal(int)
    delete_history_requested = Signal(int)
    pause_all_requested = Signal()
    clear_queue_requested = Signal()
    open_log_requested = Signal()
    open_log_folder_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("historyPage", parent)
        self._raw_log_content = ""
        self._active_task_tips: dict[int, str] = {}
        self._detail_tip = _TaskDetailTip()
        self._page_header("任务与历史", "集中查看当前任务、下载记录与运行日志",
                          illus="download-illustration.png")

        self._seg = SegmentedWidget()
        self._stack = QStackedWidget()
        tabs = [
            ("当前任务", self._build_active_tasks()),
            ("历史记录", self._build_history()),
            ("运行日志", self._build_log()),
        ]
        for index, (name, widget) in enumerate(tabs):
            self._stack.addWidget(widget)
            self._seg.addItem(
                routeKey=f"history_tab_{index}",
                text=name,
                onClick=lambda checked=False, idx=index: self._stack.setCurrentIndex(idx),
            )
        self._seg.setCurrentItem("history_tab_0")
        self.root.addWidget(self._seg)
        self.root.addWidget(self._stack)
        self.root.addStretch()

    def _build_active_tasks(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(page)
        _set_margins(layout, (0, 12, 0, 0), 14)
        card = SurfaceCard()

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("当前任务"))
        self._queue_count_badge = QLabel("0")
        self._queue_count_badge.setStyleSheet(
            f"background:{C_BLUE};color:white;border-radius:9px;"
            "padding:0 6px;font-size:11px;font-weight:700;"
        )
        self._queue_count_badge.setFixedHeight(18)
        header.addWidget(self._queue_count_badge)
        header.addStretch()
        pause_all_btn = PushButton("全部暂停", icon=FIF.PAUSE)
        clear_queue_btn = PushButton("清空任务", icon=FIF.DELETE)
        pause_all_btn.clicked.connect(self.pause_all_requested)
        clear_queue_btn.clicked.connect(self.clear_queue_requested)
        header.addWidget(pause_all_btn)
        header.addWidget(clear_queue_btn)
        card.body.addLayout(header)
        card.body.addWidget(_muted("将鼠标放到进度条上，可查看每条已发现帖子的处理状态。"))

        self._queue_table = PassiveTableWidget(0, 6)
        self._queue_table.setHorizontalHeaderLabels(
            ["任务名称", "关键词", "状态", "下载进度", "文件结果", "操作"])
        self._queue_table.verticalHeader().hide()
        self._queue_table.horizontalHeader().setStretchLastSection(False)
        self._queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._queue_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self._queue_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._queue_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._queue_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        self._queue_table.setColumnWidth(1, 90)
        self._queue_table.setColumnWidth(2, 70)
        self._queue_table.setColumnWidth(3, 160)
        self._queue_table.setColumnWidth(5, 72)
        self._queue_table.setShowGrid(False)
        self._queue_table.setAlternatingRowColors(False)
        self._queue_table.setMinimumHeight(300)
        self._queue_table.refresh_theme()
        self._queue_table.viewport().setMouseTracking(True)
        self._queue_table.viewport().installEventFilter(self)
        card.body.addWidget(self._queue_table)
        layout.addWidget(card)
        return page

    def _build_history(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(page)
        _set_margins(layout, (0, 12, 0, 0), 14)
        card = SurfaceCard()
        acts = QHBoxLayout()
        acts.addStretch()
        open_btn = PushButton("打开保存目录", icon=FIF.FOLDER)
        clear_btn = PushButton("清空历史", icon=FIF.DELETE)
        clear_btn.setMinimumHeight(36)  # 顺手统一下高度
        open_btn.clicked.connect(self.open_folder_requested)
        clear_btn.clicked.connect(self.clear_requested)
        acts.addWidget(open_btn)
        acts.addWidget(clear_btn)
        card.body.addLayout(acts)

        self._table = PassiveTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            ["频道", "Tag", "状态", "匹配帖子", "下载图片", "完成时间", "操作"])
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(6, 58)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        self._table.setMinimumHeight(420)
        self._table.refresh_theme()
        card.body.addWidget(self._table)
        layout.addWidget(card)
        return page

    def _build_log(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(page)
        _set_margins(layout, (0, 12, 0, 0), 14)
        card = SurfaceCard("运行日志", "下载、跳过、失败与帖子扫描结果会写入按日期生成的日志文件。")
        actions = QHBoxLayout()
        self._log_path_label = _muted("日志文件：-")
        self._log_path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        actions.addWidget(self._log_path_label, 1)
        self._log_filter_combo = ComboBox()
        for text, key in [
            ("全部日志", "all"),
            ("只看错误", "error"),
            ("高级规则", "advanced"),
            ("下载结果", "download"),
        ]:
            self._log_filter_combo.addItem(text, userData=key)
        self._log_filter_combo.currentIndexChanged.connect(self._apply_log_filter)
        actions.addWidget(self._log_filter_combo)
        open_file_btn = PushButton("打开日志文件", icon=FIF.DOCUMENT)
        open_folder_btn = PushButton("打开日志目录", icon=FIF.FOLDER)
        open_file_btn.clicked.connect(self.open_log_requested)
        open_folder_btn.clicked.connect(self.open_log_folder_requested)
        actions.addWidget(open_file_btn)
        actions.addWidget(open_folder_btn)
        card.body.addLayout(actions)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMinimumHeight(420)
        self._log_view.setPlaceholderText("日志会在任务开始后显示在这里。")
        self._log_view.setStyleSheet(plain_text_qss())
        card.body.addWidget(self._log_view)
        layout.addWidget(card)
        return page

    @staticmethod
    def _post_tooltip(task: TaskRow) -> str:
        if not task.post_statuses:
            return "尚未发现帖子。扫描到帖子后，会在这里显示已完成与未完成状态。"
        lines = ["帖子处理明细："]
        for post_id, status in list(task.post_statuses.items())[-50:]:
            lines.append(f"帖子 #{post_id}：{status}")
        if len(task.post_statuses) > 50:
            lines.append(f"……另有 {len(task.post_statuses) - 50} 条较早记录")
        return "\n".join(lines)

    def _install_task_tip(self, widget: QWidget, row: int):
        widget.setMouseTracking(True)
        widget.setProperty("taskDetailTipRow", row)
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        event_type = event.type()
        queue_table = getattr(self, "_queue_table", None)
        if queue_table is not None and watched is queue_table.viewport():
            if event_type == QEvent.Type.MouseMove:
                index = queue_table.indexAt(event.position().toPoint())
                if index.isValid() and index.column() in (3, 4):
                    self._detail_tip.show_text(self._active_task_tips.get(index.row(), ""))
                else:
                    self._detail_tip.hide()
            elif event_type in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._detail_tip.hide()
        row = watched.property("taskDetailTipRow") if hasattr(watched, "property") else None
        if row is not None:
            if event_type in (QEvent.Type.Enter, QEvent.Type.MouseMove):
                self._detail_tip.show_text(self._active_task_tips.get(int(row), ""))
            elif event_type in (QEvent.Type.Leave, QEvent.Type.Hide):
                self._detail_tip.hide()
        return super().eventFilter(watched, event)

    def set_active_tasks(self, tasks: list[TaskRow]):
        self._detail_tip.hide()
        self._active_task_tips.clear()
        self._queue_table.setUpdatesEnabled(False)
        self._queue_table.setRowCount(0)
        self._queue_count_badge.setText(str(len(tasks)))
        status_colors = {
            "下载中": C_BLUE, "排队中": C_ORANGE,
            "已暂停": C_MUTED, "已完成": C_GREEN, "已取消": C_MUTED,
        }
        for index, task in enumerate(tasks):
            row = self._queue_table.rowCount()
            self._queue_table.insertRow(row)
            self._queue_table.setItem(row, 0, QTableWidgetItem(task.name))
            self._queue_table.setItem(row, 1, QTableWidgetItem(task.keyword))

            status_item = QTableWidgetItem(task.status)
            status_item.setForeground(QColor(status_colors.get(task.status, C_MUTED)))
            self._queue_table.setItem(row, 2, status_item)

            tooltip = self._post_tooltip(task)
            full_tip = tooltip
            progress_widget = QWidget()
            progress_layout = QHBoxLayout(progress_widget)
            progress_layout.setContentsMargins(4, 10, 4, 10)
            bar = InlineProgress(task.progress)
            percent = QLabel(f"{task.progress}%")
            percent.setStyleSheet(f"color:{C_MUTED};font-size:11px;")
            percent.setFixedWidth(36)
            progress_layout.addWidget(bar, 1)
            progress_layout.addWidget(percent)
            self._install_task_tip(progress_widget, row)
            self._install_task_tip(bar, row)
            self._install_task_tip(percent, row)
            self._queue_table.setCellWidget(row, 3, progress_widget)

            skipped = getattr(task, "skipped", 0)
            completed = task.downloaded + skipped
            total_text = str(task.total) if task.total > 0 else "扫描中"
            result_item = QTableWidgetItem(
                f"已完成 {completed} / 总数 {total_text} "
                f"(下载 {task.downloaded} / 跳过 {skipped})"
            )
            metrics_text = str(getattr(task, "metrics_text", "") or "")
            if metrics_text:
                result_item.setText(f"{result_item.text()}\n{metrics_text}")
                full_tip = f"{tooltip}\n{metrics_text}"
            self._active_task_tips[row] = full_tip
            self._queue_table.setItem(row, 4, result_item)

            ops_widget = QWidget()
            ops_layout = QHBoxLayout(ops_widget)
            ops_layout.setContentsMargins(4, 4, 4, 4)
            ops_layout.setSpacing(4)
            # 暂停/继续 按钮：根据当前状态切换图标和 tooltip
            is_paused = task.status == "已暂停"
            pause_icon = FIF.PLAY if is_paused else FIF.PAUSE
            pause_tip  = "继续" if is_paused else "暂停"
            pause_btn = ToolButton(pause_icon)
            pause_btn.setFixedSize(28, 28)
            pause_btn.setToolTip(pause_tip)
            pause_btn.clicked.connect(lambda _, idx=index: self.pause_task_requested.emit(idx))
            delete_btn = ToolButton(FIF.DELETE)
            delete_btn.setFixedSize(28, 28)
            delete_btn.setToolTip("删除")
            delete_btn.clicked.connect(
                lambda checked=False, idx=index: self.delete_task_requested.emit(idx)
            )
            ops_layout.addWidget(pause_btn)
            ops_layout.addWidget(delete_btn)
            self._queue_table.setCellWidget(row, 5, ops_widget)
            self._queue_table.setRowHeight(row, 56 if metrics_text else 44)
        self._queue_table.setUpdatesEnabled(True)

    def set_log(self, path: str, content: str):
        self._log_path_label.setText(f"日志文件：{path}")
        self._raw_log_content = content
        self._apply_log_filter()
        scrollbar = self._log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def refresh_theme(self):
        self._queue_table.refresh_theme()
        self._table.refresh_theme()
        self._log_view.setStyleSheet(plain_text_qss())
        self._log_view.viewport().update()
        self._detail_tip.refresh_theme()

    def _apply_log_filter(self):
        content = self._raw_log_content
        mode = self._log_filter_combo.currentData() if hasattr(self, "_log_filter_combo") else "all"
        if mode != "all":
            markers = {
                "error": ("[ERROR]", "ERROR", "失败", "错误", "Exception"),
                "advanced": ("高级", "深度", "正文链接", "评论区", "跃迁", "Telegram 内部链接"),
                "download": ("已下载", "下载", "跳过", "已完成", "保存真实媒体"),
            }.get(mode, ())
            lines = [
                line for line in content.splitlines()
                if any(marker in line for marker in markers)
            ]
            content = "\n".join(lines) if lines else "当前筛选条件下暂无日志。"
        self._log_view.setPlainText(content)
        scrollbar = self._log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_rows(self, rows: list[HistoryRow]):
        self._table.setRowCount(0)
        for index, rec in enumerate(rows):
            r = self._table.rowCount()
            self._table.insertRow(r)
            vals = [
                rec.channel,
                rec.tag or "未分类",
                rec.status,
                str(rec.posts),
                str(rec.downloaded),
                rec.time,
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 2:
                    color = {
                        "已完成": C_GREEN, "下载中": C_BLUE,
                        "已暂停": C_ORANGE, "已取消": C_MUTED,
                        "失败": "#e53935",
                    }.get(v, C_MUTED)
                    item.setForeground(QColor(color))
                self._table.setItem(r, c, item)
            delete_btn = ToolButton(FIF.DELETE)
            delete_btn.setFixedSize(28, 28)
            delete_btn.setToolTip("删除这条历史记录")
            delete_btn.clicked.connect(
                lambda checked=False, idx=index: self.delete_history_requested.emit(idx)
            )
            ops_widget = QWidget()
            ops_layout = QHBoxLayout(ops_widget)
            ops_layout.setContentsMargins(4, 4, 4, 4)
            ops_layout.addStretch()
            ops_layout.addWidget(delete_btn)
            ops_layout.addStretch()
            self._table.setCellWidget(r, 6, ops_widget)
            self._table.setRowHeight(r, 38)
