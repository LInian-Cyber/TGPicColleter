"""Shared UI models, helpers, widgets, and dialogs."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import qrcode
from PIL import Image
from PySide6.QtCore import Qt, QTimer, Signal, QPropertyAnimation, QEasingCurve, QSize
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
    PillPushButton,
    RoundMenu,
    Action,
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

    palette = QToolTip.palette()
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(background))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(foreground))
    palette.setColor(QPalette.ColorRole.Window, QColor(background))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(foreground))
    QToolTip.setPalette(palette)


C_BLUE = "#0f6fff"
C_GREEN = "#18a66a"
C_ORANGE = "#f59e0b"
C_MUTED = "#68758f"
C_BG_CARD = "transparent"
C_BORDER = "#e8edf5"
C_PROGRESS_BG = "#e8edf5"

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
        # 保持 mouseTracking 开启，否则 tooltip 无法正常触发
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setItemDelegate(PassiveItemDelegate(self))

    def mousePressEvent(self, event):
        self.clearSelection()
        self.setCurrentCell(-1, -1)
        event.accept()

    def mouseReleaseEvent(self, event):
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
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(6)
        tl = TitleLabel(title)
        text.addWidget(tl)
        text.addWidget(_muted(subtitle))
        text.addStretch()
        row.addLayout(text, 1)
        row.addWidget(_img_label(illus, illus_w, illus_h))
        card.body.addLayout(row)
        self.root.addWidget(card)


class StatCard(CardWidget):
    """首页统计卡片"""
    def __init__(self, title: str, value: str, unit: str, icon: FIF, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        _set_margins(layout, (14, 12, 14, 12), 5)
        top = QHBoxLayout()
        top.addWidget(StrongBodyLabel(title))
        top.addStretch()
        ico = QLabel()
        ico.setPixmap(icon.icon().pixmap(22, 22))
        top.addWidget(ico)
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
        grid_pen = QPen(QColor("#e5edf8"), 1)
        text_pen = QPen(QColor(C_MUTED))
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
        p.setPen(QPen(QColor("white"), 2))
        for x, y in pts:
            p.drawEllipse(x - 4, y - 4, 8, 8)
            p.setPen(text_pen)
            p.drawText(x - 6, y - 8, str(self._data[pts.index((x, y))]))
            p.setPen(QPen(QColor("white"), 2))
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
        p.fillPath(path_bg, QColor(C_PROGRESS_BG))
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

    def __init__(self, channel: str, tag: str, parent=None):
        super().__init__(parent)
        self.widget.setMinimumSize(960, 680)
        self.widget.setMaximumSize(1120, 820)
        self.yesButton.setText("关闭")
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
        self.cancelButton.hide()
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
        self.cancelButton.hide()
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
        self.cancel_requested.emit()
        super().accept()

    def reject(self):
        self.cancel_requested.emit()
        super().reject()
