from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme, setThemeColor

from .config import AppConfig
from .controller import AppController


APP_NAME = "TG Pic Collector"
WINDOWS_APP_USER_MODEL_ID = "TGCommentCollector.TGPicCollector"


def _set_windows_app_identity() -> None:
    """Prevent Windows taskbar and notifications from identifying us as python.exe."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )
    except (AttributeError, OSError):
        pass


def _configure_qt_runtime() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def _configure_high_refresh_scrolling(app: QApplication) -> None:
    screen = app.primaryScreen()
    refresh_rate = int(round(screen.refreshRate())) if screen else 60
    target_fps = max(60, min(144, refresh_rate or 60))

    try:
        from qfluentwidgets.common import smooth_scroll
    except Exception:
        return

    engine_base = smooth_scroll.SmoothScrollEngineBase
    if getattr(engine_base, "_tgpc_high_refresh_patched", False):
        return

    original_init = engine_base.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.fps = target_fps
        if getattr(self, "smoothMoveTimer", None):
            self.smoothMoveTimer.setTimerType(Qt.TimerType.PreciseTimer)

    engine_base.__init__ = patched_init
    engine_base._tgpc_high_refresh_patched = True
    engine_base._tgpc_target_fps = target_fps


def run() -> int:
    _set_windows_app_identity()
    _configure_qt_runtime()
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setOrganizationName("TGCommentCollector")
    app = QApplication(sys.argv)
    _configure_high_refresh_scrolling(app)
    ui_font_family = "Microsoft YaHei UI" if sys.platform == "win32" else "Noto Sans CJK SC"
    app.setFont(QFont(ui_font_family, 10))
    app.setStyleSheet(f"QWidget{{font-family:'{ui_font_family}';}}")
    app.setQuitOnLastWindowClosed(False)
    config = AppConfig.load()
    theme = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}.get(
        config.theme_mode, Theme.AUTO
    )
    setTheme(theme)
    setThemeColor(QColor("#1677ff"))

    controller = AppController(config)
    app.aboutToQuit.connect(controller.cleanup_threads)
    controller.window.show()
    exit_code = app.exec()
    controller.cleanup_threads()
    return exit_code
