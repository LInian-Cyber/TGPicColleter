from __future__ import annotations

from .common import *
from .common import _UI_DIR, _asset, _divider, _img_label, _muted, _set_margins

class HistoryPage(ScrollPage):
    clear_requested = Signal()
    open_folder_requested = Signal()
    pause_task_requested = Signal(int)
    delete_task_requested = Signal(int)
    pause_all_requested = Signal()
    clear_queue_requested = Signal()
    open_log_requested = Signal()
    open_log_folder_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("historyPage", parent)
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
        self._queue_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._queue_table.setShowGrid(False)
        self._queue_table.setAlternatingRowColors(False)
        self._queue_table.setMinimumHeight(300)
        self._queue_table.setStyleSheet(
            "QTableWidget{border:none;background:transparent;}"
            "QTableWidget::item:selected,QTableWidget::item:hover{background:transparent;}"
        )
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

        self._table = PassiveTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["频道", "Tag", "状态", "匹配帖子", "下载图片", "完成时间"])
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(False)
        self._table.setMinimumHeight(420)
        self._table.setStyleSheet(
            "QTableWidget{border:none;background:transparent;}"
            "QTableWidget::item:selected,QTableWidget::item:hover{background:transparent;}"
        )
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

    def set_active_tasks(self, tasks: list[TaskRow]):
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
            progress_widget = QWidget()
            progress_widget.setToolTip(tooltip)
            progress_layout = QHBoxLayout(progress_widget)
            progress_layout.setContentsMargins(4, 10, 4, 10)
            bar = InlineProgress(task.progress)
            bar.setToolTip(tooltip)
            percent = QLabel(f"{task.progress}%")
            percent.setToolTip(tooltip)
            percent.setStyleSheet(f"color:{C_MUTED};font-size:11px;")
            percent.setFixedWidth(36)
            progress_layout.addWidget(bar, 1)
            progress_layout.addWidget(percent)
            self._queue_table.setCellWidget(row, 3, progress_widget)

            skipped = getattr(task, "skipped", 0)
            completed = task.downloaded + skipped
            result_item = QTableWidgetItem(f"已完成 {completed} / 共 {task.total} (下载 {task.downloaded} / 跳过 {skipped})")
            result_item.setToolTip(tooltip)
            self._queue_table.setItem(row, 4, result_item)

            ops_widget = QWidget()
            ops_layout = QHBoxLayout(ops_widget)
            ops_layout.setContentsMargins(4, 4, 4, 4)
            ops_layout.setSpacing(4)
            pause_btn = ToolButton(FIF.PAUSE)
            pause_btn.setFixedSize(28, 28)
            pause_btn.clicked.connect(lambda _, idx=index: self.pause_task_requested.emit(idx))
            delete_btn = ToolButton(FIF.DELETE)
            delete_btn.setFixedSize(28, 28)
            delete_btn.clicked.connect(lambda _, idx=index: self.delete_task_requested.emit(idx))
            ops_layout.addWidget(pause_btn)
            ops_layout.addWidget(delete_btn)
            self._queue_table.setCellWidget(row, 5, ops_widget)
            self._queue_table.setRowHeight(row, 44)
        self._queue_table.setUpdatesEnabled(True)

    def set_log(self, path: str, content: str):
        self._log_path_label.setText(f"日志文件：{path}")
        self._log_view.setPlainText(content)
        scrollbar = self._log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_rows(self, rows: list[HistoryRow]):
        self._table.setRowCount(0)
        for rec in rows:
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
            self._table.setRowHeight(r, 38)
