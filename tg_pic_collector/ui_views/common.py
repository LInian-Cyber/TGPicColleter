"""Shared UI models, helpers, widgets, and dialogs."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import qrcode
from PIL import Image
from PySide6.QtCore import (
    Qt,
    QTimer,
    Signal,
    QPropertyAnimation,
    QEasingCurve,
    QSize,
    QDate,
    QEvent,
    QObject,
    QPoint,
)
from PySide6.QtGui import (
    QCloseEvent,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QLinearGradient,
    QBrush,
    QCursor,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QSpacerItem,
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QPlainTextEdit,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QSystemTrayIcon,
    QToolTip,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    FluentIcon as FIF,
    FluentWindow,
    IconWidget,
    EditableComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    NavigationItemPosition,
    PasswordLineEdit,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    DateEdit,
    ScrollArea,
    DoubleSpinBox,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    Theme,
    TitleLabel,
    ToolButton,
    TransparentPushButton,
    TransparentToolButton,
    setTheme,
    SegmentedWidget,
    RadioButton,
    HyperlinkButton,
    InfoBadge,
    MessageBoxBase,
    MessageBox,
    PillPushButton,
    RoundMenu,
    Action,
    isDarkTheme,
)

# ──────────────────────────────────────────────────────────────
#  常量
# ──────────────────────────────────────────────────────────────
# 图标和插图位于 tg_pic_collector/assets。
_UI_DIR = Path(__file__).resolve().parent.parent / "assets"

# 使用 QFluentWidgets 的主题颜色，支持深色/浅色模式自动切换
def get_theme_color(light_color: str, dark_color: str) -> str:
    """根据当前主题返回对应的颜色"""
    from qfluentwidgets import isDarkTheme
    return dark_color if isDarkTheme() else light_color


def apply_tooltip_theme() -> None:
    """Update tooltip colors without rebuilding the application's style sheet."""
    app = QApplication.instance()
    if app is None:
        return
    from qfluentwidgets import isDarkTheme

    if isDarkTheme():
        background, foreground = "#252a34", "#f5f7fb"
    else:
        background, foreground = "#ffffff", "#1a2233"
    border = "#3f4756" if isDarkTheme() else "#dbe3f1"

    palette = QToolTip.palette()
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(background))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(foreground))
    palette.setColor(QPalette.ColorRole.Window, QColor(background))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(foreground))
    QToolTip.setPalette(palette)

    begin = "/* TGPC_TOOLTIP_BEGIN */"
    end = "/* TGPC_TOOLTIP_END */"
    tooltip_qss = (
        f"{begin}\n"
        "QToolTip{"
        f"background-color:{background};"
        f"color:{foreground};"
        f"border:1px solid {border};"
        "border-radius:6px;"
        "padding:6px 8px;"
        "}\n"
        f"{end}"
    )
    current = app.styleSheet()
    if begin in current and end in current:
        before = current.split(begin, 1)[0].rstrip()
        after = current.split(end, 1)[1].lstrip()
        app.setStyleSheet("\n".join(part for part in (before, tooltip_qss, after) if part))
    else:
        app.setStyleSheet("\n".join(part for part in (current.rstrip(), tooltip_qss) if part))

    # QFluentWidgets uses its own ToolTip widget for many controls, so the
    # native QToolTip QSS above is not enough on its own.
    try:
        from qfluentwidgets.components.widgets.tool_tip import ToolTip
    except Exception:
        return

    shadow = QColor(0, 0, 0, 90 if isDarkTheme() else 35)
    fluent_qss = (
        "ToolTip{background:transparent;border:none;}"
        "ToolTip QFrame#container,"
        "QFrame#container{"
        f"background-color:{background};"
        f"border:1px solid {border};"
        "border-radius:8px;"
        "}"
        "ToolTip QLabel#contentLabel,"
        "QLabel#contentLabel{"
        f"color:{foreground};"
        "background:transparent;"
        "font-size:12px;"
        "}"
    )

    def _set_fluent_tooltip_qss(self) -> None:
        self.container.setObjectName("container")
        self.label.setObjectName("contentLabel")
        self.setStyleSheet(fluent_qss)
        self.container.setStyleSheet(
            "QFrame#container{"
            f"background-color:{background};"
            f"border:1px solid {border};"
            "border-radius:8px;"
            "}"
        )
        self.label.setStyleSheet(
            "QLabel#contentLabel{"
            f"color:{foreground};"
            "background:transparent;"
            "font-size:12px;"
            "}"
        )
        if getattr(self, "shadowEffect", None):
            self.shadowEffect.setColor(shadow)
        self.label.adjustSize()
        self.adjustSize()

    ToolTip._ToolTip__setQss = _set_fluent_tooltip_qss
    for widget in app.allWidgets():
        if isinstance(widget, ToolTip):
            _set_fluent_tooltip_qss(widget)


class AppToolTip(QFrame):
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
        self._label.setMaximumWidth(620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.addWidget(self._label)
        self.refresh_theme()

    def refresh_theme(self):
        if isDarkTheme():
            background, foreground, border = "#252a34", "#f5f7fb", "#3f4756"
        else:
            background, foreground, border = "#ffffff", "#142033", "#dbe3f1"
        self.setStyleSheet(
            "QFrame{"
            f"background:{background};border:1px solid {border};border-radius:8px;"
            "}"
            "QLabel{"
            f"color:{foreground};background:transparent;border:none;font-size:12px;"
            "}"
        )

    def show_text(self, text: str, pos: QPoint | None = None):
        text = str(text or "").strip()
        if not text:
            self.hide()
            return
        self._label.setText(text)
        self.adjustSize()
        pos = pos or QCursor.pos()
        pos = QPoint(pos.x() + 14, pos.y() + 18)
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            pos.setX(min(max(rect.left() + 6, pos.x()), rect.right() - self.width() - 6))
            pos.setY(min(max(rect.top() + 6, pos.y()), rect.bottom() - self.height() - 6))
        self.move(pos)
        self.show()


_APP_TOOLTIP: AppToolTip | None = None


def _app_tooltip() -> AppToolTip:
    global _APP_TOOLTIP
    if _APP_TOOLTIP is None:
        _APP_TOOLTIP = AppToolTip()
    _APP_TOOLTIP.refresh_theme()
    return _APP_TOOLTIP


def hide_app_tooltip() -> None:
    if _APP_TOOLTIP is not None:
        _APP_TOOLTIP.hide()


def show_app_tooltip(text: str, pos: QPoint | None = None, duration: int = 2400) -> None:
    _app_tooltip().show_text(text, pos)
    if duration > 0:
        QTimer.singleShot(duration, hide_app_tooltip)


def _view_tooltip_text(view: QAbstractItemView, pos: QPoint) -> str:
    index = view.indexAt(pos)
    if not index.isValid():
        return ""
    value = index.data(Qt.ItemDataRole.ToolTipRole)
    return str(value or "").strip()


def tooltip_text_from_event(watched: QObject, event: QEvent) -> str:
    widget = watched if isinstance(watched, QWidget) else None
    if widget is None:
        return ""
    pos = event.pos() if hasattr(event, "pos") else QPoint()
    parent = widget
    while parent is not None:
        if isinstance(parent, QAbstractItemView) and parent.viewport() is widget:
            text = _view_tooltip_text(parent, pos)
            if text:
                return text
        parent = parent.parentWidget()
    if isinstance(widget, QAbstractItemView):
        text = _view_tooltip_text(widget, pos)
        if text:
            return text
    return str(widget.toolTip() or "").strip()


def handle_app_tooltip_event(watched: QObject, event: QEvent) -> bool:
    try:
        event_type = event.type()
        tooltip_type = QEvent.Type.ToolTip
        hide_types = {
            QEvent.Type.Leave,
            QEvent.Type.Hide,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.Wheel,
        }
    except Exception:
        return False
    if event_type == tooltip_type:
        QToolTip.hideText()
        text = tooltip_text_from_event(watched, event)
        if text:
            pos = event.globalPos() if hasattr(event, "globalPos") else QCursor.pos()
            _app_tooltip().show_text(text, pos)
        else:
            hide_app_tooltip()
        return True
    if event_type in hide_types:
        hide_app_tooltip()
    return False


C_BLUE = "#0f6fff"
C_GREEN = "#18a66a"
C_ORANGE = "#f59e0b"
C_MUTED = "#68758f"
C_BG_CARD = "transparent"
C_BORDER = "#e8edf5"
C_PROGRESS_BG = "#e8edf5"


def theme_text_color() -> str:
    return "#f5f7fb" if isDarkTheme() else "#141923"


def theme_muted_color() -> str:
    return "#aeb8ca" if isDarkTheme() else C_MUTED


def theme_border_color() -> str:
    return "#4b5260" if isDarkTheme() else C_BORDER


def theme_surface_color() -> str:
    return "#303238" if isDarkTheme() else "#ffffff"


def theme_soft_bg_color() -> str:
    return "#25282f" if isDarkTheme() else "#f6f8fc"


def theme_progress_bg_color() -> str:
    return "#555b66" if isDarkTheme() else C_PROGRESS_BG


def theme_scrollbar_color(hover: bool = False) -> str:
    if isDarkTheme():
        return "#6d7484" if hover else "#555c6b"
    return "#c9d3e5" if hover else "#dbe3f1"


def theme_icon_pixmap(icon: FIF, size: int) -> QPixmap:
    return icon.icon(Theme.AUTO).pixmap(size, size)


def set_theme_icon(label: QLabel, icon: FIF, size: int) -> None:
    label.setPixmap(theme_icon_pixmap(icon, size))


def passive_table_qss() -> str:
    text = theme_text_color()
    border = theme_border_color()
    scroll = theme_scrollbar_color()
    scroll_hover = theme_scrollbar_color(True)
    return (
        f"QTableWidget{{border:none;background:transparent;color:{text};"
        f"gridline-color:{border};selection-background-color:transparent;}}"
        f"QTableWidget::item{{color:{text};background:transparent;}}"
        f"QTableWidget::item:selected,QTableWidget::item:hover{{background:transparent;color:{text};}}"
        f"QHeaderView::section{{background:transparent;color:{text};"
        f"border:none;border-bottom:1px solid {border};font-weight:600;}}"
        f"QTableCornerButton::section{{background:transparent;border:none;}}"
        f"QScrollBar:vertical{{background:transparent;width:6px;margin:2px 0 2px 0;}}"
        f"QScrollBar::handle:vertical{{background:{scroll};border-radius:3px;min-height:28px;}}"
        f"QScrollBar::handle:vertical:hover{{background:{scroll_hover};}}"
        "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;background:transparent;}"
        "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
        f"QScrollBar:horizontal{{background:transparent;height:6px;margin:0 2px 0 2px;}}"
        f"QScrollBar::handle:horizontal{{background:{scroll};border-radius:3px;min-width:28px;}}"
        f"QScrollBar::handle:horizontal:hover{{background:{scroll_hover};}}"
        "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;background:transparent;}"
        "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:transparent;}"
    )


def plain_text_qss() -> str:
    return (
        f"QPlainTextEdit{{background:{theme_soft_bg_color()};color:{theme_text_color()};"
        f"border:1px solid {theme_border_color()};border-radius:8px;padding:8px;}}"
    )

COUNTRY_CODES = [
    ("中国", "+86"), ("中国香港", "+852"), ("中国澳门", "+853"), ("中国台湾", "+886"),
    ("美国 / 加拿大", "+1"), ("英国", "+44"), ("法国", "+33"), ("德国", "+49"),
    ("意大利", "+39"), ("西班牙", "+34"), ("葡萄牙", "+351"), ("俄罗斯", "+7"),
    ("乌克兰", "+380"), ("波兰", "+48"), ("荷兰", "+31"), ("比利时", "+32"),
    ("瑞士", "+41"), ("奥地利", "+43"), ("瑞典", "+46"), ("挪威", "+47"),
    ("丹麦", "+45"), ("芬兰", "+358"), ("爱尔兰", "+353"), ("冰岛", "+354"),
    ("捷克", "+420"), ("匈牙利", "+36"), ("罗马尼亚", "+40"), ("希腊", "+30"),
    ("土耳其", "+90"), ("以色列", "+972"), ("阿联酋", "+971"), ("沙特阿拉伯", "+966"),
    ("印度", "+91"), ("巴基斯坦", "+92"), ("孟加拉国", "+880"), ("斯里兰卡", "+94"),
    ("日本", "+81"), ("韩国", "+82"), ("新加坡", "+65"), ("马来西亚", "+60"),
    ("泰国", "+66"), ("越南", "+84"), ("菲律宾", "+63"), ("印度尼西亚", "+62"),
    ("澳大利亚", "+61"), ("新西兰", "+64"), ("巴西", "+55"), ("墨西哥", "+52"),
    ("阿根廷", "+54"), ("智利", "+56"), ("哥伦比亚", "+57"), ("秘鲁", "+51"),
    ("南非", "+27"), ("埃及", "+20"), ("尼日利亚", "+234"), ("肯尼亚", "+254"),
]


# ──────────────────────────────────────────────────────────────
#  数据模型（纯 UI 侧，不依赖业务层）
# ──────────────────────────────────────────────────────────────
class TaskRow:
    """用于填充任务队列的数据容器"""
    def __init__(
        self,
        name: str,
        keyword: str,
        status: str,          # "下载中" | "排队中" | "已暂停" | "已完成" | "已取消"
        progress: int,         # 0-100
        downloaded: int,
        total: int,
        post_statuses: dict[int, str] | None = None,
        skipped: int = 0,
    ):
        self.name = name
        self.keyword = keyword
        self.status = status
        self.progress = progress
        self.downloaded = downloaded
        self.total = total
        self.post_statuses = post_statuses or {}
        self.skipped = skipped


class HistoryRow:
    def __init__(self, channel: str, tag: str, status: str,
                 posts: int, downloaded: int, time: str):
        self.channel = channel
        self.tag = tag
        self.status = status
        self.posts = posts
        self.downloaded = downloaded
        self.time = time


# ──────────────────────────────────────────────────────────────
#  基础工具
# ──────────────────────────────────────────────────────────────
def _set_margins(layout, m=(20, 16, 20, 16), s=12):
    layout.setContentsMargins(*m)
    layout.setSpacing(s)
def _asset(name: str) -> str:
    return str(_UI_DIR / name)


def _img_label(name: str, w: int, h: int) -> QLabel:
    lbl = QLabel()
    lbl.setFixedSize(w, h)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    px = QPixmap(_asset(name))
    if not px.isNull():
        lbl.setPixmap(px.scaled(w, h,
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation))
    return lbl


def _set_round_avatar(label: QLabel, avatar_bytes: bytes, size: int) -> None:
    """Render avatar bytes as a centered circular pixmap."""
    if not avatar_bytes:
        label.clear()
        label.setText("●")
        return
    pixmap = QPixmap()
    if not pixmap.loadFromData(avatar_bytes):
        label.clear()
        label.setText("●")
        return
    scaled = pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    rounded = QPixmap(size, size)
    rounded.fill(Qt.GlobalColor.transparent)
    painter = QPainter(rounded)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, scaled)
    painter.end()
    label.setText("")
    label.setPixmap(rounded)


def _muted(text: str, wrap: bool = True) -> CaptionLabel:
    lbl = CaptionLabel(text)
    # 使用主题感知的灰色
    lbl.setObjectName("mutedLabel")
    lbl.setWordWrap(wrap)
    return lbl


def _divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setObjectName("dividerLine")
    f.setFixedHeight(1)
    return f


def _status_dot(status: str) -> str:
    colors = {
        "下载中": C_BLUE,
        "排队中": C_ORANGE,
        "已暂停": C_MUTED,
        "已完成": C_GREEN,
        "已取消": C_MUTED,
    }
    color = colors.get(status, C_MUTED)
    return f'<span style="color:{color};">●</span>'


# ──────────────────────────────────────────────────────────────
#  通用组件
# ──────────────────────────────────────────────────────────────
class PassiveItemDelegate(QStyledItemDelegate):
    """Paint table items without selected, focused, or hover states."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.state &= ~(
            QStyle.StateFlag.State_Selected
            | QStyle.StateFlag.State_HasFocus
            | QStyle.StateFlag.State_MouseOver
        )


class PassiveTableWidget(QTableWidget):
    """Read-only table whose cells never become active or highlighted."""

    def __init__(self, rows: int, columns: int, parent=None):
        super().__init__(rows, columns, parent)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 保持 mouseTracking 开启，否则 tooltip 无法正常触发
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setItemDelegate(PassiveItemDelegate(self))
        self.refresh_theme()

    def refresh_theme(self):
        self.setStyleSheet(passive_table_qss())

    def mousePressEvent(self, event):
        self.clearSelection()
        self.setCurrentCell(-1, -1)
        event.accept()

    def mouseReleaseEvent(self, event):
        event.accept()

    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        if not bar.isVisible() or bar.maximum() <= bar.minimum():
            event.ignore()
            return

        delta = event.angleDelta().y() or event.pixelDelta().y()
        if delta == 0:
            event.ignore()
            return

        can_scroll_up = bar.value() > bar.minimum()
        can_scroll_down = bar.value() < bar.maximum()
        if (delta > 0 and not can_scroll_up) or (delta < 0 and not can_scroll_down):
            event.ignore()
            return

        super().wheelEvent(event)
        event.accept()


class SurfaceCard(CardWidget):
    """带可选标题/副标题的卡片容器"""
    def __init__(self, title: str = "", subtitle: str = "", parent=None):
        super().__init__(parent)
        self.body = QVBoxLayout(self)
        _set_margins(self.body)
        if title:
            row = QHBoxLayout()
            self.title_label = SubtitleLabel(title)
            row.addWidget(self.title_label)
            row.addStretch()
            self.body.addLayout(row)
            self._title_row = row
        if subtitle:
            self.body.addWidget(_muted(subtitle))

    def title_row(self) -> QHBoxLayout | None:
        return getattr(self, "_title_row", None)


class ScrollPage(ScrollArea):
    """可滚动页面基类"""
    def __init__(self, object_name: str, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setWidgetResizable(True)
        self.setFrameShape(ScrollArea.Shape.NoFrame)
        self.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._content = QWidget()
        self._content.setStyleSheet("background:transparent;")
        self.root = QVBoxLayout(self._content)
        _set_margins(self.root, (28, 24, 28, 28), 16)
        self.root.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setWidget(self._content)
        apply_tooltip_theme()

    def _page_header(self, title: str, subtitle: str,
                     illus: str = "download-illustration.png",
                     illus_w: int = 260, illus_h: int = 100):
        card = SurfaceCard()
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(6)
        tl = TitleLabel(title)
        text.addWidget(tl)
        text.addWidget(_muted(subtitle))
        row.addLayout(text, 1)
        row.addWidget(_img_label(illus, illus_w, illus_h), 0, Qt.AlignmentFlag.AlignVCenter)
        card.body.addLayout(row)
        self.root.addWidget(card, 0, Qt.AlignmentFlag.AlignTop)


class StatCard(CardWidget):
    """首页统计卡片"""
    def __init__(self, title: str, value: str, unit: str, icon: FIF, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        _set_margins(layout, (14, 12, 14, 12), 5)
        top = QHBoxLayout()
        top.addWidget(StrongBodyLabel(title))
        top.addStretch()
        self._icon = icon
        self._icon_label = QLabel()
        set_theme_icon(self._icon_label, icon, 22)
        top.addWidget(self._icon_label)
        layout.addLayout(top)
        vrow = QHBoxLayout()
        self._val = TitleLabel(value)
        vrow.addWidget(self._val)
        vrow.addWidget(_muted(unit))
        vrow.addStretch()
        layout.addLayout(vrow)
        self._detail = _muted("暂无记录")
        layout.addWidget(self._detail)

    def set_value(self, value: str, detail: str = ""):
        self._val.setText(value)
        if detail:
            self._detail.setText(detail)

    def refresh_theme(self):
        set_theme_icon(self._icon_label, self._icon, 22)
        self.update()


class TrendChart(QWidget):
    """7 天下载趋势迷你折线图（支持真实数据注入）"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(180)
        self._data: list[int] = [0] * 7
        self._dates: list[str] = []
        self._refresh_dates()

    def _refresh_dates(self):
        self._dates = [
            (datetime.now() - timedelta(days=i)).strftime("%m-%d")
            for i in range(6, -1, -1)
        ]

    def set_data(self, values: list[int], labels: list[str] | None = None):
        """注入 7 天数据"""
        self._data = (values + [0] * 7)[:7]
        if labels:
            self._dates = (labels + [""] * 7)[:7]
        else:
            self._refresh_dates()
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        area = self.rect().adjusted(46, 14, -14, -34)
        grid_pen = QPen(QColor("#59606c" if isDarkTheme() else "#e5edf8"), 1)
        text_pen = QPen(QColor(theme_muted_color()))
        font = QFont()
        font.setPointSize(8)
        p.setFont(font)

        # Y轴网格 + 标签
        y_labels = [90, 60, 30, 0]
        for i, v in enumerate(y_labels):
            y = int(area.top() + i * area.height() / 3)
            p.setPen(grid_pen)
            p.drawLine(area.left(), y, area.right(), y)
            p.setPen(text_pen)
            p.drawText(4, y + 4, str(v))

        # X轴
        p.setPen(QPen(QColor(C_BLUE), 2))
        p.drawLine(area.left(), area.bottom(), area.right(), area.bottom())

        # 日期标签 + 数据点
        step = area.width() / max(len(self._dates) - 1, 1)
        max_val = max(max(self._data), 1)
        pts = []
        for i, (date, val) in enumerate(zip(self._dates, self._data)):
            x = int(area.left() + i * step)
            y = int(area.bottom() - (val / max_val) * area.height())
            pts.append((x, y))
            p.setPen(text_pen)
            p.drawText(x - 16, area.bottom() + 22, date)

        # 折线
        if len(pts) >= 2:
            p.setPen(QPen(QColor(C_BLUE), 2))
            for i in range(len(pts) - 1):
                p.drawLine(pts[i][0], pts[i][1], pts[i+1][0], pts[i+1][1])

        # 数据点
        p.setBrush(QBrush(QColor(C_BLUE)))
        point_border = QColor(theme_surface_color())
        p.setPen(QPen(point_border, 2))
        for x, y in pts:
            p.drawEllipse(x - 4, y - 4, 8, 8)
            p.setPen(text_pen)
            p.drawText(x - 6, y - 8, str(self._data[pts.index((x, y))]))
            p.setPen(QPen(point_border, 2))
        p.end()


class InlineProgress(QWidget):
    """内联进度条（仿设计稿蓝色细长条）"""
    def __init__(self, value: int = 0, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self.setMinimumWidth(80)
        self._value = max(0, min(100, value))

    def set_value(self, v: int):
        self._value = max(0, min(100, v))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        path_bg = QPainterPath()
        path_bg.addRoundedRect(r.x(), r.y(), r.width(), r.height(), 3, 3)
        p.fillPath(path_bg, QColor(theme_progress_bg_color()))
        fill_w = int(r.width() * self._value / 100)
        if fill_w > 0:
            path_fill = QPainterPath()
            path_fill.addRoundedRect(r.x(), r.y(), fill_w, r.height(), 3, 3)
            p.fillPath(path_fill, QColor(C_BLUE))
        p.end()


class TagPill(PushButton):
    """可点击的 Tag 标签药丸"""
    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        self.setText(text)
        self.setStyleSheet(f"""
            PushButton {{
                background:#eaf1fc;
                color:{C_BLUE};
                border:none;
                border-radius:14px; /* 根据高度微调圆角 */
                padding:6px 16px;   /* ✨ 增加上下左右的内边距，防止文字贴边 */
                font-size:12px;
            }}
            PushButton:hover {{
                background:#d4e6fc;
            }}
        """)
        # ✨ 删掉 self.setFixedHeight(26)
        self.setMinimumHeight(28) # 改用最小高度


class SearchPreviewDialog(MessageBoxBase):
    """Fluent-style browser for matched posts and comment image thumbnails."""

    cancel_requested = Signal()
    download_requested = Signal()

    def __init__(self, channel: str, tag: str, parent=None):
        super().__init__(parent)
        self.widget.setMinimumSize(960, 680)
        self.widget.setMaximumSize(1120, 820)
        self._ready = False
        self.yesButton.setText("直接下载")
        self.yesButton.setEnabled(False)
        self.cancelButton.setText("取消搜索")

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title_col.addWidget(TitleLabel("搜索预览"))
        target = channel if not tag else f"{channel}  ·  {tag}"
        title_col.addWidget(_muted(target))
        header.addLayout(title_col, 1)
        badge = QLabel(" 仅预览，不保存 ")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background:#eaf1fc;color:{C_BLUE};border-radius:12px;"
            "padding:4px 10px;font-size:12px;font-weight:600;"
        )
        header.addWidget(badge)
        self.viewLayout.addLayout(header)

        self._status = BodyLabel("正在准备搜索…")
        self.viewLayout.addWidget(self._status)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(4)
        self.viewLayout.addWidget(self._progress)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self._content = QWidget()
        self._content.setStyleSheet("background:transparent;")
        self._results_layout = QVBoxLayout(self._content)
        _set_margins(self._results_layout, (0, 4, 0, 4), 12)
        self._results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._content)
        self.viewLayout.addWidget(self._scroll, 1)

    def set_progress(self, message: str):
        self._status.setText(message)

    def set_results(self, rows: list[dict], total_count: int, display_limit: int):
        self._progress.hide()
        self._ready = True
        self.yesButton.setEnabled(bool(rows))
        self.cancelButton.setText("关闭")
        self._clear_results()
        image_total = sum(int(row.get("image_count", 0)) for row in rows)
        hidden_count = max(0, total_count - len(rows))
        if hidden_count:
            self._status.setText(
                f"本次扫描范围内共找到 {total_count} 篇帖子，当前展示 {len(rows)} 篇，"
                f"还有 {hidden_count} 篇未展示；已展示帖子评论区共发现 {image_total} 张图片"
            )
        elif rows:
            self._status.setText(
                f"本次扫描范围内共找到 {total_count} 篇帖子，"
                f"评论区共发现 {image_total} 张图片"
            )
        else:
            self._status.setText("没有找到匹配的帖子")
        if not rows:
            empty = SurfaceCard()
            empty.body.addWidget(SubtitleLabel("暂无搜索结果"))
            empty.body.addWidget(_muted("请检查频道地址与 Tag，或尝试扩大默认检查帖子数量。"))
            self._results_layout.addWidget(empty)
            return

        if hidden_count:
            notice = SurfaceCard()
            notice.body.addWidget(StrongBodyLabel(
                f"预览最多展示 {display_limit} 篇帖子"
            ))
            notice.body.addWidget(_muted(
                f"本次共找到 {total_count} 篇，还有 {hidden_count} 篇未展示。"
                "正式下载仍会按照默认扫描帖子数量完整处理。"
            ))
            self._results_layout.addWidget(notice)

        for row in rows:
            card = SurfaceCard()
            top = QHBoxLayout()
            top.addWidget(StrongBodyLabel(f"帖子 #{row.get('post_id', '-')}"))
            top.addWidget(_muted(str(row.get("channel", "")), wrap=False))
            top.addStretch()
            top.addWidget(_muted(str(row.get("date", "-")), wrap=False))
            card.body.addLayout(top)

            text = str(row.get("text", "")).strip() or "该帖子没有文字内容"
            if len(text) > 500:
                text = f"{text[:500]}…"
            text_label = BodyLabel(text)
            text_label.setWordWrap(True)
            text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            card.body.addWidget(text_label)

            meta = (
                f"浏览 {int(row.get('views', 0)):,}  ·  "
                f"评论 {int(row.get('replies', 0)):,}  ·  "
                f"评论区图片 {int(row.get('image_count', 0)):,}"
            )
            card.body.addWidget(_muted(meta))

            hit_sources = [str(item) for item in (row.get("hit_sources") or []) if item]
            if hit_sources:
                source_row = QHBoxLayout()
                source_row.setSpacing(6)
                for source in hit_sources[:6]:
                    badge = QLabel(source)
                    badge.setStyleSheet(
                        f"background:#eaf1fc;color:{C_BLUE};border-radius:10px;"
                        "padding:3px 8px;font-size:12px;font-weight:600;"
                    )
                    source_row.addWidget(badge)
                source_row.addStretch()
                card.body.addLayout(source_row)

            debug_trace = [str(item) for item in (row.get("debug_trace") or []) if item]
            if len(debug_trace) > 1:
                trace_label = _muted("追踪链路：\n" + "\n".join(debug_trace))
                trace_label.setVisible(False)
                trace_btn = PushButton("查看追踪链路", icon=FIF.LINK)
                trace_btn.setMinimumHeight(32)
                trace_btn.clicked.connect(
                    lambda checked=False, label=trace_label: label.setVisible(not label.isVisible())
                )
                trace_row = QHBoxLayout()
                trace_row.addWidget(trace_btn)
                trace_row.addStretch()
                card.body.addLayout(trace_row)
                card.body.addWidget(trace_label)

            thumbnails = row.get("thumbnails") or []
            if thumbnails:
                thumb_row = QHBoxLayout()
                thumb_row.setSpacing(8)
                for data in thumbnails:
                    thumb = QLabel()
                    thumb.setFixedSize(132, 92)
                    thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    thumb.setStyleSheet(
                        "background:#eef3fa;border:1px solid #dfe7f2;border-radius:8px;"
                    )
                    pixmap = QPixmap()
                    if pixmap.loadFromData(data):
                        thumb.setPixmap(
                            pixmap.scaled(
                                thumb.size(),
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation,
                            )
                        )
                    thumb_row.addWidget(thumb)
                thumb_row.addStretch()
                card.body.addLayout(thumb_row)
            elif int(row.get("image_count", 0)):
                card.body.addWidget(_muted("图片没有可用缩略图，下载任务仍可保存原图。"))

            self._results_layout.addWidget(card)

    def set_error(self, message: str):
        self._progress.hide()
        self._ready = True
        self.yesButton.hide()
        self.cancelButton.setText("关闭")
        self._clear_results()
        self._status.setText("搜索预览失败")
        card = SurfaceCard()
        card.body.addWidget(StrongBodyLabel("暂时无法加载搜索结果"))
        card.body.addWidget(_muted(message))
        self._results_layout.addWidget(card)

    def _clear_results(self):
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def accept(self):
        if self._ready:
            self.download_requested.emit()
        else:
            self.cancel_requested.emit()
        super().accept()

    def reject(self):
        if not self._ready:
            self.cancel_requested.emit()
        super().reject()


class CloseBehaviorDialog(MessageBoxBase):
    """Ask what the title-bar close button should do this time."""

    def __init__(self, remember_default: bool = False, parent=None):
        super().__init__(parent)
        self.yesButton.setText("确定")
        self.cancelButton.setText("取消")
        self.widget.setMinimumWidth(520)

        self.viewLayout.addWidget(TitleLabel("点击关闭按钮时"))
        self.viewLayout.addWidget(_muted("选择本次操作，也可以决定是否记住这个选择。"))

        self._behavior_radios: dict[str, RadioButton] = {}
        behavior_row = QHBoxLayout()
        behavior_row.setSpacing(18)
        for text, key in [("最小化到托盘", "minimize"), ("退出应用", "exit")]:
            rb = RadioButton(text)
            self._behavior_radios[key] = rb
            behavior_row.addWidget(rb)
        behavior_row.addStretch()
        self._behavior_radios["minimize"].setChecked(True)
        self.viewLayout.addLayout(behavior_row)

        self.viewLayout.addWidget(_divider())

        self._remember_radios: dict[bool, RadioButton] = {}
        remember_row = QHBoxLayout()
        remember_row.setSpacing(18)
        for text, key in [("记住选择", True), ("仅本次", False)]:
            rb = RadioButton(text)
            self._remember_radios[key] = rb
            remember_row.addWidget(rb)
        remember_row.addStretch()
        self._remember_radios[bool(remember_default)].setChecked(True)
        self.viewLayout.addLayout(remember_row)

    def behavior(self) -> str:
        for key, radio in self._behavior_radios.items():
            if radio.isChecked():
                return key
        return "minimize"

    def remember_choice(self) -> bool:
        return self._remember_radios[True].isChecked()
