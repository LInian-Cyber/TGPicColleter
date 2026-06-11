"""
ui.py  ——  纯视图层，与业务逻辑完全解耦。
所有与外部通信均通过 Signal 完成，页面不持有任何业务对象，
外部通过调用 setter 方法将数据推入 UI。

目录结构假设：
  tg_pic_collector/
    ui.py          ← 本文件
  ui/
    icons/         ← qfluentwidgets 图标由框架自带，无需本地文件
    download-illustration.png
    telegram-app-icon.png
    login-illustration.png
    settings-illustration.png
"""

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
    QHeaderView,
    QProgressBar,
    QScrollArea,
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
# 图标/插图目录：ui.py 的同级 ui/ 目录
_UI_DIR = Path(__file__).resolve().parent / "assets"

# 使用 QFluentWidgets 的主题颜色，支持深色/浅色模式自动切换
def get_theme_color(light_color: str, dark_color: str) -> str:
    """根据当前主题返回对应的颜色"""
    from qfluentwidgets import isDarkTheme
    return dark_color if isDarkTheme() else light_color

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
    ):
        self.name = name
        self.keyword = keyword
        self.status = status
        self.progress = progress
        self.downloaded = downloaded
        self.total = total


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

        self._status = BodyLabel("正在连接 Telegram…")
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

    def set_results(self, rows: list[dict]):
        self._progress.hide()
        self.cancelButton.hide()
        self._clear_results()
        image_total = sum(int(row.get("image_count", 0)) for row in rows)
        self._status.setText(
            f"找到 {len(rows)} 篇帖子，评论区共发现 {image_total} 张图片"
            if rows
            else "没有找到匹配的帖子"
        )
        if not rows:
            empty = SurfaceCard()
            empty.body.addWidget(SubtitleLabel("暂无搜索结果"))
            empty.body.addWidget(_muted("请检查频道地址与 Tag，或尝试扩大默认检查帖子数量。"))
            self._results_layout.addWidget(empty)
            return

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


# ──────────────────────────────────────────────────────────────
#  首页
# ──────────────────────────────────────────────────────────────
class HomePage(ScrollPage):
    # ── Signals（外部监听）
    new_task_requested = Signal()
    resume_task_requested = Signal()
    login_requested = Signal()
    open_folder_requested = Signal()
    history_requested = Signal()
    settings_requested = Signal()
    trend_period_changed = Signal(str)
    common_tag_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__("homePage", parent)

        # Hero 卡片
        hero = SurfaceCard()
        hero.setMinimumHeight(148)
        row = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(6)
        tl = TitleLabel("欢迎使用 Telegram 评论区图片下载器")
        tl.setObjectName("heroTitle")
        text.addWidget(tl)
        text.addWidget(BodyLabel("基于 Telethon 的高效工具，支持从频道评论区批量下载图片，"))
        text.addWidget(BodyLabel("按 Tag 管理、智能去重、安全稳定，轻松保存精彩内容。"))
        text.addStretch()
        row.addLayout(text, 1)
        row.addWidget(_img_label("download-illustration.png", 280, 120))
        hero.body.addLayout(row)
        self.root.addWidget(hero)

        # 账号状态卡片
        self._account_card = SurfaceCard()
        acct_row = QHBoxLayout()
        acct_row.setSpacing(14)
        # 头像
        self._avatar = QLabel("●")
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setFixedSize(50, 50)
        self._avatar.setObjectName("accountAvatar")
        acct_row.addWidget(self._avatar)
        # 文字
        acct_text = QVBoxLayout()
        acct_text.setSpacing(4)
        self._acct_name = SubtitleLabel("未登录")
        self._acct_sub = _muted("当前未登录 Telethon 账号，部分功能受限")
        acct_text.addWidget(self._acct_name)
        acct_text.addWidget(self._acct_sub)
        acct_row.addLayout(acct_text, 1)
        # 安全提示
        shield_row = QHBoxLayout()
        shield_row.setSpacing(6)
        shield_ico = QLabel()
        shield_ico.setPixmap(FIF.ACCEPT.icon().pixmap(16, 16))
        shield_row.addWidget(shield_ico)
        shield_row.addWidget(_muted("所有会话数据仅保存在本地，安全加密存储"))
        acct_row.addLayout(shield_row)
        acct_row.addSpacing(16)
        self._login_btn = PrimaryPushButton("前往登录", icon=FIF.PEOPLE)
        self._login_btn.clicked.connect(self.login_requested)
        acct_row.addWidget(self._login_btn)
        self._account_card.body.addLayout(acct_row)
        self.root.addWidget(self._account_card)

        # 统计卡片行
        stat_row = QHBoxLayout()
        self._stat_today = StatCard("今日下载", "0", "张图片", FIF.DOWNLOAD)
        self._stat_total = StatCard("累计下载", "0", "张图片", FIF.ALBUM)
        self._stat_tasks = StatCard("任务总数", "0", "个任务", FIF.DOCUMENT)
        self._stat_tags = StatCard("已保存 Tag", "0", "个标签", FIF.TAG)
        self._stat_disk = StatCard("磁盘占用", "0", "B", FIF.FOLDER)
        self._stat_active = StatCard("最近活跃时间", "-", "", FIF.HISTORY)
        for c in (self._stat_today, self._stat_total, self._stat_tasks,
                  self._stat_tags, self._stat_disk, self._stat_active):
            stat_row.addWidget(c)
        self.root.addLayout(stat_row)

        # 中部三列
        mid = QHBoxLayout()
        mid.setSpacing(14)

        # 趋势图
        self._trend_card = SurfaceCard("最近 7 天下载趋势")
        # 右上角「按天」下拉
        self._period_combo = ComboBox()
        self._period_combo.addItem("按天", userData="day")
        self._period_combo.addItem("按周", userData="week")
        self._period_combo.setFixedWidth(80)
        self._period_combo.currentIndexChanged.connect(self._on_period_changed)
        if tr := self._trend_card.title_row():
            tr.addWidget(self._period_combo)
        self._trend_chart = TrendChart()
        self._trend_card.body.addWidget(self._trend_chart)
        mid.addWidget(self._trend_card, 4)

        # 最近任务
        recent_card = SurfaceCard("最近任务")
        see_all = HyperlinkButton("", "查看全部")
        see_all.clicked.connect(self.history_requested)
        if tr := recent_card.title_row():
            tr.addWidget(see_all)
        self._recent_table = QTableWidget(0, 4)
        self._recent_table.setHorizontalHeaderLabels(["任务名称", "状态", "进度", "更新时间"])
        self._recent_table.verticalHeader().hide()
        self._recent_table.horizontalHeader().setStretchLastSection(True)
        self._recent_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._recent_table.setFixedHeight(190)
        self._recent_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._recent_table.setShowGrid(False)
        self._recent_table.setAlternatingRowColors(True)
        self._recent_table.setStyleSheet("""
            QTableWidget {
                border: none;
                background: transparent;
            }
            QTableWidget::item:hover {
                background: rgba(0, 0, 0, 0.05);
            }
        """)
        recent_card.body.addWidget(self._recent_table)
        mid.addWidget(recent_card, 5)

        # 快速操作
        quick_card = SurfaceCard("快速操作")
        self._btn_new_task = PrimaryPushButton("  新建下载任务", icon=FIF.DOWNLOAD)
        self._btn_new_task.setFixedHeight(36)
        self._btn_new_task.clicked.connect(self.new_task_requested)
        self._btn_resume = PushButton("  继续上次任务", icon=FIF.PLAY)
        self._btn_resume.setFixedHeight(36)
        self._btn_resume.clicked.connect(self.resume_task_requested)
        self._btn_open_folder = PushButton("  打开保存目录", icon=FIF.FOLDER)
        self._btn_open_folder.setFixedHeight(36)
        self._btn_open_folder.clicked.connect(self.open_folder_requested)
        quick_card.body.addWidget(self._btn_new_task)
        quick_card.body.addWidget(self._btn_resume)
        quick_card.body.addWidget(self._btn_open_folder)
        quick_card.body.addStretch()
        mid.addWidget(quick_card, 3)
        self.root.addLayout(mid)

        # 底部三列
        foot = QHBoxLayout()
        foot.setSpacing(14)
        # 默认设置摘要
        self._summary_card = SurfaceCard("默认设置摘要")
        self._summary_path = _muted("默认保存目录：-")
        self._summary_mode = _muted("默认保存模式：-")
        self._summary_card.body.addWidget(self._summary_path)
        self._summary_card.body.addWidget(self._summary_mode)
        self._settings_btn = TransparentPushButton("前往设置", icon=FIF.SETTING)
        self._settings_btn.setMinimumHeight(36)
        self._settings_btn.clicked.connect(self.settings_requested)
        self._summary_card.body.addWidget(self._settings_btn)
        foot.addWidget(self._summary_card, 1)
        # 常用 Tag
        self._tags_card = SurfaceCard("常用 Tag")
        self._tags_row = QHBoxLayout()
        self._tags_row.setSpacing(8)
        self._tags_card.body.addLayout(self._tags_row)
        foot.addWidget(self._tags_card, 1)
        self.set_common_tags([])
        # 使用提示
        tips_card = SurfaceCard("使用提示")
        tips_card.body.addWidget(
            _muted("在 设置 中可配置默认行为、过滤规则与保存模式，让下载更符合您的需求。")
        )
        foot.addWidget(tips_card, 1)
        self.root.addLayout(foot)
        self.root.addStretch()

    # ── Setters（由外部调用）
    def set_account(self, name: str = "", phone: str = ""):
        if name:
            self._acct_name.setText(name)
            self._acct_sub.setText(f"Telethon 用户 · {phone or '本地会话已连接'}")
            self._login_btn.setText("账号详情")
        else:
            self._acct_name.setText("未登录")
            self._acct_sub.setText("当前未登录 Telethon 账号，部分功能受限")
            self._login_btn.setText("前往登录")

    def set_summary(self, save_root: str, save_mode_label: str):
        self._summary_path.setText(f"默认保存目录：{save_root}")
        self._summary_mode.setText(f"默认保存模式：{save_mode_label}")

    def set_stats(self, today: int, total: int, tasks: int,
                  tags: int, disk_str: str, last_active: str):
        self._stat_today.set_value(str(today), "较昨日实时统计")
        self._stat_total.set_value(str(total), "累计总数")
        self._stat_tasks.set_value(str(tasks), "全部任务")
        self._stat_tags.set_value(str(tags), "自定义标签")
        self._stat_disk.set_value(disk_str, "本地存储占用")
        self._stat_active.set_value(last_active, "最近完成时间")

    def _on_period_changed(self, index: int):
        period = self._period_combo.itemData(index) or "day"
        self._trend_card.title_label.setText(
            "最近 7 周下载趋势" if period == "week" else "最近 7 天下载趋势"
        )
        self.trend_period_changed.emit(period)

    def set_trend(self, values: list[int], labels: list[str] | None = None):
        self._trend_chart.set_data(values, labels)

    def set_common_tags(self, tags: list[str]):
        while self._tags_row.count():
            item = self._tags_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._tags_card.title_label.setText(f"常用 Tag（{len(tags)}）" if tags else "常用 Tag")
        if not tags:
            self._tags_row.addWidget(_muted("暂无常用 Tag，完成带 Tag 的下载任务后会显示在这里。"))
        else:
            for tag in tags[:8]:
                text = tag if tag.startswith("#") else f"#{tag}"
                pill = TagPill(text)
                pill.clicked.connect(
                    lambda checked=False, value=tag: self.common_tag_requested.emit(value)
                )
                self._tags_row.addWidget(pill)
        self._tags_row.addStretch()

    def set_recent_tasks(self, rows: list[dict]):
        """rows: list of {name, status, progress, time}"""
        self._recent_table.setRowCount(0)
        status_colors = {
            "已完成": C_GREEN, "下载中": C_BLUE,
            "已暂停": C_ORANGE, "已取消": C_MUTED,
        }
        for rec in rows[:5]:
            r = self._recent_table.rowCount()
            self._recent_table.insertRow(r)
            # 名称
            self._recent_table.setItem(r, 0, QTableWidgetItem(rec.get("name", "-")))
            # 状态（带颜色）
            status = rec.get("status", "已完成")
            status_item = QTableWidgetItem(status)
            color = status_colors.get(status, C_MUTED)
            status_item.setForeground(QColor(color))
            self._recent_table.setItem(r, 1, status_item)
            # 进度（进度条 + 百分比，横向排列）
            prog = rec.get("progress", 100)
            prog_widget = QWidget()
            prog_widget.setStyleSheet("background: transparent;")  # 透明背景，继承表格悬停效果
            prog_layout = QHBoxLayout(prog_widget)
            prog_layout.setContentsMargins(8, 8, 8, 8)
            prog_layout.setSpacing(8)
            
            # 进度条
            bar = InlineProgress(prog)
            bar.setMinimumWidth(80)
            bar.setMaximumWidth(120)
            
            # 百分比标签，放在进度条右侧
            pct_label = QLabel(f"{prog}%")
            pct_label.setStyleSheet(f"color:{C_MUTED};font-size:11px;background:transparent;")
            pct_label.setFixedWidth(30)
            pct_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            
            prog_layout.addWidget(bar)
            prog_layout.addWidget(pct_label)
            prog_layout.addStretch()  # 推到左侧
            
            self._recent_table.setCellWidget(r, 2, prog_widget)
            self._recent_table.setRowHeight(r, 40)
            # 时间
            self._recent_table.setItem(r, 3, QTableWidgetItem(rec.get("time", "-")))


# ──────────────────────────────────────────────────────────────
#  下载任务页
# ──────────────────────────────────────────────────────────────
class TaskPage(ScrollPage):
    # ── Signals
    start_requested = Signal(dict)   # emit task params dict
    cancel_requested = Signal()
    pause_task_requested = Signal(int)   # row index
    delete_task_requested = Signal(int)  # row index
    open_folder_requested = Signal()
    open_current_folder_requested = Signal(str)
    pause_all_requested = Signal()
    clear_queue_requested = Signal()
    switch_account_requested = Signal()
    settings_requested = Signal()
    preview_requested = Signal(dict)
    save_template_requested = Signal(dict)
    resume_task_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("taskPage", parent)
        self._task_busy = False
        self._preview_busy = False
        self._default_save_root = ""
        self._default_mode_label = ""
        self._default_mode_key = ""
        self._channel_list = []  # 存储频道列表
        self._page_header("新建下载任务",
                          "默认行为来自 设置，您可在本页按需临时覆盖，上次使用的模式可一键复用。")

        # 提示横幅
        notice = SurfaceCard()
        notice_row = QHBoxLayout()
        ico = QLabel()
        ico.setPixmap(FIF.INFO.icon().pixmap(16, 16))
        notice_row.addWidget(ico)
        notice_row.addWidget(BodyLabel(
            "  默认保存模式：沿用上次设置，可在本页临时覆盖；更多默认规则请前往 设置。"))
        notice_row.addStretch()
        notice.body.addLayout(notice_row)
        self.root.addWidget(notice)

        # 账号栏
        self._acct_card = SurfaceCard()
        acct_row = QHBoxLayout()
        avatar = QLabel("●")
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFixedSize(42, 42)
        avatar.setObjectName("taskAccountAvatar")
        acct_row.addWidget(avatar)
        acct_info = QVBoxLayout()
        acct_info.setSpacing(2)
        self._acct_title_row = QHBoxLayout()
        self._acct_label = BodyLabel("当前账号")
        self._acct_label.setStyleSheet("font-weight:600;")
        self._acct_phone = _muted("未登录")
        self._acct_title_row.addWidget(self._acct_label)
        self._acct_title_row.addSpacing(8)
        self._acct_phone_label = BodyLabel("")
        self._acct_title_row.addWidget(self._acct_phone_label)
        self._acct_title_row.addStretch()
        self._acct_status = BodyLabel("● 未登录")
        self._acct_status.setObjectName("accountStatus")
        self._acct_title_row.addWidget(self._acct_status)
        acct_info.addLayout(self._acct_title_row)
        # 数据中心 / 会话位置
        detail_row = QHBoxLayout()
        self._dc_label = _muted("数据中心  —")
        self._dc_label.setWordWrap(False)
        self._session_label = _muted("会话存储位置  本地安全存储")
        self._session_label.setWordWrap(False)
        detail_row.addWidget(self._dc_label)
        detail_row.addSpacing(24)
        detail_row.addWidget(self._session_label)
        detail_row.addStretch()
        acct_info.addLayout(detail_row)
        acct_row.addLayout(acct_info, 1)
        self._switch_btn = PushButton("切换账号", icon=FIF.SYNC)
        self._switch_btn.clicked.connect(self.switch_account_requested)
        acct_row.addWidget(self._switch_btn)
        self._acct_card.body.addLayout(acct_row)
        self.root.addWidget(self._acct_card)

        # 主体：表单 + 右侧摘要
        body = QHBoxLayout()
        body.setSpacing(14)
        form_card = SurfaceCard()

        # 表单网格
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(16)
        form.setColumnStretch(1, 1)

        # 1. 频道
        form.addWidget(StrongBodyLabel("1. 频道 / 用户名 / ID"), 0, 0)
        self.channel_combo = EditableComboBox()
        self.channel_combo.setPlaceholderText("例如：@wallpapers，直接输入或从下拉历史选择")
        self.channel_combo.setMinimumHeight(36)
        # 移除 channel_row 包装，直接放入表单网格
        form.addWidget(self.channel_combo, 0, 1)

        # 2. Tag
        form.addWidget(StrongBodyLabel("2. Tag 关键词（可选）"), 1, 0)
        tag_col = QVBoxLayout()
        tag_col.setSpacing(6)
        tag_top = QHBoxLayout()
        self.tag_edit = LineEdit()
        self.tag_edit.setPlaceholderText("例如：壁纸")
        self._preview_btn = TransparentPushButton("搜索预览", icon=FIF.SEARCH)
        self._preview_btn.setMinimumHeight(36)
        self._preview_btn.clicked.connect(self._on_preview)
        tag_top.addWidget(self.tag_edit, 1)
        tag_top.addWidget(self._preview_btn)
        tag_col.addLayout(tag_top)
        self._common_tags_row = QHBoxLayout()
        self._common_tags_row.setSpacing(6)
        tag_col.addLayout(self._common_tags_row)
        self.set_common_tags([])
        form.addLayout(tag_col, 1, 1)

        # 3. 保存位置
        form.addWidget(StrongBodyLabel("3. 保存位置"), 2, 0)
        path_row = QHBoxLayout()
        self.path_edit = LineEdit()
        self._open_folder_btn = PushButton("打开目录", icon=FIF.FOLDER)
        self._open_folder_btn.clicked.connect(
            lambda: self.open_current_folder_requested.emit(self.path_edit.text().strip())
        )
        self._change_path_btn = PushButton("本次更改", icon=FIF.EDIT)
        self._change_path_btn.clicked.connect(self._choose_dir)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(self._open_folder_btn)
        path_row.addWidget(self._change_path_btn)
        form.addLayout(path_row, 2, 1)

        # 4. 保存模式
        form.addWidget(StrongBodyLabel("4. 保存模式（本次下载覆盖）"), 3, 0)
        mode_row = QHBoxLayout()
        self.mode_combo = ComboBox()
        self.mode_combo.setMinimumWidth(300)
        mode_row.addWidget(self.mode_combo, 1)
        mode_row.addStretch()
        form.addLayout(mode_row, 3, 1)

        # 5. 本次下载选项
        form.addWidget(StrongBodyLabel("5. 本次下载选项（仅此生效）"), 4, 0)
        opts_col = QVBoxLayout()
        opts_col.setSpacing(8)

        # 第一排：常规勾选项
        opts_row1 = QHBoxLayout()
        opts_row1.setSpacing(24)
        self.only_images_cb = CheckBox("仅下载图片")
        self.only_images_cb.setChecked(True)
        self.skip_dup_cb = CheckBox("跳过重复文件")
        self.skip_dup_cb.setChecked(True)
        self.include_replies_cb = CheckBox("包含回复中的图片")
        self.include_replies_cb.setChecked(True)
        self.open_after_cb = CheckBox("完成后打开目录")

        opts_row1.addWidget(self.only_images_cb)
        opts_row1.addWidget(self.skip_dup_cb)
        opts_row1.addWidget(self.include_replies_cb)
        opts_row1.addWidget(self.open_after_cb)
        opts_row1.addStretch()

        # 第二排：✨ 自动提取按钮链接的组合控件
        opts_row2 = QHBoxLayout()
        opts_row2.setSpacing(12)
        self.extract_btn_cb = CheckBox("提取底部按钮链接作为原图")
        self.extract_btn_cb.setChecked(True)

        self.btn_keyword_edit = LineEdit()
        self.btn_keyword_edit.setPlaceholderText("按钮文字包含，如：原图")
        self.btn_keyword_edit.setText("原图")
        self.btn_keyword_edit.setMinimumSize(160, 32)

        # 简单的 UI 交互：勾选才启用输入框
        self.extract_btn_cb.stateChanged.connect(
            lambda: self.btn_keyword_edit.setEnabled(self.extract_btn_cb.isChecked())
        )

        opts_row2.addWidget(self.extract_btn_cb)
        opts_row2.addWidget(self.btn_keyword_edit)
        opts_row2.addStretch()

        opts_col.addLayout(opts_row1)
        opts_col.addLayout(opts_row2)
        opts_col.addWidget(_muted("ⓘ  默认行为已记忆，上次选择可自动恢复。"))
        form.addLayout(opts_col, 4, 1)
        
        # 操作按钮
        form.addWidget(_divider(), 5, 0, 1, 2)
        btn_row = QHBoxLayout()
        self._start_btn = PrimaryPushButton("  开始下载", icon=FIF.DOWNLOAD)
        self._start_btn.clicked.connect(self._on_start)
        self._save_tpl_btn = PushButton("  保存为模板", icon=FIF.SAVE)
        self._save_tpl_btn.clicked.connect(self._on_save_template)
        self._reset_btn = PushButton("  重置本次覆盖", icon=FIF.RETURN)
        self._reset_btn.clicked.connect(self._on_reset)
        for button in (self._start_btn, self._save_tpl_btn, self._reset_btn):
            button.setMinimumSize(140, 36)
        self._cancel_btn = PushButton("  取消任务", icon=FIF.CANCEL)
        self._cancel_btn.setMinimumSize(140, 36)  # ✨ 替换 setFixedHeight(40)
        self._cancel_btn.hide()
        self._cancel_btn.clicked.connect(self.cancel_requested)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._save_tpl_btn)
        btn_row.addWidget(self._reset_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._cancel_btn)
        form.addLayout(btn_row, 6, 0, 1, 2)

        form_card.body.addLayout(form)
        body.addWidget(form_card, 3)

        # 右侧默认设置摘要
        summary_card = SurfaceCard("默认设置摘要")
        self._settings_link = TransparentPushButton("前往设置", icon=FIF.SETTING)
        self._settings_link.setMinimumHeight(36)
        self._settings_link.clicked.connect(self.settings_requested)
        if tr := summary_card.title_row():
            tr.addWidget(self._settings_link)
        items = [
            ("保存位置", "D:\\TelegramDownloads"),
            ("保存模式", "按 Tag 建文件夹"),
            ("文件命名", "{tag}_{date}_{index}"),
            ("仅下载图片", "开启"),
            ("跳过重复文件", "开启"),
            ("包含回复中的图片", "关闭"),
            ("完成后打开目录", "关闭"),
            ("并发下载数", "6"),
            ("请求间隔", "1.0 秒"),
            ("文件名长度限制", "100"),
        ]
        self._summary_labels: dict[str, QLabel] = {}
        for key, val in items:
            row2 = QHBoxLayout()
            row2.setSpacing(6)
            k_lbl = _muted(key)
            k_lbl.setFixedWidth(100)
            v_lbl = BodyLabel(val)
            v_lbl.setStyleSheet("font-size:12px;")
            row2.addWidget(k_lbl)
            row2.addWidget(v_lbl, 1)
            self._summary_labels[key] = v_lbl
            summary_card.body.addLayout(row2)
        summary_card.body.addWidget(_muted("ⓘ 以上为全局默认规则，可在本页临时覆盖。"))
        summary_card.body.addStretch()
        body.addWidget(summary_card, 1)
        self.root.addLayout(body)

        # 任务队列
        queue_card = SurfaceCard("任务队列")
        queue_header = QHBoxLayout()
        self._queue_count_badge = QLabel("0")
        self._queue_count_badge.setStyleSheet(
            f"background:{C_BLUE};color:white;border-radius:9px;"
            "padding:0 6px;font-size:11px;font-weight:700;"
        )
        self._queue_count_badge.setFixedHeight(18)
        queue_header.addWidget(SubtitleLabel("任务队列"))
        queue_header.addWidget(self._queue_count_badge)
        queue_header.addStretch()
        self._pause_all_btn = PushButton("全部暂停", icon=FIF.PAUSE)
        self._clear_queue_btn = PushButton("清空队列", icon=FIF.DELETE)
        self._pause_all_btn.clicked.connect(self.pause_all_requested)
        self._clear_queue_btn.clicked.connect(self.clear_queue_requested)
        queue_header.addWidget(self._pause_all_btn)
        queue_header.addWidget(self._clear_queue_btn)

        # 进度/状态栏
        self._progress_bar = ProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.hide()
        self._detail_label = _muted("暂无运行中的任务")

        self._queue_table = QTableWidget(0, 6)
        self._queue_table.setHorizontalHeaderLabels(
            ["任务名称", "关键词", "状态", "进度", "已下载", "操作"])
        self._queue_table.verticalHeader().hide()
        self._queue_table.horizontalHeader().setStretchLastSection(False)
        self._queue_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._queue_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._queue_table.setShowGrid(False)
        self._queue_table.setFixedHeight(175)
        self._queue_table.setStyleSheet("QTableWidget{border:none;}")

        queue_card.body.addLayout(queue_header)
        queue_card.body.addWidget(self._progress_bar)
        queue_card.body.addWidget(self._detail_label)
        queue_card.body.addWidget(self._queue_table)
        self.root.addWidget(queue_card)
        self.root.addStretch()

    def _get_channel_input(self) -> str:
        """辅助方法：智能获取频道ID"""
        text = self.channel_combo.text().strip()
        # 如果用户是从下拉框选的，提取出 userData (真实的 @username 或 ID)
        idx = self.channel_combo.findText(text)
        if idx >= 0:
            return self.channel_combo.itemData(idx) or text
        # 如果是用户纯手打的，直接返回手打文字
        return text
    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择图片保存位置", self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def _show_channel_menu(self):
        """显示频道选择菜单"""
        if not self._channel_list:
            InfoBar.info(
                title="提示",
                content="请先登录以加载频道列表",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return
        
        # 创建菜单
        menu = RoundMenu(parent=self)
        
        for ch in self._channel_list[:20]:  # 最多显示20个频道
            name = ch.get("name", "")
            ch_id = ch.get("id", "")
            avatar_bytes = ch.get("avatar", b"")
            
            display_text = f"{name} ({ch_id})" if name and ch_id else (ch_id or name)
            
            # 创建菜单项
            if avatar_bytes:
                pixmap = QPixmap()
                if pixmap.loadFromData(avatar_bytes):
                    # 缩放为16x16的圆形头像（菜单项较小）
                    scaled = pixmap.scaled(
                        16, 16,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    rounded = QPixmap(16, 16)
                    rounded.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(rounded)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addEllipse(0, 0, 16, 16)
                    painter.setClipPath(path)
                    painter.drawPixmap(0, 0, scaled)
                    painter.end()
                    
                    icon = QIcon(rounded)
                    action = Action(icon, display_text)
                else:
                    action = Action(FIF.PEOPLE, display_text)
            else:
                action = Action(FIF.PEOPLE, display_text)
            
            # 连接点击事件
            action.triggered.connect(
                lambda checked=False, text=ch_id: self.channel_edit.setText(text)
            )
            menu.addAction(action)
        
        if not menu.actions():
            action = Action(FIF.INFO, "暂无可用频道")
            action.setEnabled(False)
            menu.addAction(action)
        
        # 显示菜单
        menu.exec(self._channel_list_btn.mapToGlobal(self._channel_list_btn.rect().bottomLeft()))

    def _on_start(self):
        params = {
            "channel": self._get_channel_input(),  # ✨ 改用辅助方法提取
            "tag": self.tag_edit.text().strip(),
            "save_root": self.path_edit.text().strip(),
            "save_mode": self.mode_combo.currentData(),
            "only_images": self.only_images_cb.isChecked(),
            "skip_duplicates": self.skip_dup_cb.isChecked(),
            "include_replies": self.include_replies_cb.isChecked(),
            "extract_button_link": self.extract_btn_cb.isChecked(),
            "button_keyword": self.btn_keyword_edit.text().strip(),
            "open_after": self.open_after_cb.isChecked(),
        }
        self.start_requested.emit(params)

    def _on_preview(self):
        self.preview_requested.emit(
            {
                "channel": self._get_channel_input(),  # ✨ 改用辅助方法提取
                "tag": self.tag_edit.text().strip(),
            }
        )

    def _on_save_template(self):
        """保存当前配置为模板（实际上就是保存到默认设置）"""
        params = {
            "save_root": self.path_edit.text().strip(),
            "save_mode": self.mode_combo.currentData(),
            "only_images": self.only_images_cb.isChecked(),
            "skip_duplicates": self.skip_dup_cb.isChecked(),
            "include_replies": self.include_replies_cb.isChecked(),
            "extract_button_link": self.extract_btn_cb.isChecked(),
            "button_keyword": self.btn_keyword_edit.text().strip(),
            "open_after": self.open_after_cb.isChecked(),
        }
        self.save_template_requested.emit(params)

    def _on_reset(self):
        """重置本次覆盖，恢复到默认设置"""
        self.path_edit.setText(self._default_save_root)
        idx = self.mode_combo.findData(self._default_mode_key)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)
        self.only_images_cb.setChecked(True)
        self.skip_dup_cb.setChecked(True)
        self.include_replies_cb.setChecked(True)
        self.extract_btn_cb.setChecked(True)
        self.btn_keyword_edit.setText("原图")
        self.open_after_cb.setChecked(False)

    # ── Setters
    def set_account(self, name: str = "", phone: str = "", dc: str = ""):
        if name:
            self._acct_phone_label.setText(f"Telethon 用户 · {phone}")
            self._acct_status.setText("● 已登录")
            self._acct_status.setProperty("statusType", "success")
            self._acct_status.setStyle(self._acct_status.style())
            if dc:
                self._dc_label.setText(f"数据中心  {dc}")
        else:
            self._acct_phone_label.setText("")
            self._acct_status.setText("● 未登录")
            self._acct_status.setProperty("statusType", "muted")
            self._acct_status.setStyle(self._acct_status.style())

    def set_defaults(self, save_root: str, save_mode_label: str,
                     save_mode_key: str = ""):
        self._default_save_root = save_root
        self._default_mode_label = save_mode_label
        self._default_mode_key = save_mode_key
        self.path_edit.setText(save_root)
        if "保存位置" in self._summary_labels:
            self._summary_labels["保存位置"].setText(save_root)
        if "保存模式" in self._summary_labels:
            self._summary_labels["保存模式"].setText(save_mode_label)
        # sync combo
        idx = self.mode_combo.findData(save_mode_key)
        if idx >= 0:
            self.mode_combo.setCurrentIndex(idx)

    def restore_last_params(self, channel: str, tag: str):
        """恢复上次的任务参数"""
        self.channel_combo.setText(channel)  # ✨ 换成 combo 的 setText
        self.tag_edit.setText(tag)

    def add_channel_history(self, channels: list[dict]):
        """添加频道列表到可编辑下拉框"""
        self._channel_list = channels
        self.channel_combo.clear()

        if not channels:
            return

        for ch in channels[:20]:  # 最多显示20个频道
            name = ch.get("name", "")
            ch_id = ch.get("id", "")
            avatar_bytes = ch.get("avatar", b"")

            # 显示文本，例如: 精彩壁纸 (@wallpapers)
            display_text = f"{name} ({ch_id})" if name and ch_id else (ch_id or name)

            if avatar_bytes:
                pixmap = QPixmap()
                if pixmap.loadFromData(avatar_bytes):
                    # 缩放为16x16的圆形头像
                    scaled = pixmap.scaled(
                        16, 16,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation
                    )
                    rounded = QPixmap(16, 16)
                    rounded.fill(Qt.GlobalColor.transparent)
                    painter = QPainter(rounded)
                    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                    path = QPainterPath()
                    path.addEllipse(0, 0, 16, 16)
                    painter.setClipPath(path)
                    painter.drawPixmap(0, 0, scaled)
                    painter.end()

                    icon = QIcon(rounded)
                    # ✨ 核心修复：将第一个参数改为文字 display_text，并通过关键字显式传递 icon
                    self.channel_combo.addItem(display_text, icon=icon, userData=ch_id)
                    continue

            # ✨ 同样确保第一个参数是文字
            self.channel_combo.addItem(display_text, userData=ch_id)

    def set_rule_summary(
        self,
        filename_template: str,
        preserve_original_name: bool,
        duplicate_mode: str,
        open_after_download: bool,
    ):
        if "文件命名" in self._summary_labels:
            self._summary_labels["文件命名"].setText(
                "优先保留原名" if preserve_original_name else filename_template
            )
        if "跳过重复文件" in self._summary_labels:
            duplicate_labels = {"skip": "开启", "overwrite": "覆盖", "rename": "自动重命名"}
            self._summary_labels["跳过重复文件"].setText(
                duplicate_labels.get(duplicate_mode, duplicate_mode)
            )
        if "完成后打开目录" in self._summary_labels:
            self._summary_labels["完成后打开目录"].setText(
                "开启" if open_after_download else "关闭"
            )

    def add_mode_item(self, text: str, key: str):
        self.mode_combo.addItem(text, userData=key)

    def set_common_tags(self, tags: list[str]):
        while self._common_tags_row.count():
            item = self._common_tags_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._common_tags_row.addWidget(_muted("常用 Tag："))
        if not tags:
            self._common_tags_row.addWidget(_muted("暂无"))
        else:
            for tag in tags[:6]:
                text = tag if tag.startswith("#") else f"#{tag}"
                pill = TagPill(text)
                pill.clicked.connect(
                    lambda checked=False, value=tag: self.tag_edit.setText(value.lstrip("#"))
                )
                self._common_tags_row.addWidget(pill)
        self._common_tags_row.addStretch()

    def set_busy(self, busy: bool):
        self._task_busy = busy
        self._progress_bar.setVisible(busy)
        self._cancel_btn.setVisible(busy)
        self._sync_action_states()

    def set_preview_busy(self, busy: bool):
        self._preview_busy = busy
        self._preview_btn.setText("正在预览…" if busy else "搜索预览")
        self._sync_action_states()

    def _sync_action_states(self):
        busy = self._task_busy or self._preview_busy
        self._start_btn.setDisabled(busy)
        self._preview_btn.setDisabled(busy)

    def set_detail(self, text: str):
        self._detail_label.setText(text)

    def set_queue_tasks(self, tasks: list[TaskRow]):
        self._queue_table.setUpdatesEnabled(False)  # 暂停重绘
        self._queue_table.setRowCount(0)
        self._queue_count_badge.setText(str(len(tasks)))
        status_colors = {
            "下载中": C_BLUE, "排队中": C_ORANGE,
            "已暂停": C_MUTED, "已完成": C_GREEN, "已取消": C_MUTED,
        }
        for i, t in enumerate(tasks):
            r = self._queue_table.rowCount()
            self._queue_table.insertRow(r)
            # 名称（两行：频道名 + @username）
            name_widget = QWidget()
            name_layout = QVBoxLayout(name_widget)
            name_layout.setContentsMargins(4, 2, 4, 2)
            name_layout.setSpacing(1)
            name_layout.addWidget(BodyLabel(t.name))
            self._queue_table.setCellWidget(r, 0, name_widget)
            self._queue_table.setItem(r, 1, QTableWidgetItem(t.keyword))
            # 状态
            status_item = QTableWidgetItem(t.status)
            status_item.setForeground(QColor(status_colors.get(t.status, C_MUTED)))
            self._queue_table.setItem(r, 2, status_item)
            # 进度条
            prog_w = QWidget()
            pl = QHBoxLayout(prog_w)
            pl.setContentsMargins(4, 10, 4, 10)
            bar = InlineProgress(t.progress)
            pct = QLabel(f"{t.progress}%")
            pct.setStyleSheet(f"color:{C_MUTED};font-size:11px;")
            pct.setFixedWidth(36)
            pl.addWidget(bar)
            pl.addWidget(pct)
            self._queue_table.setCellWidget(r, 3, prog_w)
            self._queue_table.setItem(r, 4, QTableWidgetItem(
                f"{t.downloaded} / {t.total}"))
            # 操作按钮
            ops_w = QWidget()
            ops_l = QHBoxLayout(ops_w)
            ops_l.setContentsMargins(4, 4, 4, 4)
            ops_l.setSpacing(4)
            pause_btn = ToolButton(FIF.PAUSE)
            pause_btn.setFixedSize(28, 28)
            pause_btn.clicked.connect(lambda _, idx=i: self.pause_task_requested.emit(idx))
            del_btn = ToolButton(FIF.DELETE)
            del_btn.setFixedSize(28, 28)
            del_btn.clicked.connect(lambda _, idx=i: self.delete_task_requested.emit(idx))
            ops_l.addWidget(pause_btn)
            ops_l.addWidget(del_btn)
            self._queue_table.setCellWidget(r, 5, ops_w)
            self._queue_table.setRowHeight(r, 44)
        self._queue_table.setUpdatesEnabled(True)  # 恢复重绘

# ──────────────────────────────────────────────────────────────
#  登录中心
# ──────────────────────────────────────────────────────────────
class LoginPage(ScrollPage):
    send_code_requested = Signal(str)          # phone
    login_requested = Signal(str, str, str)    # phone, code, password
    qr_requested = Signal()
    logout_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("loginPage", parent)
        self._qr_requested_once = False
        self._is_logged_in = False
        self._page_header("登录中心", "登录您的 Telegram 账号以使用全部功能",
                          illus="login-illustration.png", illus_w=200, illus_h=90)

        # 安全提示横幅
        self._banner = SurfaceCard()
        banner_row = QHBoxLayout()
        ico = QLabel()
        ico.setPixmap(FIF.ACCEPT.icon().pixmap(18, 18))
        banner_row.addWidget(ico)
        banner_row.addWidget(BodyLabel(
            "  本地会话数据安全存储在此设备中，仅用于与 Telegram 建立连接，不会上传或分享任何信息。"))
        banner_row.addStretch()
        close_ico = ToolButton(FIF.CLOSE)
        close_ico.setFixedSize(22, 22)
        close_ico.clicked.connect(lambda: self._banner.hide())
        banner_row.addWidget(close_ico)
        self._banner.body.addLayout(banner_row)
        self.root.addWidget(self._banner)

        # 用户信息卡片（已登录时显示）
        self._user_info_card = self._build_user_info_card()
        self.root.addWidget(self._user_info_card)
        self._user_info_card.hide()

        # 登录表单容器（未登录时显示）
        self._login_container = QWidget()
        self._login_container.setStyleSheet("background:transparent;")
        login_layout = QVBoxLayout(self._login_container)

        # 两列登录
        cols = QHBoxLayout()
        cols.setSpacing(16)

        # ① 扫码登录
        qr_card = SurfaceCard()
        qr_card.setMinimumWidth(360)
        qr_card.setMaximumWidth(440)
        qr_header = QHBoxLayout()
        badge = QLabel("1")
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background:{C_BLUE};color:white;border-radius:13px;font-weight:700;"
        )
        qr_header.addWidget(badge)
        qr_title = QVBoxLayout()
        qr_title.setSpacing(2)
        qr_title.addWidget(SubtitleLabel("扫码登录（推荐）"))
        qr_title.addWidget(_muted("使用 Telegram 手机端扫描二维码登录"))
        qr_header.addLayout(qr_title)
        qr_header.addStretch()
        qr_card.body.addLayout(qr_header)

        self._qr_label = QLabel("请使用 Telegram 扫码登录")
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setWordWrap(True)
        self._qr_label.setFixedSize(280, 280)
        self._qr_label.setObjectName("qrCodeLabel")
        qr_card.body.addWidget(self._qr_label, alignment=Qt.AlignmentFlag.AlignCenter)
        qr_refresh = PushButton("  刷新二维码", icon=FIF.SYNC)
        qr_refresh.setFixedHeight(36)
        qr_refresh.clicked.connect(self.qr_requested)
        qr_card.body.addWidget(qr_refresh)
        qr_card.body.addWidget(
            _muted("二维码 2 分钟内有效"), alignment=Qt.AlignmentFlag.AlignCenter)
        cols.addWidget(qr_card, 1)

        # ② 手机号登录
        phone_card = SurfaceCard()
        phone_card.setMinimumWidth(460)
        ph_header = QHBoxLayout()
        badge2 = QLabel("2")
        badge2.setFixedSize(26, 26)
        badge2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge2.setStyleSheet(
            f"background:{C_BLUE};color:white;border-radius:13px;font-weight:700;"
        )
        ph_header.addWidget(badge2)
        ph_title = QVBoxLayout()
        ph_title.setSpacing(2)
        ph_title.addWidget(SubtitleLabel("手机号登录"))
        ph_title.addWidget(_muted("使用手机号接收验证码登录"))
        ph_header.addLayout(ph_title)
        ph_header.addStretch()
        phone_card.body.addLayout(ph_header)

        # 国家/地区选择
        phone_card.body.addWidget(StrongBodyLabel("国家 / 地区"))
        self._country_combo = ComboBox()
        for country, code in COUNTRY_CODES:
            self._country_combo.addItem(f"🌐  {country} ({code})", userData=code)
        phone_card.body.addWidget(self._country_combo)

        phone_card.body.addWidget(StrongBodyLabel("手机号"))
        self.phone_edit = LineEdit()
        self.phone_edit.setPlaceholderText("请输入不含区号的手机号，或输入 + 开头完整号码")
        phone_card.body.addWidget(self.phone_edit)

        code_row = QHBoxLayout()
        code_row.addWidget(StrongBodyLabel("验证码"))
        code_row.addStretch()
        self._send_code_btn = PushButton("发送验证码")
        self._send_code_btn.setObjectName("sendCodeButton")
        self._send_code_btn.clicked.connect(self._emit_send_code)
        code_row.addWidget(self._send_code_btn)
        phone_card.body.addLayout(code_row)
        self.code_edit = LineEdit()
        self.code_edit.setPlaceholderText("请输入验证码")
        phone_card.body.addWidget(self.code_edit)

        phone_card.body.addWidget(StrongBodyLabel("两步验证密码（如已开启）"))
        self.password_edit = PasswordLineEdit()
        self.password_edit.setPlaceholderText("请输入两步验证密码（可选）")
        phone_card.body.addWidget(self.password_edit)

        login_btn = PrimaryPushButton("  登录", icon=FIF.SEND)
        login_btn.setFixedHeight(36)
        login_btn.clicked.connect(self._emit_login)
        phone_card.body.addWidget(login_btn)
        phone_card.body.addWidget(_muted("登录即表示您同意仅在本地安全存储会话数据"))
        cols.addWidget(phone_card, 1)
        login_layout.addLayout(cols)

        # 设备与会话信息
        session_card = SurfaceCard("设备与会话信息")
        info_row = QHBoxLayout()
        info_row.setSpacing(16)
        for icon, label, val in [
            (FIF.PEOPLE, "当前状态", "未登录"),
            (FIF.ALBUM, "会话类型", "本地 Telethon Session"),
            (FIF.FOLDER, "数据存储位置", "本地加密存储"),
        ]:
            info_card = CardWidget()
            info_layout = QVBoxLayout(info_card)
            info_layout.setContentsMargins(14, 12, 14, 12)
            ico_row = QHBoxLayout()
            ico_w = QLabel()
            ico_w.setPixmap(icon.icon().pixmap(20, 20))
            ico_row.addWidget(ico_w)
            ico_row.addStretch()
            info_layout.addLayout(ico_row)
            info_layout.addWidget(_muted(label))
            v_lbl = BodyLabel(val)
            v_lbl.setStyleSheet("font-weight:600;")
            v_lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            info_layout.addWidget(v_lbl)
            info_row.addWidget(info_card, 1)
            if label == "当前状态":
                self._session_state_label = v_lbl
        session_card.body.addLayout(info_row)

        # 会话特性说明行
        feat_row = QHBoxLayout()
        feat_row.setSpacing(16)
        for ico, title, desc in [
            (FIF.ACCEPT, "登录后可自动保存会话", "下次启动时将自动恢复登录状态"),
            (FIF.CLOUD, "会话数据仅存储在本地", "不会上传到任何服务器"),
            (FIF.SYNC, "随时可在设置中登出", "退出后会话数据将被清除"),
        ]:
            feat_card = CardWidget()
            fl = QHBoxLayout(feat_card)
            fl.setContentsMargins(12, 10, 12, 10)
            ico_lbl = QLabel()
            ico_lbl.setPixmap(ico.icon().pixmap(22, 22))
            fl.addWidget(ico_lbl)
            text_v = QVBoxLayout()
            text_v.setSpacing(2)
            text_v.addWidget(BodyLabel(title))
            text_v.addWidget(_muted(desc))
            fl.addLayout(text_v, 1)
            feat_row.addWidget(feat_card, 1)
        session_card.body.addLayout(feat_row)
        self._logout_btn = PushButton("退出当前账号", icon=FIF.POWER_BUTTON)
        self._logout_btn.hide()
        self._logout_btn.setObjectName("logoutButton")
        self._logout_btn.clicked.connect(self.logout_requested)
        session_card.body.addWidget(self._logout_btn, alignment=Qt.AlignmentFlag.AlignRight)
        login_layout.addWidget(session_card)
        self.root.addWidget(self._login_container)
        self.root.addStretch()

    def _build_user_info_card(self) -> QWidget:
        """构建用户信息显示卡片"""
        card = SurfaceCard("账户信息")
        
        # 用户信息行
        user_row = QHBoxLayout()
        # 头像
        self._user_avatar = QLabel()
        self._user_avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._user_avatar.setFixedSize(80, 80)
        self._user_avatar.setStyleSheet(
            "background:#eaf1fc;color:#8a99b2;border-radius:40px;font-size:32px;"
        )
        self._user_avatar.setText("●")
        user_row.addWidget(self._user_avatar)
        user_row.addSpacing(20)
        
        # 用户详情
        user_details = QVBoxLayout()
        user_details.setSpacing(8)
        self._user_name_label = TitleLabel("用户名")
        self._user_phone_label = BodyLabel("手机号")
        self._user_status_label = BodyLabel("● 已登录")
        self._user_status_label.setStyleSheet("color:#18a66a;font-weight:600;")
        user_details.addWidget(self._user_name_label)
        user_details.addWidget(self._user_phone_label)
        user_details.addWidget(self._user_status_label)
        user_row.addLayout(user_details, 1)
        
        card.body.addLayout(user_row)
        card.body.addWidget(_divider())
        
        # 会话信息网格
        info_grid = QGridLayout()
        info_grid.setHorizontalSpacing(20)
        info_grid.setVerticalSpacing(12)
        
        self._user_dc_label = BodyLabel("数据中心：-")
        self._user_session_label = BodyLabel("会话类型：本地 Telethon Session")
        self._user_storage_label = BodyLabel("存储位置：本地加密存储")
        
        info_grid.addWidget(self._user_dc_label, 0, 0)
        info_grid.addWidget(self._user_session_label, 0, 1)
        info_grid.addWidget(self._user_storage_label, 1, 0, 1, 2)
        
        card.body.addLayout(info_grid)
        card.body.addWidget(_divider())
        
        # 操作按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._user_logout_btn = PushButton("退出登录", icon=FIF.POWER_BUTTON)
        self._user_logout_btn.setMinimumSize(140, 36)
        self._user_logout_btn.clicked.connect(self.logout_requested)
        btn_row.addWidget(self._user_logout_btn)
        card.body.addLayout(btn_row)
        
        return card
    
    def set_user_avatar(self, avatar_bytes: bytes):
        """设置用户头像"""
        if avatar_bytes:
            pixmap = QPixmap()
            if pixmap.loadFromData(avatar_bytes):
                # 将头像裁剪为圆形
                scaled = pixmap.scaled(
                    80, 80,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation
                )
                # 创建圆形遮罩
                rounded = QPixmap(80, 80)
                rounded.fill(Qt.GlobalColor.transparent)
                painter = QPainter(rounded)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = QPainterPath()
                path.addEllipse(0, 0, 80, 80)
                painter.setClipPath(path)
                painter.drawPixmap(0, 0, scaled)
                painter.end()
                
                self._user_avatar.setPixmap(rounded)
                self._user_avatar.setText("")
            else:
                # 加载失败，显示默认图标
                self._user_avatar.setText("●")
        else:
            # 没有头像，显示默认图标
            self._user_avatar.setText("●")

    def showEvent(self, event):
        super().showEvent(event)
        # 只有在未登录时才自动请求二维码
        if not self._qr_requested_once and not self._is_logged_in:
            self._qr_requested_once = True
            QTimer.singleShot(0, self.qr_requested.emit)

    def _full_phone(self) -> str:
        phone = self.phone_edit.text().strip().replace(" ", "").replace("-", "")
        if phone.startswith("+"):
            return phone
        code = self._country_combo.currentData() or "+86"
        return f"{code}{phone.lstrip('0')}"

    def _emit_send_code(self):
        self.send_code_requested.emit(self._full_phone())

    def _emit_login(self):
        self.login_requested.emit(
            self._full_phone(),
            self.code_edit.text().strip(),
            self.password_edit.text(),
        )

    def show_qr(self, url: str):
        image = qrcode.make(url).get_image().convert("RGBA")
        logo_path = _UI_DIR / "telegram-app-icon.png"
        if logo_path.exists():
            logo = Image.open(logo_path).convert("RGBA")
            logo.thumbnail((60, 60), Image.Resampling.LANCZOS)
            logo_bg = Image.new("RGBA", (76, 76), "white")
            logo_bg.paste(logo, ((76 - logo.width) // 2, (76 - logo.height) // 2), logo)
            image.paste(logo_bg, ((image.width - 76) // 2, (image.height - 76) // 2), logo_bg)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        px = QPixmap()
        px.loadFromData(buf.getvalue())
        self._qr_label.setPixmap(
            px.scaled(260, 260,
                      Qt.AspectRatioMode.KeepAspectRatio,
                      Qt.TransformationMode.SmoothTransformation))

    def set_qr_message(self, message: str, allow_auto_retry: bool = False):
        self._qr_label.clear()
        self._qr_label.setText(message)
        if allow_auto_retry:
            self._qr_requested_once = False

    def set_phone(self, phone: str):
        if not phone:
            return
        for index in range(self._country_combo.count()):
            code = self._country_combo.itemData(index)
            if phone.startswith(code):
                self._country_combo.setCurrentIndex(index)
                self.phone_edit.setText(phone[len(code):])
                return
        self.phone_edit.setText(phone)

    def set_account(self, name: str = "", phone: str = ""):
        if name:
            self._is_logged_in = True
            # 更新用户信息卡片
            self._user_name_label.setText(name)
            self._user_phone_label.setText(f"手机号：{phone or '未知'}")
            # 显示用户信息，隐藏登录表单
            self._user_info_card.show()
            self._login_container.hide()
            # 更新会话状态标签
            self._session_state_label.setText(f"已登录 · {name}")
            self._session_state_label.setProperty("statusType", "success")
            self._session_state_label.setStyle(self._session_state_label.style())
            self._logout_btn.show()
        else:
            self._is_logged_in = False
            # 显示登录表单，隐藏用户信息
            self._user_info_card.hide()
            self._login_container.show()
            # 更新会话状态标签
            self._session_state_label.setText("未登录")
            self._session_state_label.setProperty("statusType", "info")
            self._session_state_label.setStyle(self._session_state_label.style())
            self._logout_btn.hide()


# ──────────────────────────────────────────────────────────────
#  下载历史页
# ──────────────────────────────────────────────────────────────
class HistoryPage(ScrollPage):
    clear_requested = Signal()
    open_folder_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("historyPage", parent)
        self._page_header("下载历史", "查看本地保存的任务记录与结果",
                          illus="download-illustration.png")

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

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["频道", "Tag", "状态", "匹配帖子", "下载图片", "完成时间"])
        self._table.verticalHeader().hide()
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        self._table.setMinimumHeight(420)
        self._table.setStyleSheet("""
            QTableWidget {
                border: none;
                background: transparent;
            }
            QTableWidget::item:hover {
                background: rgba(0, 0, 0, 0.05);
            }
        """)
        card.body.addWidget(self._table)
        self.root.addWidget(card)
        self.root.addStretch()

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
                    }.get(v, C_MUTED)
                    item.setForeground(QColor(color))
                self._table.setItem(r, c, item)
            self._table.setRowHeight(r, 38)


# ──────────────────────────────────────────────────────────────
#  设置页（带真实 Tab 切换）
# ──────────────────────────────────────────────────────────────
class SettingsPage(ScrollPage):
    save_requested = Signal(dict)   # emit settings dict
    logout_requested = Signal()
    cache_clear_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("settingsPage", parent)
        self._page_header("设置", "管理默认下载行为、保存规则、会话与主题外观",
                          illus="settings-illustration.png", illus_w=260, illus_h=100)

        # Tab 切换（真实 SegmentedWidget）
        self._seg = SegmentedWidget()
        self._stack = QStackedWidget()
        tabs = [
            ("常规", self._build_general()),
            ("下载默认值", self._build_download_defaults()),
            ("保存规则", self._build_save_rules()),
            ("会话与安全", self._build_session()),
            ("外观", self._build_appearance()),
        ]
        for i, (name, widget) in enumerate(tabs):
            self._stack.addWidget(widget)
            self._seg.addItem(
                routeKey=f"tab_{i}",
                text=name,
                onClick=lambda checked=False, idx=i: self._stack.setCurrentIndex(idx),
            )
        self._seg.setCurrentItem("tab_0")
        self.root.addWidget(self._seg)
        self.root.addWidget(self._stack)

        # 底部操作栏
        foot = SurfaceCard()
        foot_row = QHBoxLayout()
        foot_row.addWidget(_muted("ⓘ  设置仅在本机生效，不会上传到云端。"))
        foot_row.addStretch()

        restore_btn = PushButton("恢复默认", icon=FIF.RETURN)
        restore_btn.clicked.connect(self._restore_defaults)

        save_btn = PrimaryPushButton("保存设置", icon=FIF.SAVE)
        save_btn.clicked.connect(self._on_save)

        # ✨ 统一将两个按钮的尺寸设置为相同的最小宽高（例如宽 140，高 36）
        for button in (restore_btn, save_btn):
            button.setMinimumSize(140, 36)

        foot_row.addWidget(restore_btn)
        foot_row.addWidget(save_btn)
        foot.body.addLayout(foot_row)
        self.root.addWidget(foot)

    # ── Tab 页面构建
    def _build_general(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        _set_margins(layout, (0, 12, 0, 0), 14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 2)

        # 下载默认值
        dl = SurfaceCard("下载默认值")
        dl.body.addWidget(StrongBodyLabel("默认保存目录"))
        path_row = QHBoxLayout()
        self.path_edit = LineEdit()
        browse_btn = PushButton("浏览", icon=FIF.FOLDER)
        browse_btn.clicked.connect(self._choose_dir)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_btn)
        dl.body.addLayout(path_row)
        dl.body.addWidget(StrongBodyLabel("默认保存模式"))
        self.mode_combo = ComboBox()
        for text, key in [
            ("按频道 / Tag 建立文件夹", "channel_tag"),
            ("按 Tag 建立文件夹", "tag"),
            ("按 Tag / 帖子建立文件夹", "post"),
            ("全部保存到同一文件夹", "flat"),
        ]:
            self.mode_combo.addItem(text, userData=key)
        dl.body.addWidget(self.mode_combo)
        dl.body.addWidget(_muted("按每个 Tag 自动创建独立文件夹，便于分类管理。"))
        dl.body.addWidget(StrongBodyLabel("默认检查帖子数量"))
        self.max_posts = SpinBox()
        self.max_posts.setRange(1, 5000)
        self.max_posts.setValue(200)
        self.max_posts.setMinimumSize(140, 36)
        dl.body.addWidget(self.max_posts)
        grid.addWidget(dl, 0, 0)

        # 启动行为
        launch = SurfaceCard("启动行为")
        for label, desc, attr in [
            ("启动时恢复上次下载配置", "应用启动时自动恢复上次会话和下载配置。", "restore_cb"),
            ("默认沿用上次模式", "新建任务时自动沿用上一次使用的保存模式。", "last_mode_cb"),
            ("新建任务时自动带入最近 Tag", "从最近使用的 Tag 列表中自动填充。", "auto_tag_cb"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(12)
            text_v = QVBoxLayout()
            text_v.setSpacing(2)
            text_v.addWidget(StrongBodyLabel(label))
            text_v.addWidget(_muted(desc))
            row.addLayout(text_v, 1)
            sw = SwitchButton()
            sw.setChecked(True)
            setattr(self, attr, sw)
            row.addWidget(sw)
            launch.body.addLayout(row)
            launch.body.addWidget(_divider())
        grid.addWidget(launch, 0, 1)

        # 当前默认摘要（右侧固定列）
        self._summary_side = SurfaceCard("当前默认摘要", "以下为当前默认设置，新建下载任务将应用这些配置。")
        self._summary_path_lbl = _muted("保存目录\n-")
        self._summary_mode_lbl = _muted("保存模式\n-")
        self._summary_dup_lbl = _muted("重复文件处理\n-")
        self._summary_fn_lbl = _muted("文件命名规则\n-")
        for lbl in (self._summary_path_lbl, self._summary_mode_lbl,
                    self._summary_dup_lbl, self._summary_fn_lbl):
            self._summary_side.body.addWidget(lbl)
        self._summary_side.body.addStretch()
        grid.addWidget(self._summary_side, 0, 2, 3, 1)

        layout.addLayout(grid)
        return w

    def _build_download_defaults(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        _set_margins(layout, (0, 12, 0, 0), 14)
        card = SurfaceCard("并发与速率")
        card.body.addWidget(StrongBodyLabel("并发下载数"))
        self.concurrency_spin = SpinBox()
        self.concurrency_spin.setRange(1, 20)
        self.concurrency_spin.setValue(6)
        self.concurrency_spin.setMinimumSize(140, 36)
        card.body.addWidget(self.concurrency_spin)
        card.body.addWidget(StrongBodyLabel("请求间隔（秒）"))
        self.interval_spin = DoubleSpinBox()
        self.interval_spin.setRange(0, 10)
        self.interval_spin.setSingleStep(0.1)
        self.interval_spin.setDecimals(1)
        self.interval_spin.setValue(1.0)
        self.interval_spin.setMinimumSize(140, 36)
        card.body.addWidget(self.interval_spin)
        card.body.addWidget(StrongBodyLabel("文件名长度限制"))
        self.fn_len_spin = SpinBox()
        self.fn_len_spin.setRange(20, 255)
        self.fn_len_spin.setValue(100)
        self.fn_len_spin.setMinimumSize(140, 36)
        card.body.addWidget(self.fn_len_spin)
        layout.addWidget(card)
        layout.addStretch()
        return w

    def _build_save_rules(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        _set_margins(layout, (0, 12, 0, 0), 14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        # Tag 为空时处理
        tag_empty = SurfaceCard("Tag 为空时的处理", "当未识别到 Tag 时的默认处理方式。")
        self.tag_empty_combo = ComboBox()
        for text, key in [
            ("保存到【未分类】文件夹", "uncategorized"),
            ("跳过该帖子", "skip"),
            ("使用频道名作为 Tag", "channel"),
        ]:
            self.tag_empty_combo.addItem(text, userData=key)
        tag_empty.body.addWidget(self.tag_empty_combo)
        grid.addWidget(tag_empty, 0, 0)

        # 重复文件处理
        dup = SurfaceCard("重复文件处理", "检测到同名文件时的处理策略。")
        dup_row = QHBoxLayout()
        self._dup_radios: dict[str, RadioButton] = {}
        for text, key in [("跳过", "skip"), ("覆盖", "overwrite"), ("重命名", "rename")]:
            rb = RadioButton(text)
            self._dup_radios[key] = rb
            dup_row.addWidget(rb)
        dup_row.addStretch()
        self._dup_radios["skip"].setChecked(True)
        dup.body.addLayout(dup_row)
        grid.addWidget(dup, 0, 1)

        # 文件命名规则
        fn = SurfaceCard("文件命名规则")
        fn.body.addWidget(StrongBodyLabel("命名模板"))
        self.filename_edit = LineEdit()
        self.filename_edit.setPlaceholderText("{tag}/{date}/{index}_{id}.{ext}")
        self.filename_edit.setText("{tag}/{date}/{index}_{id}.{ext}")
        fn.body.addWidget(self.filename_edit)
        preserve_row = QHBoxLayout()
        preserve_text = QVBoxLayout()
        preserve_text.addWidget(StrongBodyLabel("优先保留原文件名"))
        preserve_text.addWidget(_muted("媒体包含原始文件名时直接使用；Telegram 照片无原名时使用命名模板。"))
        preserve_row.addLayout(preserve_text, 1)
        self.preserve_original_sw = SwitchButton()
        self.preserve_original_sw.setChecked(True)
        preserve_row.addWidget(self.preserve_original_sw)
        fn.body.addLayout(preserve_row)
        preview_row = QHBoxLayout()
        self._filename_preview_lbl = _muted("预览：旅行/20260610_190654_5678.jpg")
        preview_row.addWidget(self._filename_preview_lbl)
        preview_btn = PushButton("预览", icon=FIF.VIEW)
        # ✨ 取消写死的 70 宽度，改为最小宽度 90（或者 100），高度统一为 36
        preview_btn.setMinimumSize(90, 36)
        preview_btn.clicked.connect(self._preview_filename)
        preview_row.addWidget(preview_btn)
        fn.body.addLayout(preview_row)
        grid.addWidget(fn, 1, 0)

        # 完成后自动打开
        auto_open = SurfaceCard("下载完成后自动打开目录", "任务完成后自动打开保存目录。")
        ao_row = QHBoxLayout()
        self.auto_open_sw = SwitchButton()
        self.auto_open_sw.setChecked(True)
        ao_row.addWidget(self.auto_open_sw)
        ao_row.addStretch()
        auto_open.body.addLayout(ao_row)
        grid.addWidget(auto_open, 1, 1)

        layout.addLayout(grid)
        layout.addStretch()
        return w

    def _build_session(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        _set_margins(layout, (0, 12, 0, 0), 14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 2)
        grid.setColumnStretch(2, 1)

        # API 凭据
        api_card = SurfaceCard("API 凭据", "API 凭据仅用于连接 Telegram，并保存在本机。")
        self._session_loaded_badge = QLabel(" 未加载 ")
        # ✨ 新增：强制对齐和最小尺寸，防止文字被切割
        self._session_loaded_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._session_loaded_badge.setMinimumSize(64, 26)

        self._session_loaded_badge.setStyleSheet(
            "background:#e53935;color:white;border-radius:13px;font-size:12px;font-weight:bold;"
        )
        if tr := api_card.title_row():
            tr.addWidget(self._session_loaded_badge)
        self._session_status_label = BodyLabel("当前会话可正常使用。")
        api_card.body.addWidget(self._session_status_label)

        api_card.body.addWidget(StrongBodyLabel("API ID"))
        self.api_id_edit = LineEdit()
        self.api_id_edit.setPlaceholderText("API ID（从 my.telegram.org 获取）")
        api_card.body.addWidget(self.api_id_edit)

        api_card.body.addWidget(StrongBodyLabel("API Hash"))
        self.api_hash_edit = PasswordLineEdit()
        self.api_hash_edit.setPlaceholderText("API Hash")
        api_card.body.addWidget(self.api_hash_edit)

        api_card.body.addWidget(StrongBodyLabel("本地会话名称"))
        self.session_edit = LineEdit()
        self.session_edit.setPlaceholderText("default")
        api_card.body.addWidget(self.session_edit)

        api_card.body.addWidget(StrongBodyLabel("会话存储位置"))
        sess_path_row = QHBoxLayout()
        self.session_path_edit = LineEdit()
        sess_path_row.addWidget(self.session_path_edit, 1)
        browse_s = PushButton("浏览", icon=FIF.FOLDER)
        browse_s.clicked.connect(self._choose_session_dir)
        sess_path_row.addWidget(browse_s)
        api_card.body.addLayout(sess_path_row)

        enc_row = QHBoxLayout()
        enc_row.addWidget(StrongBodyLabel("本地加密存储"))
        enc_row.addStretch()
        self.encrypt_sw = SwitchButton()
        self.encrypt_sw.setChecked(True)
        enc_row.addWidget(self.encrypt_sw)
        api_card.body.addLayout(enc_row)
        api_card.body.addWidget(_muted("使用系统 DPAPI 加密存储会话文件。"))

        ops_row = QHBoxLayout()

        logout_btn = PushButton("登出当前账号", icon=FIF.POWER_BUTTON)
        logout_btn.clicked.connect(self.logout_requested)

        cache_btn = PushButton("清理缓存", icon=FIF.DELETE)
        cache_btn.clicked.connect(self.cache_clear_requested)

        # ✨ 1. 统一将两个按钮的尺寸设置为相同的最小宽高（宽 140，高 36）
        # ✨ 2. 删除了原有的 setStyleSheet("color:#e53935;")，恢复原生的高级质感与交互反馈
        for button in (logout_btn, cache_btn):
            button.setMinimumSize(140, 36)

        ops_row.addWidget(logout_btn)
        ops_row.addWidget(cache_btn)
        ops_row.addStretch()
        api_card.body.addLayout(ops_row)
        grid.addWidget(api_card, 0, 0, 1, 2)

        guide_card = SurfaceCard(
            "如何申请 Telegram API",
            "二维码和手机号登录都属于第三方客户端登录，因此都需要 API ID 与 API Hash。",
        )
        for step in [
            "1. 打开 my.telegram.org，使用 Telegram 手机号登录。",
            "2. 输入 Telegram 客户端收到的验证码。",
            "3. 进入 API development tools。",
            "4. 填写 App title 与 Short name，提交创建应用。",
            "5. 将 App api_id 和 App api_hash 填到左侧并保存。",
        ]:
            guide_card.body.addWidget(_muted(step))
        guide_card.body.addWidget(_divider())
        guide_card.body.addWidget(_muted("API Hash 相当于应用密钥，请勿发送给他人。"))
        api_link = HyperlinkButton(
            "https://my.telegram.org/apps",
            "打开 my.telegram.org",
            icon=FIF.LINK,
        )
        api_link.setMinimumHeight(36)
        guide_card.body.addWidget(api_link)
        guide_card.body.addStretch()
        grid.addWidget(guide_card, 0, 2)

        layout.addLayout(grid)
        layout.addStretch()
        return w

    def _build_appearance(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background:transparent;")
        layout = QVBoxLayout(w)
        _set_margins(layout, (0, 12, 0, 0), 14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        # 主题
        theme_card = SurfaceCard("主题模式")
        theme_row = QHBoxLayout()
        self._theme_radios: dict[str, RadioButton] = {}
        for text, key in [("跟随系统", "auto"), ("浅色", "light"), ("深色", "dark")]:
            rb = RadioButton(text)
            self._theme_radios[key] = rb
            theme_row.addWidget(rb)
        theme_row.addStretch()
        self._theme_radios["auto"].setChecked(True)
        theme_card.body.addLayout(theme_row)
        grid.addWidget(theme_card, 0, 0)

        # 动画与圆角
        anim_card = SurfaceCard("界面效果")
        for label, desc, attr in [
            ("启用动画效果", "提供更流畅的界面动效体验。", "anim_sw"),
            ("圆角样式", "使用圆角卡片与控件样式（推荐）。", "round_sw"),
        ]:
            row = QHBoxLayout()
            row.setSpacing(12)
            text_v = QVBoxLayout()
            text_v.setSpacing(2)
            text_v.addWidget(StrongBodyLabel(label))
            text_v.addWidget(_muted(desc))
            row.addLayout(text_v, 1)
            sw = SwitchButton()
            sw.setChecked(True)
            setattr(self, attr, sw)
            row.addWidget(sw)
            anim_card.body.addLayout(row)
            anim_card.body.addWidget(_divider())
        grid.addWidget(anim_card, 0, 1)

        # 语言
        lang_card = SurfaceCard("语言（Language）")
        self.lang_combo = ComboBox()
        self.lang_combo.addItem("简体中文", userData="zh_CN")
        self.lang_combo.addItem("English", userData="en_US")
        lang_card.body.addWidget(self.lang_combo)
        grid.addWidget(lang_card, 1, 0)

        # 预览图
        preview_card = SurfaceCard()
        preview_card.body.addWidget(
            _img_label("download-illustration.png", 260, 160),
            alignment=Qt.AlignmentFlag.AlignCenter
        )
        grid.addWidget(preview_card, 1, 1)

        layout.addLayout(grid)
        layout.addStretch()
        return w

    def _choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择默认保存目录", self.path_edit.text())
        if d:
            self.path_edit.setText(d)

    def _choose_session_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择会话存储位置")
        if d:
            self.session_path_edit.setText(d)

    def _on_save(self):
        self.save_requested.emit(self._collect())

    def _preview_filename(self):
        template = self.filename_edit.text().strip()
        try:
            result = template.format(
                tag="旅行",
                date="20260610_190654",
                post_id="1024",
                comment_id="5678",
                index="5678",
                id="5678",
                ext="jpg",
            )
            self._filename_preview_lbl.setText(f"预览：{result}")
        except (KeyError, ValueError, IndexError):
            self._filename_preview_lbl.setText("预览：格式错误，请检查模板变量")

    def _restore_defaults(self):
        self.path_edit.setText("")
        self.max_posts.setValue(200)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData("channel_tag")))
        self.preserve_original_sw.setChecked(True)
        self.concurrency_spin.setValue(6)
        self.interval_spin.setValue(1.0)
        self.fn_len_spin.setValue(100)
        self.tag_empty_combo.setCurrentIndex(
            max(0, self.tag_empty_combo.findData("uncategorized"))
        )
        self.restore_cb.setChecked(True)
        self.last_mode_cb.setChecked(True)
        self.auto_tag_cb.setChecked(True)

    def _collect(self) -> dict:
        mode = self.mode_combo.currentData() or "channel_tag"
        dup = next((k for k, rb in self._dup_radios.items() if rb.isChecked()), "skip")
        theme = next((k for k, rb in self._theme_radios.items() if rb.isChecked()), "auto")
        return {
            "save_root": self.path_edit.text().strip(),
            "save_mode": mode,
            "max_posts": self.max_posts.value(),
            "concurrency": self.concurrency_spin.value(),
            "request_interval": float(self.interval_spin.value()),
            "filename_limit": self.fn_len_spin.value(),
            "empty_tag_action": self.tag_empty_combo.currentData() or "uncategorized",
            "restore_on_launch": self.restore_cb.isChecked(),
            "use_last_mode": self.last_mode_cb.isChecked(),
            "auto_fill_tag": self.auto_tag_cb.isChecked(),
            "skip_duplicates": dup,
            "filename_template": self.filename_edit.text().strip(),
            "preserve_original_name": self.preserve_original_sw.isChecked(),
            "api_id": self.api_id_edit.text().strip(),
            "api_hash": self.api_hash_edit.text().strip(),
            "session_name": self.session_edit.text().strip() or "default",
            "session_path": self.session_path_edit.text().strip(),
            "theme_mode": theme,
            "lang": self.lang_combo.currentData(),
            "open_after_download": self.auto_open_sw.isChecked(),
            "enable_animations": self.anim_sw.isChecked(),
            "enable_rounded_corners": self.round_sw.isChecked(),
            "use_dpapi_encryption": self.encrypt_sw.isChecked(),
        }

    # ── Setters
    def set_defaults(self, d: dict):
        if "save_root" in d:
            self.path_edit.setText(d["save_root"])
            self._summary_path_lbl.setText(f"保存目录\n{d['save_root']}")
        if "save_mode" in d:
            idx = self.mode_combo.findData(d["save_mode"])
            if idx >= 0:
                self.mode_combo.setCurrentIndex(idx)
            self._summary_mode_lbl.setText(f"保存模式\n{self.mode_combo.currentText()}")
        if "api_id" in d:
            self.api_id_edit.setText(d["api_id"])
        if "api_hash" in d:
            self.api_hash_edit.setText(d["api_hash"])
        if "session_name" in d:
            self.session_edit.setText(d["session_name"])
        if "session_path" in d:
            self.session_path_edit.setText(str(d["session_path"]))
        if "theme_mode" in d:
            rb = self._theme_radios.get(d["theme_mode"])
            if rb:
                rb.setChecked(True)
        if "max_posts" in d:
            self.max_posts.setValue(int(d["max_posts"]))
        if "concurrency" in d:
            self.concurrency_spin.setValue(int(d["concurrency"]))
        if "request_interval" in d:
            self.interval_spin.setValue(float(d["request_interval"]))
        if "filename_limit" in d:
            self.fn_len_spin.setValue(int(d["filename_limit"]))
        if "empty_tag_action" in d:
            idx = self.tag_empty_combo.findData(d["empty_tag_action"])
            if idx >= 0:
                self.tag_empty_combo.setCurrentIndex(idx)
        if "restore_on_launch" in d:
            self.restore_cb.setChecked(bool(d["restore_on_launch"]))
        if "use_last_mode" in d:
            self.last_mode_cb.setChecked(bool(d["use_last_mode"]))
        if "auto_fill_tag" in d:
            self.auto_tag_cb.setChecked(bool(d["auto_fill_tag"]))
        if "skip_duplicates" in d:
            key = d["skip_duplicates"]
            if isinstance(key, bool):
                key = "skip" if key else "rename"
            rb = self._dup_radios.get(key)
            if rb:
                rb.setChecked(True)
            labels = {"skip": "跳过", "overwrite": "覆盖", "rename": "自动重命名"}
            self._summary_dup_lbl.setText(f"重复文件处理\n{labels.get(key, key)}")
        if "filename_template" in d:
            self.filename_edit.setText(d["filename_template"])
            self._summary_fn_lbl.setText(f"文件命名规则\n{d['filename_template']}")
        if "preserve_original_name" in d:
            self.preserve_original_sw.setChecked(bool(d["preserve_original_name"]))
            if d["preserve_original_name"]:
                self._summary_fn_lbl.setText("文件命名规则\n优先保留原名")
        if "open_after_download" in d:
            self.auto_open_sw.setChecked(bool(d["open_after_download"]))
        if "lang" in d:
            idx = self.lang_combo.findData(d["lang"])
            if idx >= 0:
                self.lang_combo.setCurrentIndex(idx)
        if "enable_animations" in d:
            self.anim_sw.setChecked(bool(d["enable_animations"]))
        if "enable_rounded_corners" in d:
            self.round_sw.setChecked(bool(d["enable_rounded_corners"]))
        if "use_dpapi_encryption" in d:
            self.encrypt_sw.setChecked(bool(d["use_dpapi_encryption"]))

    def set_session_status(self, loaded: bool, message: str = ""):
        if loaded:
            self._session_loaded_badge.setText("已加载")
            self._session_loaded_badge.setStyleSheet(
                f"background:{C_GREEN};color:white;border-radius:13px;font-size:12px;font-weight:bold;")
        else:
            self._session_loaded_badge.setText("未加载")
            self._session_loaded_badge.setStyleSheet(
                "background:#e53935;color:white;border-radius:13px;font-size:12px;font-weight:bold;")

        if message:
            self._session_status_label.setText(message)


# ──────────────────────────────────────────────────────────────
#  关于页
# ──────────────────────────────────────────────────────────────
class AboutPage(ScrollPage):
    def __init__(self, parent=None):
        super().__init__("aboutPage", parent)
        card = SurfaceCard()
        row = QHBoxLayout()
        row.addWidget(_img_label("download-illustration.png", 380, 300))
        text = QVBoxLayout()
        text.setSpacing(10)
        text.addWidget(TitleLabel("Telegram 评论区图片下载器"))
        text.addWidget(SubtitleLabel("安全 · 稳定 · 高效"))
        text.addWidget(_muted(
            "使用 Telethon、PySide6 与 QFluentWidgets 构建。\n"
            "用于按 Tag 搜索频道帖子，并整理评论区中的图片。"
        ))
        text.addWidget(BodyLabel("版本 v2.3.0"))
        text.addStretch()
        row.addLayout(text, 1)
        card.body.addLayout(row)
        self.root.addWidget(card)
        self.root.addStretch()


# ──────────────────────────────────────────────────────────────
#  主窗口（纯 UI 壳，不含业务逻辑）
# ──────────────────────────────────────────────────────────────
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
    task_pause_all_requested = Signal()
    task_clear_queue_requested = Signal()
    # 登录
    send_code_requested = Signal(str)
    login_requested = Signal(str, str, str)
    qr_requested = Signal()
    logout_requested = Signal()
    # 设置
    settings_save_requested = Signal(dict)
    settings_logout_requested = Signal()
    settings_cache_clear_requested = Signal()
    # 通用
    open_folder_requested = Signal()
    history_clear_requested = Signal()
    trend_period_changed = Signal(str)
    # 窗口关闭
    window_closing = Signal()

    def __init__(self):
        super().__init__()

        # 子页面
        self.home_page = HomePage()
        self.task_page = TaskPage()
        self.login_page = LoginPage()
        self.history_page = HistoryPage()
        self.settings_page = SettingsPage()
        self.about_page = AboutPage()
        self._preview_dialog: SearchPreviewDialog | None = None

        # 注册导航
        self.addSubInterface(self.home_page,     FIF.HOME,     "首页")
        self.addSubInterface(self.task_page,     FIF.DOWNLOAD, "下载任务")
        self.addSubInterface(self.login_page,    FIF.PEOPLE,   "登录中心")
        self.addSubInterface(self.history_page,  FIF.HISTORY,  "下载历史")
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
            text="v2.3.0",
            onClick=lambda: self.switchTo(self.about_page),
            position=NavigationItemPosition.BOTTOM
        )

        # 窗口属性
        icon_path = _UI_DIR / "telegram-app-icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setWindowTitle("Telegram 评论区图片下载器")
        self.resize(1440, 900)
        self.setMinimumSize(1200, 760)
        self.navigationInterface.setExpandWidth(280)
        self.navigationInterface.setMinimumExpandWidth(1080)
        self.navigationInterface.expand(useAni=False)

        self._wire_internal()

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
        self.task_page.pause_task_requested.connect(self.task_pause_requested)
        self.task_page.delete_task_requested.connect(self.task_delete_requested)
        self.task_page.open_folder_requested.connect(self.open_folder_requested)
        self.task_page.switch_account_requested.connect(lambda: self.switchTo(self.login_page))
        self.task_page.settings_requested.connect(lambda: self.switchTo(self.settings_page))
        self.task_page.preview_requested.connect(self.task_preview_requested)
        self.task_page.pause_all_requested.connect(self.task_pause_all_requested)
        self.task_page.clear_queue_requested.connect(self.task_clear_queue_requested)
        # 登录页
        self.login_page.send_code_requested.connect(self.send_code_requested)
        self.login_page.login_requested.connect(self.login_requested)
        self.login_page.qr_requested.connect(self.qr_requested)
        self.login_page.logout_requested.connect(self.logout_requested)
        # 历史页
        self.history_page.clear_requested.connect(self.history_clear_requested)
        self.history_page.open_folder_requested.connect(self.open_folder_requested)
        # 设置页
        self.settings_page.save_requested.connect(self.settings_save_requested)
        self.settings_page.logout_requested.connect(self.settings_logout_requested)
        self.settings_page.cache_clear_requested.connect(self.settings_cache_clear_requested)

    # ──────────────────────────────────────────────────────────
    #  公开 Setter API（Controller 调用这些方法推数据入 UI）
    # ──────────────────────────────────────────────────────────

    def set_account(self, name: str = "", phone: str = "", dc: str = ""):
        """更新所有页面的账号状态"""
        self.home_page.set_account(name, phone)
        self.task_page.set_account(name, phone, dc)
        self.login_page.set_account(name, phone)

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

    def set_task_defaults(self, save_root: str, save_mode_label: str, save_mode_key: str = ""):
        self.task_page.set_defaults(save_root, save_mode_label, save_mode_key)

    def set_task_rule_summary(
        self,
        filename_template: str,
        preserve_original_name: bool,
        duplicate_mode: str,
        open_after_download: bool,
    ):
        self.task_page.set_rule_summary(
            filename_template,
            preserve_original_name,
            duplicate_mode,
            open_after_download,
        )

    def set_task_busy(self, busy: bool):
        self.task_page.set_busy(busy)

    def set_task_detail(self, text: str):
        self.task_page.set_detail(text)

    def show_search_preview_loading(self, channel: str, tag: str):
        if self._preview_dialog:
            self._preview_dialog.reject()
        self._preview_dialog = SearchPreviewDialog(channel, tag, self)
        self._preview_dialog.cancel_requested.connect(self.task_preview_cancel_requested)
        self._preview_dialog.show()
        self.task_page.set_preview_busy(True)

    def set_search_preview_progress(self, message: str):
        if self._preview_dialog:
            self._preview_dialog.set_progress(message)

    def set_search_preview_results(self, rows: list[dict]):
        self.task_page.set_preview_busy(False)
        if self._preview_dialog:
            self._preview_dialog.set_results(rows)

    def set_search_preview_error(self, message: str):
        self.task_page.set_preview_busy(False)
        if self._preview_dialog:
            self._preview_dialog.set_error(message)

    def set_task_queue(self, tasks: list[TaskRow]):
        self.task_page.set_queue_tasks(tasks)

    def show_qr(self, url: str):
        self.login_page.show_qr(url)

    def set_qr_message(self, message: str, allow_auto_retry: bool = False):
        self.login_page.set_qr_message(message, allow_auto_retry)

    def set_login_phone(self, phone: str):
        self.login_page.set_phone(phone)

    def set_history(self, rows: list[HistoryRow]):
        self.history_page.set_rows(rows)

    def set_settings_defaults(self, d: dict):
        self.settings_page.set_defaults(d)

    def set_session_status(self, loaded: bool, message: str = ""):
        self.settings_page.set_session_status(loaded, message)

    def show_success(self, message: str):
        InfoBar.success(
            title="操作成功", content=message, parent=self,
            position=InfoBarPosition.TOP_RIGHT, duration=3500,
        )

    def show_error(self, message: str):
        InfoBar.error(
            title="需要处理一下", content=message, parent=self,
            position=InfoBarPosition.TOP_RIGHT, duration=5500,
        )

    def show_info(self, message: str):
        InfoBar.info(
            title="提示", content=message, parent=self,
            position=InfoBarPosition.TOP_RIGHT, duration=3000,
        )

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
            setTheme(Theme.LIGHT)
        else:
            current.get("dark") and current["dark"].setChecked(True)
            setTheme(Theme.DARK)

    def closeEvent(self, event: QCloseEvent):
        self.window_closing.emit()
        super().closeEvent(event)
