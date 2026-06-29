from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import QMenu

from .. import __version__
from ..i18n import apply_language as apply_widget_language, translate
from .common import *
from .common import _UI_DIR
from .about import AboutPage
from .export import ExportPage
from .history import HistoryPage
from .home import HomePage
from .login import LoginPage
from .settings import SettingsPage
from .task import TaskPage
from .yande import YandePage

class MainWindow(FluentWindow):
    """
    纯视图主窗口。

    职责：
    - 组装所有子页面
    - 连接页面间的导航 Signal
    - 暴露统一的 setter API 供外部（controller）调用
    - 通过 Signal 将用户操作通知给外部

    不得直接引用任何业务层对象（TelegramWorker、AppConfig 等）。
    """

    # ── 对外暴露的顶级 Signals（透传自子页面，外部直接监听）
    # 任务
    task_start_requested = Signal(dict)
    task_cancel_requested = Signal()
    task_pause_requested = Signal(int)
    task_delete_requested = Signal(int)
    task_preview_requested = Signal(dict)
    task_preview_cancel_requested = Signal()
    task_preview_download_requested = Signal(list)
    task_pause_all_requested = Signal()
    task_clear_queue_requested = Signal()
    tray_pause_requested = Signal()
    tray_resume_requested = Signal()
    tray_stop_requested = Signal()
    tray_quit_requested = Signal()
    # 登录
    send_code_requested = Signal(str)
    login_requested = Signal(str, str, str)
    qr_requested = Signal()
    logout_requested = Signal()
    account_switch_requested = Signal(str)
    account_add_requested = Signal()
    # 设置
    settings_save_requested = Signal(dict)
    settings_network_test_requested = Signal(dict)
    settings_data_dir_open_requested = Signal()
    settings_logout_requested = Signal()
    settings_cache_clear_requested = Signal()
    settings_channel_cache_refresh_requested = Signal()
    settings_channel_cache_delete_requested = Signal(str)
    settings_channel_cache_clear_requested = Signal()
    close_behavior_changed = Signal(str, bool)
    # 导出
    export_requested = Signal(dict)
    export_open_output_requested = Signal(str)
    # Yande
    yande_preview_requested = Signal(dict)
    yande_download_requested = Signal(dict)
    yande_cancel_requested = Signal()
    yande_open_folder_requested = Signal(str)
    # 通用
    open_folder_requested = Signal()
    open_log_requested = Signal()
    open_log_folder_requested = Signal()
    history_clear_requested = Signal()
    history_delete_requested = Signal(int)
    history_open_folder_requested = Signal(str)
    trend_period_changed = Signal(str)
    # 窗口关闭
    window_closing = Signal()

    def __init__(self):
        self._app_tooltip_filter_ready = False
        super().__init__()

        # 子页面
        self.home_page = HomePage()
        self.task_page = TaskPage()
        self.login_page = LoginPage()
        self.history_page = HistoryPage()
        self.export_page = ExportPage()
        self.yande_page = YandePage()
        self.settings_page = SettingsPage()
        self.about_page = AboutPage()
        self._preview_dialog: SearchPreviewDialog | None = None
        self._closing = False
        self._tray_icon: QSystemTrayIcon | None = None
        self._tray_menu: QMenu | None = None
        self._tray_status_action: QAction | None = None
        self._tray_pause_action: QAction | None = None
        self._tray_resume_action: QAction | None = None
        self._tray_stop_action: QAction | None = None
        self._system_notifications_enabled = True
        self._close_behavior = "ask"
        self._remember_close_behavior = False
        self._initially_centered = False
        self._language = "zh_CN"
        self._sidebar_width = 280
        self._sidebar_min_width = 220
        self._sidebar_max_width = 420
        self._sidebar_dragging = False
        self._sidebar_drag_start_x = 0
        self._sidebar_drag_start_width = self._sidebar_width
        self._sidebar_resize_grip: QFrame | None = None

        # 注册导航
        self.addSubInterface(self.home_page,     FIF.HOME,     "首页")
        self.addSubInterface(self.task_page,     FIF.DOWNLOAD, "下载任务")
        self.addSubInterface(self.login_page,    FIF.PEOPLE,   "登录中心")
        self.addSubInterface(self.history_page,  FIF.HISTORY,  "下载历史")
        self.addSubInterface(self.yande_page,    FIF.PHOTO,    "Yande")
        self.addSubInterface(self.export_page,   FIF.SAVE,     "导出")
        self.addSubInterface(self.settings_page, FIF.SETTING,  "设置")
        self.addSubInterface(self.about_page,    FIF.INFO,     "关于")

        # 底部导航按钮：主题切换
        self.navigationInterface.addItem(
            routeKey="themeItem",
            icon=FIF.BRUSH,
            text="切换主题",
            onClick=self._toggle_theme,
            position=NavigationItemPosition.BOTTOM,
            tooltip="切换深色/浅色模式"
        )

        # 底部导航按钮：版本信息
        self.navigationInterface.addItem(
            routeKey="versionItem",
            icon=FIF.ACCEPT,
            text=f"v{__version__}",
            onClick=lambda: self.switchTo(self.about_page),
            position=NavigationItemPosition.BOTTOM
        )

        # 窗口属性
        icon_path = _UI_DIR / "telegram-app-icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon = QSystemTrayIcon(self.windowIcon(), self)
            self._tray_icon.setToolTip("TG Pic Collector")
            self._tray_icon.activated.connect(self._on_tray_activated)
            self._tray_icon.messageClicked.connect(self._restore_from_notification)
            self._build_tray_menu()
            self._tray_icon.show()
        self.setWindowTitle("Telegram 评论区图片下载器")
        self.resize(1440, 900)
        self.setMinimumSize(1200, 760)
        self.navigationInterface.setExpandWidth(self._sidebar_width)
        self.navigationInterface.setMinimumExpandWidth(1080)
        self.navigationInterface.expand(useAni=False)
        self._build_sidebar_resize_grip()

        self._wire_internal()
        apply_tooltip_theme()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)
        self._app_tooltip_filter_ready = True

    def _wire_internal(self):
        """连接子页面 Signal → 顶级 Signal 或页面切换（纯 UI 内部路由）"""
        # 首页导航
        self.home_page.new_task_requested.connect(lambda: self.switchTo(self.task_page))
        self.home_page.resume_task_requested.connect(lambda: self.switchTo(self.task_page))
        self.home_page.login_requested.connect(lambda: self.switchTo(self.login_page))
        self.home_page.history_requested.connect(lambda: self.switchTo(self.history_page))
        self.home_page.settings_requested.connect(lambda: self.switchTo(self.settings_page))
        self.home_page.trend_period_changed.connect(self.trend_period_changed)
        self.home_page.common_tag_requested.connect(self._open_tag_task)
        self.home_page.open_folder_requested.connect(self.open_folder_requested)
        # 任务页
        self.task_page.start_requested.connect(self.task_start_requested)
        self.task_page.cancel_requested.connect(self.task_cancel_requested)
        self.task_page.switch_account_requested.connect(lambda: self.switchTo(self.login_page))
        self.task_page.settings_requested.connect(lambda: self.switchTo(self.settings_page))
        self.task_page.preview_requested.connect(self.task_preview_requested)
        # 登录页
        self.login_page.send_code_requested.connect(self.send_code_requested)
        self.login_page.login_requested.connect(self.login_requested)
        self.login_page.qr_requested.connect(self.qr_requested)
        self.login_page.logout_requested.connect(self.logout_requested)
        self.login_page.account_switch_requested.connect(self.account_switch_requested)
        self.login_page.account_add_requested.connect(self.account_add_requested)
        # 历史页
        self.history_page.clear_requested.connect(self.history_clear_requested.emit)
        self.history_page.delete_history_requested.connect(self.history_delete_requested.emit)
        self.history_page.open_history_folder_requested.connect(
            self.history_open_folder_requested.emit
        )
        self.history_page.open_folder_requested.connect(self.open_folder_requested.emit)
        self.history_page.pause_task_requested.connect(self.task_pause_requested.emit)
        self.history_page.delete_task_requested.connect(self.task_delete_requested.emit)
        self.history_page.pause_all_requested.connect(self.task_pause_all_requested.emit)
        self.history_page.clear_queue_requested.connect(self.task_clear_queue_requested.emit)
        self.history_page.open_log_requested.connect(self.open_log_requested.emit)
        self.history_page.open_log_folder_requested.connect(self.open_log_folder_requested.emit)
        # 导出页
        self.export_page.export_requested.connect(self.export_requested.emit)
        self.export_page.open_output_requested.connect(self.export_open_output_requested.emit)
        # Yande 页
        self.yande_page.preview_requested.connect(self.yande_preview_requested.emit)
        self.yande_page.download_requested.connect(self.yande_download_requested.emit)
        self.yande_page.cancel_requested.connect(self.yande_cancel_requested.emit)
        self.yande_page.open_folder_requested.connect(self.yande_open_folder_requested.emit)
        # 设置页
        self.settings_page.save_requested.connect(self.settings_save_requested)
        self.settings_page.network_test_requested.connect(self.settings_network_test_requested)
        self.settings_page.data_dir_open_requested.connect(self.settings_data_dir_open_requested)
        self.settings_page.logout_requested.connect(self.settings_logout_requested)
        self.settings_page.cache_clear_requested.connect(self.settings_cache_clear_requested)
        self.settings_page.channel_cache_refresh_requested.connect(
            self.settings_channel_cache_refresh_requested.emit
        )
        self.settings_page.channel_cache_delete_requested.connect(
            self.settings_channel_cache_delete_requested.emit
        )
        self.settings_page.channel_cache_clear_requested.connect(
            self.settings_channel_cache_clear_requested.emit
        )
        self.settings_page.language_preview_requested.connect(self.apply_language)

    # ──────────────────────────────────────────────────────────
    #  公开 Setter API（Controller 调用这些方法推数据入 UI）
    # ──────────────────────────────────────────────────────────

    def set_account(self, name: str = "", phone: str = "", dc: str = ""):
        """更新所有页面的账号状态"""
        self.home_page.set_account(name, phone)
        self.task_page.set_account(name, phone, dc)
        self.login_page.set_account(name, phone)
        if not name:
            self.set_user_avatar(b"")

    def set_user_avatar(self, avatar_bytes: bytes):
        self.home_page.set_user_avatar(avatar_bytes)
        self.task_page.set_user_avatar(avatar_bytes)
        self.login_page.set_user_avatar(avatar_bytes)

    def set_account_sessions(self, rows: list[dict], current_key: str = ""):
        self.login_page.set_account_sessions(rows, current_key)

    def set_home_stats(self, today: int, total: int, tasks: int,
                       tags: int, disk_str: str, last_active: str):
        self.home_page.set_stats(today, total, tasks, tags, disk_str, last_active)

    def set_home_trend(self, values: list[int]):
        self.home_page.set_trend(values)

    def set_home_trend_with_labels(self, values: list[int], labels: list[str]):
        self.home_page.set_trend(values, labels)

    def set_home_recent_tasks(self, rows: list[dict]):
        self.home_page.set_recent_tasks(rows)

    def set_summary(self, save_root: str, save_mode_label: str):
        self.home_page.set_summary(save_root, save_mode_label)

    def set_common_tags(self, tags: list[str]):
        self.home_page.set_common_tags(tags)
        self.task_page.set_common_tags(tags)

    def set_task_defaults(
        self,
        save_root: str,
        save_mode_label: str,
        save_mode_key: str = "",
        save_extended_info: bool = False,
        open_after_download: bool = False,
        skip_duplicates: bool = True,
    ):
        self.task_page.set_defaults(
            save_root,
            save_mode_label,
            save_mode_key,
            save_extended_info,
            open_after_download,
            skip_duplicates,
        )

    def set_task_rule_summary(
        self,
        filename_template: str,
        preserve_original_name: bool,
        duplicate_mode: str,
        open_after_download: bool,
        concurrency: int,
        chunk_concurrency: int,
        file_download_interval: float,
        filename_limit: int,
        empty_tag_action: str = "uncategorized",
    ):
        self.task_page.set_rule_summary(
            filename_template,
            preserve_original_name,
            duplicate_mode,
            open_after_download,
            concurrency,
            chunk_concurrency,
            file_download_interval,
            filename_limit,
            empty_tag_action,
        )

    def set_task_busy(self, busy: bool):
        self.task_page.set_busy(busy)

    def set_task_detail(self, text: str):
        self.task_page.set_detail(text)

    def set_task_progress(self, downloaded: int, skipped: int, total: int):
        self.task_page.set_progress(downloaded, skipped, total)

    def show_search_preview_loading(self, channel: str, tag: str):
        if self._preview_dialog:
            self._preview_dialog.reject()
        self._preview_dialog = SearchPreviewDialog(channel, tag, self)
        self._preview_dialog.cancel_requested.connect(self.task_preview_cancel_requested)
        self._preview_dialog.download_requested.connect(self.task_preview_download_requested)
        self._preview_dialog.show()
        self.task_page.set_preview_busy(True)

    def set_search_preview_progress(self, message: str):
        if self._preview_dialog:
            self._preview_dialog.set_progress(message)

    def set_search_preview_results(
        self, rows: list[dict], total_count: int, display_limit: int
    ):
        self.task_page.set_preview_busy(False)
        if self._preview_dialog:
            self._preview_dialog.set_results(rows, total_count, display_limit)

    def set_search_preview_error(self, message: str):
        self.task_page.set_preview_busy(False)
        if self._preview_dialog:
            self._preview_dialog.set_error(message)

    def set_task_queue(self, tasks: list[TaskRow]):
        self.history_page.set_active_tasks(tasks)

    def show_qr(self, url: str):
        self.login_page.show_qr(url)

    def set_qr_message(self, message: str, allow_auto_retry: bool = False):
        self.login_page.set_qr_message(message, allow_auto_retry)

    def set_login_phone(self, phone: str):
        self.login_page.set_phone(phone)

    def set_history(self, rows: list[HistoryRow]):
        self.history_page.set_rows(rows)

    def set_log(self, path: str, content: str):
        self.history_page.set_log(path, content)

    def set_export_result(self, summary: str, rows: list[dict]):
        self.export_page.set_export_result(summary, rows)

    def set_yande_defaults(self, save_root: str, cookie: str, tags: str, common_tags: list[str]):
        self.yande_page.set_defaults(save_root, cookie, tags, common_tags)

    def set_yande_busy(self, busy: bool):
        self.yande_page.set_busy(busy)

    def set_yande_rows(self, rows: list[dict]):
        self.yande_page.set_rows(rows)

    def update_yande_row(self, index: int, status: str, message: str):
        self.yande_page.update_row(index, status, message)

    def set_yande_progress(self, completed: int, total: int, message: str):
        self.yande_page.set_progress(completed, total, message)

    def set_settings_defaults(self, d: dict):
        self.settings_page.set_defaults(d)

    def set_channel_cache_rows(self, rows: list[dict]):
        self.settings_page.set_channel_cache(rows)

    def set_session_status(self, loaded: bool, message: str = ""):
        self.settings_page.set_session_status(loaded, message)

    def show_success(self, message: str):
        InfoBar.success(
            title=translate("操作成功", self._language),
            content=translate(message, self._language),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT, duration=3500,
        )

    def show_error(self, message: str):
        InfoBar.error(
            title=translate("需要处理一下", self._language),
            content=translate(message, self._language),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT, duration=5500,
        )

    def show_info(self, message: str):
        InfoBar.info(
            title=translate("提示", self._language),
            content=translate(message, self._language),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT, duration=3000,
        )

    def show_system_notification(self, title: str, message: str):
        """Show a native operating-system notification when available."""
        if self._tray_icon and self._system_notifications_enabled:
            self._tray_icon.showMessage(
                translate(title, self._language),
                translate(message, self._language),
                QSystemTrayIcon.MessageIcon.Information,
                7000,
            )

    def show_download_finished_actions(self, downloaded: int, skipped: int):
        """Show an in-app completion toast with quick actions."""
        bar = InfoBar.success(
            title=translate("下载完成", self._language),
            content=translate(f"新增 {downloaded} 个文件，跳过 {skipped} 个。", self._language),
            parent=self,
            position=InfoBarPosition.TOP_RIGHT,
            duration=9000,
        )
        open_btn = PushButton(translate("打开目录", self._language), icon=FIF.FOLDER)
        history_btn = PushButton(translate("查看历史", self._language), icon=FIF.HISTORY)
        resume_btn = PushButton(translate("继续上次任务", self._language), icon=FIF.PLAY)
        for button in (open_btn, history_btn, resume_btn):
            button.setMinimumHeight(32)
        open_btn.clicked.connect(lambda checked=False: self.open_folder_requested.emit())
        history_btn.clicked.connect(lambda checked=False: self.switchTo(self.history_page))
        resume_btn.clicked.connect(lambda checked=False: self.task_page.resume_task_requested.emit())
        bar.addWidget(open_btn)
        bar.addWidget(history_btn)
        bar.addWidget(resume_btn)

    def set_system_notifications_enabled(self, enabled: bool):
        self._system_notifications_enabled = enabled
        if self._tray_icon and not self._tray_icon.isVisible():
            self._tray_icon.show()

    def set_close_behavior(self, behavior: str, remember: bool = False):
        self._close_behavior = behavior if behavior in {"ask", "minimize", "exit"} else "ask"
        self._remember_close_behavior = bool(remember)

    def set_tray_task_state(
        self,
        can_pause: bool = False,
        can_resume: bool = False,
        can_stop: bool = False,
        status_text: str | None = None,
    ):
        if self._tray_status_action and status_text is not None:
            self._tray_status_action.setText(status_text)
        if self._tray_icon and status_text:
            self._tray_icon.setToolTip(f"TG Pic Collector\n{status_text}")
        if self._tray_pause_action:
            self._tray_pause_action.setEnabled(can_pause)
        if self._tray_resume_action:
            self._tray_resume_action.setEnabled(can_resume)
        if self._tray_stop_action:
            self._tray_stop_action.setEnabled(can_stop)

    def set_tray_status(self, status_text: str):
        self.set_tray_task_state(status_text=status_text)

    def navigate_to_login(self):
        self.switchTo(self.login_page)

    def navigate_to_task(self):
        self.switchTo(self.task_page)

    def _open_tag_task(self, tag: str):
        self.task_page.tag_edit.setText(tag.lstrip("#"))
        self.switchTo(self.task_page)

    # ──────────────────────────────────────────────────────────
    #  内部
    # ──────────────────────────────────────────────────────────
    def _toggle_theme(self):
        # 由 Controller 监听 settings_save_requested 统一管理主题
        # 这里仅做快捷切换
        current = self.settings_page._theme_radios
        if current.get("dark") and current["dark"].isChecked():
            current["light"].setChecked(True)
            setTheme(Theme.LIGHT, lazy=True)
        else:
            current.get("dark") and current["dark"].setChecked(True)
            setTheme(Theme.DARK, lazy=True)
        self.refresh_theme()

    def apply_language(self, lang: str):
        self._language = lang
        apply_widget_language(self, lang)
        for page in (
            self.home_page,
            self.task_page,
            self.login_page,
            self.history_page,
            self.yande_page,
            self.export_page,
            self.settings_page,
            self.about_page,
        ):
            set_language = getattr(page, "set_language", None)
            if callable(set_language):
                set_language(lang)

    def eventFilter(self, watched, event):
        if getattr(self, "_app_tooltip_filter_ready", False) and handle_app_tooltip_event(watched, event):
            return True

        sidebar_grip = getattr(self, "_sidebar_resize_grip", None)
        if sidebar_grip is not None and watched is sidebar_grip:
            event_type = event.type()
            if event_type == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._sidebar_dragging = True
                self._sidebar_drag_start_x = int(event.globalPosition().x())
                self._sidebar_drag_start_width = self._sidebar_width
                sidebar_grip.grabMouse()
                return True
            if event_type == QEvent.Type.MouseMove and self._sidebar_dragging:
                delta = int(event.globalPosition().x()) - self._sidebar_drag_start_x
                self._set_sidebar_width(self._sidebar_drag_start_width + delta)
                return True
            if event_type == QEvent.Type.MouseButtonRelease and self._sidebar_dragging:
                self._sidebar_dragging = False
                sidebar_grip.releaseMouse()
                return True
            if event_type == QEvent.Type.MouseButtonDblClick:
                self._set_sidebar_width(280)
                return True

        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and watched.isWindow()
        ):
            QTimer.singleShot(
                0, lambda widget=watched: apply_widget_language(widget, self._language)
        )
        return super().eventFilter(watched, event)

    def _build_sidebar_resize_grip(self):
        grip = QFrame(self)
        grip.setObjectName("sidebarResizeGrip")
        grip.setFixedWidth(8)
        grip.setCursor(Qt.CursorShape.SizeHorCursor)
        grip.setToolTip("拖动调整侧边栏宽度，双击恢复默认宽度")
        grip.setStyleSheet(
            "QFrame#sidebarResizeGrip{background:transparent;}"
            "QFrame#sidebarResizeGrip:hover{background:transparent;}"
        )
        grip.installEventFilter(self)
        self._sidebar_resize_grip = grip
        self._position_sidebar_resize_grip()
        grip.show()
        grip.raise_()

    def _set_sidebar_width(self, width: int):
        width = max(self._sidebar_min_width, min(self._sidebar_max_width, int(width)))
        if width == self._sidebar_width:
            return
        self._sidebar_width = width
        self.navigationInterface.setExpandWidth(width)
        self.navigationInterface.expand(useAni=False)
        self._position_sidebar_resize_grip()

    def _position_sidebar_resize_grip(self):
        sidebar_grip = getattr(self, "_sidebar_resize_grip", None)
        if not sidebar_grip:
            return
        nav = self.navigationInterface.geometry()
        x = max(0, nav.x() + nav.width() - 4)
        sidebar_grip.setGeometry(x, 0, 8, self.height())
        sidebar_grip.raise_()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self._show_tray_menu()
            return
        if reason not in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            return
        self._restore_from_notification()

    def _build_tray_menu(self):
        if not self._tray_icon:
            return
        menu = QMenu(self)
        if isDarkTheme():
            menu_bg, menu_border, menu_text, menu_hover, menu_disabled = (
                "#2f3238",
                "#4b5260",
                "#f5f7fb",
                "#3d4656",
                "#8b94a6",
            )
        else:
            menu_bg, menu_border, menu_text, menu_hover, menu_disabled = (
                "#ffffff",
                "#d9e1ee",
                "#141923",
                "#eef5ff",
                "#8a95a8",
            )
        menu.setStyleSheet(
            f"QMenu{{padding:4px;background:{menu_bg};color:{menu_text};"
            f"border:1px solid {menu_border};border-radius:8px;font-size:12px;}}"
            "QMenu::item{padding:5px 26px 5px 24px;min-height:22px;}"
            f"QMenu::item:selected{{background:{menu_hover};border-radius:5px;}}"
            f"QMenu::separator{{height:1px;background:{menu_border};margin:4px 6px;}}"
            f"QMenu::item:disabled{{color:{menu_disabled};}}"
        )

        def make_action(icon: FIF, text: str) -> QAction:
            return QAction(icon.icon(Theme.AUTO), text, self)

        open_action = make_action(FIF.HOME, "打开主界面")
        open_action.triggered.connect(lambda checked=False: self._restore_from_notification())
        menu.addAction(open_action)
        menu.addSeparator()

        self._tray_pause_action = make_action(FIF.PAUSE, "暂停下载")
        self._tray_status_action = make_action(FIF.INFO, "空闲")
        self._tray_status_action.setEnabled(False)
        menu.addAction(self._tray_status_action)
        menu.addSeparator()

        self._tray_pause_action.setEnabled(False)
        self._tray_pause_action.triggered.connect(
            lambda checked=False: self.tray_pause_requested.emit()
        )
        menu.addAction(self._tray_pause_action)

        self._tray_resume_action = make_action(FIF.PLAY, "继续下载")
        self._tray_resume_action.setEnabled(False)
        self._tray_resume_action.triggered.connect(
            lambda checked=False: self.tray_resume_requested.emit()
        )
        menu.addAction(self._tray_resume_action)

        self._tray_stop_action = make_action(FIF.CLOSE, "停止下载")
        self._tray_stop_action.setEnabled(False)
        self._tray_stop_action.triggered.connect(
            lambda checked=False: self.tray_stop_requested.emit()
        )
        menu.addAction(self._tray_stop_action)
        menu.addSeparator()

        folder_action = make_action(FIF.FOLDER, "打开保存目录")
        folder_action.triggered.connect(
            lambda checked=False: self.open_folder_requested.emit()
        )
        menu.addAction(folder_action)

        close_action = make_action(FIF.POWER_BUTTON, "退出应用")
        close_action.triggered.connect(lambda checked=False: self._quit_from_tray())
        menu.addAction(close_action)

        self._tray_menu = menu

    def _show_tray_menu(self):
        if not self._tray_menu:
            return
        if self._tray_menu.isVisible():
            self._tray_menu.hide()

        cursor = QCursor.pos()
        screen = QApplication.screenAt(cursor) or QApplication.primaryScreen()
        if screen is None:
            self._tray_menu.exec(cursor)
            return

        area = screen.availableGeometry()
        size = self._tray_menu.sizeHint()
        margin = 8
        width = max(1, size.width())
        height = max(1, size.height())

        x = min(cursor.x(), area.right() - width - margin)
        x = max(area.left() + margin, x)
        space_below = area.bottom() - cursor.y()
        if space_below >= height + margin:
            y = cursor.y() + margin
        else:
            y = cursor.y() - height - margin
        y = max(area.top() + margin, min(y, area.bottom() - height - margin))

        self._tray_menu.exec(QPoint(x, y))

    def _quit_from_tray(self):
        self._closing = True
        if self._tray_menu and self._tray_menu.isVisible():
            self._tray_menu.close()
        self.hide()
        if self._tray_icon:
            self._tray_icon.hide()
        QTimer.singleShot(0, lambda: self.tray_quit_requested.emit())

    def _hide_to_tray_or_minimize(self):
        if self._tray_icon and self._tray_icon.isVisible():
            self.hide()
            self._tray_icon.setToolTip("TG Pic Collector\n已隐藏到托盘，右键可退出应用")
        else:
            self.showMinimized()

    def _restore_from_notification(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh_tooltip_theme(self):
        self.refresh_theme()

    def refresh_theme(self):
        apply_tooltip_theme()
        for page in (
            self.home_page,
            self.task_page,
            self.login_page,
            self.history_page,
            self.yande_page,
            self.export_page,
            self.settings_page,
            self.about_page,
        ):
            refresh = getattr(page, "refresh_theme", None)
            if callable(refresh):
                refresh()
        for table in self.findChildren(PassiveTableWidget):
            table.refresh_theme()
        for chart in self.findChildren(TrendChart):
            chart.update()
        for card in self.findChildren(StatCard):
            card.refresh_theme()
        if self._tray_icon:
            self._build_tray_menu()

    def refresh_responsive_layouts(self):
        pages = (
            getattr(self, "home_page", None),
            getattr(self, "task_page", None),
            getattr(self, "login_page", None),
            getattr(self, "history_page", None),
            getattr(self, "yande_page", None),
            getattr(self, "export_page", None),
            getattr(self, "settings_page", None),
            getattr(self, "about_page", None),
        )
        for page in pages:
            if page is None:
                continue
            refresh = getattr(page, "refresh_layout", None)
            if callable(refresh):
                refresh()

    def center_on_screen(self):
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        frame = self.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        self.move(frame.topLeft())

    def showEvent(self, event):
        super().showEvent(event)
        self._position_sidebar_resize_grip()
        if self._initially_centered:
            return
        self._initially_centered = True
        # Wait until FluentWindow finishes its first layout and frame sizing.
        QTimer.singleShot(0, self.center_on_screen)
        QTimer.singleShot(0, self._position_sidebar_resize_grip)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_sidebar_resize_grip()
        self.refresh_responsive_layouts()
        QTimer.singleShot(0, self.refresh_responsive_layouts)
        QTimer.singleShot(80, self.refresh_responsive_layouts)

    def closeEvent(self, event: QCloseEvent):
        if self._closing:
            event.accept()
            return
        behavior = getattr(self, "_close_behavior", "ask")
        if behavior == "ask":
            box = CloseBehaviorDialog(self._remember_close_behavior, self)
            if not box.exec():
                event.ignore()
                return
            behavior = box.behavior()
            remember = box.remember_choice()
            if remember:
                self._close_behavior = behavior
                self._remember_close_behavior = True
                self.close_behavior_changed.emit(behavior, True)
            else:
                self._close_behavior = "ask"
                self._remember_close_behavior = False
                self.close_behavior_changed.emit("ask", False)

        if behavior == "minimize":
            event.ignore()
            self._hide_to_tray_or_minimize()
            return
        self._closing = True
        event.ignore()
        self.hide()
        self.window_closing.emit()
