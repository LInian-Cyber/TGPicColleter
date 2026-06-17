from __future__ import annotations

from .. import __version__
from .common import *
from .common import _UI_DIR, _asset, _divider, _img_label, _muted, _set_margins

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
        text.addWidget(BodyLabel(f"版本 v{__version__}"))
        text.addWidget(_muted("GNU GPL-3.0 开源软件 · 不提供任何担保"))
        text.addStretch()
        row.addLayout(text, 1)
        card.body.addLayout(row)
        self.root.addWidget(card)
        self.root.addStretch()


# ──────────────────────────────────────────────────────────────
#  主窗口（纯 UI 壳，不含业务逻辑）
# ──────────────────────────────────────────────────────────────
