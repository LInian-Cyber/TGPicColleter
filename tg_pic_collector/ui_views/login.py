from __future__ import annotations

from .common import *
from .common import _UI_DIR, _asset, _divider, _img_label, _muted, _set_margins, _set_round_avatar

class LoginPage(ScrollPage):
    send_code_requested = Signal(str)          # phone
    login_requested = Signal(str, str, str)    # phone, code, password
    qr_requested = Signal()
    logout_requested = Signal()
    account_switch_requested = Signal(str)
    account_add_requested = Signal()

    def __init__(self, parent=None):
        super().__init__("loginPage", parent)
        self._qr_requested_once = False
        self._is_logged_in = False
        self._theme_icon_labels: list[tuple[QLabel, FIF, int]] = []
        self._page_header("登录中心", "登录您的 Telegram 账号以使用全部功能",
                          illus="login-illustration.png", illus_w=200, illus_h=90)

        # 安全提示横幅
        self._banner = SurfaceCard()
        banner_row = QHBoxLayout()
        ico = QLabel()
        set_theme_icon(ico, FIF.ACCEPT, 18)
        self._theme_icon_labels.append((ico, FIF.ACCEPT, 18))
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

        self._accounts_card = self._build_account_sessions_card()
        self.root.addWidget(self._accounts_card)

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
            set_theme_icon(ico_w, icon, 20)
            self._theme_icon_labels.append((ico_w, icon, 20))
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
            set_theme_icon(ico_lbl, ico, 22)
            self._theme_icon_labels.append((ico_lbl, ico, 22))
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

    def _build_account_sessions_card(self) -> SurfaceCard:
        card = SurfaceCard("已保存账号")
        if row := card.title_row():
            add_btn = TransparentPushButton("添加新账号", icon=FIF.ADD)
            add_btn.setMinimumHeight(32)
            add_btn.clicked.connect(self.account_add_requested)
            row.addWidget(add_btn)
        self._accounts_list = QVBoxLayout()
        self._accounts_list.setSpacing(8)
        card.body.addLayout(self._accounts_list)
        return card

    def set_account_sessions(self, rows: list[dict], current_key: str = ""):
        while self._accounts_list.count():
            item = self._accounts_list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not rows:
            self._accounts_list.addWidget(
                _muted("暂无保存账号。登录成功后会自动保存为可切换账号。")
            )
            return

        for account in rows:
            key = str(account.get("key", "") or "")
            name = str(account.get("name", "") or "").strip() or "Telegram 用户"
            phone = str(account.get("phone", "") or "").strip()
            session_name = str(account.get("session_name", "") or "default")
            is_current = bool(current_key and key == current_key)

            row_card = CardWidget()
            row_card.setStyleSheet("CardWidget{background:transparent;}")
            row = QHBoxLayout(row_card)
            row.setContentsMargins(10, 8, 10, 8)
            row.setSpacing(12)

            avatar = QLabel("●")
            avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
            avatar.setFixedSize(40, 40)
            avatar.setObjectName("savedAccountAvatar")
            _set_round_avatar(avatar, account.get("avatar", b""), 40)
            row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignVCenter)

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            name_row = QHBoxLayout()
            name_row.setSpacing(8)
            name_row.addWidget(BodyLabel(name))
            if is_current:
                badge = CaptionLabel("当前")
                badge.setStyleSheet(
                    f"background:#eaf7f0;color:{C_GREEN};border-radius:9px;"
                    "padding:2px 8px;font-weight:600;"
                )
                name_row.addWidget(badge)
            name_row.addStretch()
            text_col.addLayout(name_row)
            subtitle = phone or f"本地会话：{session_name}"
            text_col.addWidget(_muted(subtitle, wrap=False))
            row.addLayout(text_col, 1)

            switch_btn = PushButton("当前账号" if is_current else "切换")
            switch_btn.setMinimumSize(96, 32)
            switch_btn.setEnabled(not is_current)
            switch_btn.clicked.connect(
                lambda checked=False, session_key=key: self.account_switch_requested.emit(session_key)
            )
            row.addWidget(switch_btn, 0, Qt.AlignmentFlag.AlignVCenter)

            self._accounts_list.addWidget(row_card)
    
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
            self.phone_edit.clear()
            self.code_edit.clear()
            self.password_edit.clear()
            return
        for index in range(self._country_combo.count()):
            code = self._country_combo.itemData(index)
            if phone.startswith(code):
                self._country_combo.setCurrentIndex(index)
                self.phone_edit.setText(phone[len(code):])
                return
        self.phone_edit.setText(phone)

    def refresh_theme(self):
        for label, icon, size in self._theme_icon_labels:
            set_theme_icon(label, icon, size)

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
