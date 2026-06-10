from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme, setThemeColor

from .config import AppConfig
from .controller import AppController


def run() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("TG Pic Collector")
    app.setOrganizationName("TGCommentCollector")
    app.setFont(QFont("Segoe UI Variable", 10))
    config = AppConfig.load()
    theme = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}.get(
        config.theme_mode, Theme.AUTO
    )
    setTheme(theme)
    setThemeColor(QColor("#1677ff"))

    controller = AppController(config)
    controller.window.show()
    return app.exec()
