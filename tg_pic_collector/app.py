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


def run() -> int:
    _set_windows_app_identity()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationDisplayName(APP_NAME)
    QApplication.setOrganizationName("TGCommentCollector")
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI Variable", 10))
    app.setQuitOnLastWindowClosed(False)
    config = AppConfig.load()
    theme = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}.get(
        config.theme_mode, Theme.AUTO
    )
    setTheme(theme)
    setThemeColor(QColor("#1677ff"))

    controller = AppController(config)
    controller.window.show()
    return app.exec()
