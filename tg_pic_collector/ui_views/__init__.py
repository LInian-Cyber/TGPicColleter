"""Split UI package with a stable public surface."""

from .about import AboutPage
from .common import HistoryRow, SearchPreviewDialog, TaskRow
from .history import HistoryPage
from .home import HomePage
from .login import LoginPage
from .main_window import MainWindow
from .settings import SettingsPage
from .task import TaskPage

__all__ = [
    "AboutPage",
    "HistoryPage",
    "HistoryRow",
    "HomePage",
    "LoginPage",
    "MainWindow",
    "SearchPreviewDialog",
    "SettingsPage",
    "TaskPage",
    "TaskRow",
]
