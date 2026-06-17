from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme

from .config import AppConfig
from .logger import get_logger
from .models import (
    PreviewRequest,
    SAVE_MODE_LABELS,
    ScanRequest,
    TelegramCredentials,
    normalize_channel_reference,
)
from .telegram_worker import TelegramWorker
from .ui import HistoryRow, MainWindow, TaskRow


class AppController(QObject):
    """Connects the pure UI layer to configuration and Telegram services."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.logger = get_logger()
        self.window = MainWindow()
        self.worker: TelegramWorker | None = None
        self.authorized = False
        self.current_request: ScanRequest | None = None
        self.current_open_after = False
        self.cancelled = False
        self.queue: list[TaskRow] = []
        self._loaded_dialogs: list[dict] = []
        self._discard_current_task = False
        self._shutting_down = False
        self._shutdown_complete = False

        self._populate_ui()
        self._connect_ui()
        self._refresh_local_data()
        self._ensure_worker(quiet=True)

    def _populate_ui(self) -> None:
        task_modes = [("default", "沿用默认设置"), *SAVE_MODE_LABELS.items()]
        for key, label in task_modes:
            self.window.task_page.add_mode_item(label, key)
        self.window.set_task_defaults(
            self.config.save_root,
            SAVE_MODE_LABELS.get(self.config.save_mode, self.config.save_mode),
            self.config.save_mode if self.config.use_last_mode else "default",
        )

        # 加载频道历史
        channel_history = self.config.get_channel_history_with_avatars()
        self.window.task_page.add_channel_history(channel_history)

        if self.config.channel:
            self.window.task_page.channel_combo.setText(self.config.channel)
        if self.config.restore_on_launch:
            self.window.task_page.tag_edit.setText(self.config.tag)
            if self.config.last_task_state:
                self.window.task_page.restore_task_options(
                    self.config.last_task_state.get("params", {})
                )
        self.window.task_page.set_advanced_rules(self.config.advanced_rules or [])
        if self.config.auto_fill_tag and not self.window.task_page.tag_edit.text() and self.config.history:
            recent_tag = str(self.config.history[0].get("tag", "")).strip()
            if recent_tag:
                self.window.task_page.tag_edit.setText(recent_tag.lstrip("#"))
        self.window.set_task_rule_summary(
            self.config.filename_template,
            self.config.preserve_original_name,
            self.config.duplicate_mode,
            self.config.open_after_download,
            self.config.concurrency,
            self.config.file_download_interval,
            self.config.filename_limit,
        )
        self.window.set_summary(
            self.config.save_root,
            SAVE_MODE_LABELS.get(self.config.save_mode, self.config.save_mode),
        )
        self.window.set_settings_defaults(self._settings_dict())
        self.window.set_system_notifications_enabled(self.config.enable_system_notifications)
        self.window.set_session_status(False, "等待连接 Telegram")
        self.window.set_login_phone(self.config.phone)
        self.window.apply_language(self.config.lang)

    def _settings_dict(self) -> dict:
        return {
            "save_root": self.config.save_root,
            "save_mode": self.config.save_mode,
            "max_posts": self.config.max_posts,
            "preview_max_results": self.config.preview_max_results,
            "concurrency": self.config.concurrency,
            "file_download_interval": self.config.file_download_interval,
            "filename_limit": self.config.filename_limit,
            "empty_tag_action": self.config.empty_tag_action,
            "restore_on_launch": self.config.restore_on_launch,
            "use_last_mode": self.config.use_last_mode,
            "auto_fill_tag": self.config.auto_fill_tag,
            "skip_duplicates": self.config.duplicate_mode,
            "filename_template": self.config.filename_template,
            "preserve_original_name": self.config.preserve_original_name,
            "api_id": self.config.api_id,
            "api_hash": self.config.api_hash,
            "session_name": self.config.session_name,
            "session_path": self.config.session_path.parent,
            "theme_mode": self.config.theme_mode,
            "lang": self.config.lang,
            "open_after_download": self.config.open_after_download,
            "enable_animations": self.config.enable_animations,
            "enable_rounded_corners": self.config.enable_rounded_corners,
            "enable_system_notifications": self.config.enable_system_notifications,
            "use_dpapi_encryption": self.config.use_dpapi_encryption,
        }

    def _connect_ui(self) -> None:
        w = self.window
        w.task_start_requested.connect(self.start_task)
        w.task_cancel_requested.connect(self.cancel_task)
        w.task_pause_requested.connect(self.pause_task)
        w.task_delete_requested.connect(self.delete_task)
        w.task_preview_requested.connect(self.start_preview)
        w.task_preview_cancel_requested.connect(self.cancel_preview)
        w.task_pause_all_requested.connect(self.pause_all)
        w.task_clear_queue_requested.connect(self.clear_queue)
        w.tray_pause_requested.connect(self.pause_from_tray)
        w.tray_resume_requested.connect(self.resume_from_tray)
        w.tray_stop_requested.connect(self.cancel_task)
        w.tray_quit_requested.connect(self.shutdown)
        w.task_page.save_template_requested.connect(self.save_template)
        w.task_page.advanced_rules_changed.connect(self.save_advanced_rules)
        w.task_page.resume_task_requested.connect(self.resume_last_task)
        w.home_page.resume_task_requested.connect(self.resume_last_task)
        w.send_code_requested.connect(self.send_code)
        w.login_requested.connect(self.sign_in)
        w.qr_requested.connect(self.start_qr_login)
        w.logout_requested.connect(self.logout)
        w.settings_save_requested.connect(self.save_settings)
        w.settings_logout_requested.connect(self.logout)
        w.settings_cache_clear_requested.connect(self.clear_cache)
        w.open_folder_requested.connect(self.open_folder)
        w.open_log_requested.connect(self.open_log)
        w.open_log_folder_requested.connect(self.open_log_folder)
        w.history_clear_requested.connect(self.clear_history)
        w.history_delete_requested.connect(self.delete_history)
        w.trend_period_changed.connect(self.refresh_trend)
        w.window_closing.connect(self.shutdown)
        w.task_page.open_current_folder_requested.connect(self.open_specific_folder)

    def open_specific_folder(self, path_str: str) -> None:
        path = Path(path_str).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(path.as_uri())

    def clear_queue(self) -> None:
        if self.worker and self.worker.isRunning():
            self._discard_current_task = True
        self.cancel_task()  # 先停止当前任务
        self.queue.clear()
        self.window.set_task_queue(self.queue)
        self.window.set_tray_task_state()
        self.window.show_success("任务队列已清空")

    def pause_all(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.pause_scan()
        for task in self.queue:
            if task.status not in {"已完成", "已取消"}:
                task.status = "已暂停"
        self.window.set_task_queue(self.queue)
        if self.queue and self.queue[0].status == "已暂停":
            self.window.set_tray_task_state(can_resume=True, can_stop=True)

    def clear_cache(self) -> None:
        session_dir = self.config.session_path.parent
        active_journal = Path(f"{self.config.session_path}.session-journal")
        count = 0
        if session_dir.exists():
            candidates = [*session_dir.glob("*.journal"), *session_dir.glob("*.session-journal")]
            for path in candidates:
                if self.worker and self.worker.isRunning() and path == active_journal:
                    continue
                try:
                    path.unlink()
                    count += 1
                except OSError:
                    continue
        self.window.show_success(f"已清理 {count} 个缓存文件")

    def _credentials(self) -> TelegramCredentials:
        return TelegramCredentials(
            api_id=int(self.config.api_id),
            api_hash=self.config.api_hash.strip(),
            phone=self.config.phone.strip(),
            session_path=self.config.session_path,
        )

    def _ensure_worker(self, quiet: bool = False) -> bool:
        if self.worker and self.worker.isRunning():
            return True
        try:
            credentials = self._credentials()
            if not credentials.api_hash:
                raise ValueError
        except ValueError:
            self.window.set_session_status(False, "请先在设置中填写 API ID 与 API Hash")
            self.window.set_qr_message(
                "暂时无法生成二维码\n请先在“设置 → 会话与安全”中填写\nAPI ID 与 API Hash",
                allow_auto_retry=True,
            )
            if not quiet:
                self.window.show_error("请先在设置中填写有效的 API ID 与 API Hash")
            return False

        self.worker = TelegramWorker(credentials, use_encryption=self.config.use_dpapi_encryption)
        self.worker.ready.connect(self._on_worker_ready)
        self.worker.status_changed.connect(self.window.set_task_detail)
        self.worker.authorized.connect(self._on_authorized)
        self.worker.user_profile_updated.connect(self._on_user_profile_updated)
        self.worker.channel_info_fetched.connect(self._on_channel_info_fetched)
        self.worker.dialogs_loaded.connect(self._on_dialogs_loaded)
        self.worker.code_sent.connect(
            lambda phone: self.window.show_success(f"验证码已发送至 {phone}")
        )
        self.worker.qr_ready.connect(self.window.show_qr)
        self.worker.password_required.connect(self._on_password_required)
        self.worker.auth_failed.connect(self.window.show_error)
        self.worker.connection_failed.connect(self._on_worker_error)
        self.worker.logged_out.connect(self._on_logged_out)
        self.worker.scan_started.connect(self._on_scan_started)
        self.worker.scan_plan_ready.connect(self._on_scan_plan_ready)
        self.worker.scan_discovery_finished.connect(self._on_scan_discovery_finished)
        self.worker.scan_progress.connect(self._on_scan_progress)
        self.worker.post_status_changed.connect(self._on_post_status_changed)
        self.worker.scan_finished.connect(self._on_scan_finished)
        self.worker.scan_failed.connect(self._on_scan_failed)
        self.worker.preview_progress.connect(self.window.set_search_preview_progress)
        self.worker.preview_finished.connect(self._on_preview_finished)
        self.worker.preview_failed.connect(self._on_preview_failed)
        self.worker.start()
        return True

    def _restart_worker(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(4000)
        self.worker = None
        self.authorized = False
        self.window.set_account()
        self._ensure_worker(quiet=True)

    def _on_worker_ready(self, authorized: bool) -> None:
        self.window.set_session_status(authorized, "本地 Telethon Session 已加载" if authorized else "未登录")
        if not authorized:
            self.window.set_account()
            self.window.set_qr_message("当前未登录，可刷新二维码或使用手机号登录")

    def _on_worker_error(self, message: str) -> None:
        self.authorized = False
        self.window.set_session_status(False, f"Telegram 连接失败：{message}")
        self.window.set_task_detail(f"Telegram 连接失败：{message}")
        self.window.set_qr_message(
            f"无法连接 Telegram\n{message}\n\n请检查网络后点击“刷新二维码”",
            allow_auto_retry=True,
        )
        self.window.show_error(f"Telegram 连接失败：{message}")

    def _on_authorized(self, name: str, phone: str) -> None:
        self.authorized = True
        self.config.phone = phone
        self.config.save()
        self.window.set_account(name, phone, "Telethon")
        self.window.set_session_status(True, "当前会话可正常使用")
        self.window.show_success(f"欢迎回来，{name}")

        # 自动加载对话列表
        if self.worker:
            self.worker.load_dialogs()

    def _on_user_profile_updated(self, name: str, phone: str, avatar_bytes: bytes) -> None:
        """处理用户头像更新"""
        self.window.set_user_avatar(avatar_bytes)

    def _on_channel_info_fetched(self, channel_id: str, channel_name: str, avatar_bytes: bytes) -> None:
        """处理频道信息获取"""
        self.config.add_channel_to_history(channel_id, channel_name, avatar_bytes)
        # 刷新下拉列表
        self.window.task_page.add_channel_history(
            self._combined_channel_history(self._loaded_dialogs)
        )

    def _on_dialogs_loaded(self, dialogs: list[dict]) -> None:
        """处理对话列表加载完成"""
        self._loaded_dialogs = dialogs
        self.window.task_page.add_channel_history(self._combined_channel_history(dialogs))

    def _combined_channel_history(self, dialogs: list[dict] | None = None) -> list[dict]:
        """Merge searched channels and loaded dialogs without dropping metadata."""
        merged: list[dict] = []
        seen: set[str] = set()
        for item in [*self.config.get_channel_history_with_avatars(), *(dialogs or [])]:
            channel_id = str(item.get("id", "")).strip()
            if not channel_id or channel_id in seen:
                continue
            seen.add(channel_id)
            if not item.get("link"):
                item = dict(item)
                item["link"] = AppConfig._channel_display_link(channel_id)
            merged.append(item)
        return merged[:40]

    def send_code(self, phone: str) -> None:
        if not phone:
            self.window.show_error("请输入包含国家代码的手机号")
            return
        if self._ensure_worker() and self.worker:
            self.config.phone = phone
            self.config.save()
            self.worker.request_code(phone)

    def sign_in(self, phone: str, code: str, password: str) -> None:
        if not phone or (not code and not password):
            self.window.show_error("请输入手机号和验证码")
            return
        if self._ensure_worker() and self.worker:
            self.worker.sign_in(phone, code, password)

    def start_qr_login(self) -> None:
        if self.authorized:
            self.window.set_qr_message("当前账号已登录，无需扫码")
            return
        if self._ensure_worker(quiet=True) and self.worker:
            self.window.set_qr_message("正在生成二维码…")
            self.worker.start_qr_login()

    def _on_password_required(self) -> None:
        self.window.show_info("此账号已开启两步验证，请输入密码后再次登录")
        self.window.navigate_to_login()

    def logout(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.log_out()
        else:
            self.window.show_info("当前没有已连接的账号")

    def _on_logged_out(self) -> None:
        self.worker = None
        self.authorized = False
        self.window.set_account()
        self.window.set_session_status(False, "已退出当前账号")
        self.window.show_success("已退出当前账号")

    def start_task(self, params: dict) -> None:
        channel = normalize_channel_reference(str(params.get("channel", "")))
        if not channel or not params.get("save_root"):
            self.window.show_error("请填写频道和保存位置")
            return
        if not self.authorized:
            self.window.show_error("请先登录 Telegram")
            self.window.navigate_to_login()
            return
        mode = params.get("save_mode") or self.config.save_mode
        if mode == "default":
            mode = self.config.save_mode
        if mode not in SAVE_MODE_LABELS:
            mode = self.config.save_mode if self.config.save_mode in SAVE_MODE_LABELS else "tag"
        duplicate_mode = "skip" if params.get("skip_duplicates", True) else self.config.duplicate_mode
        if duplicate_mode == "skip" and not params.get("skip_duplicates", True):
            duplicate_mode = "rename"
        request = ScanRequest(
            channel=channel,
            tag=params.get("tag", ""),
            save_root=Path(params["save_root"]).expanduser(),
            save_mode=mode,
            max_posts=self.config.max_posts,
            skip_duplicates=duplicate_mode == "skip",
            duplicate_mode=duplicate_mode,
            preserve_original_name=self.config.preserve_original_name,
            filename_template=self.config.filename_template,
            extract_button_link=bool(params.get("extract_button_link")),
            button_keyword=str(params.get("button_keyword", "")).strip() or "原图",
            only_images=bool(params.get("only_images", True)),
            include_replies=bool(params.get("include_replies", True)),
            concurrency=max(1, int(self.config.concurrency)),
            file_download_interval=max(0.0, float(self.config.file_download_interval)),
            filename_limit=max(20, int(self.config.filename_limit)),
            empty_tag_action=self.config.empty_tag_action,
            custom_extract_json=str(params.get("custom_extract_json", "")).strip(),
            chunk_concurrency=max(1, int(getattr(self.config, "chunk_concurrency", 1))),
        )
        self.config.channel = request.channel
        self.config.tag = request.tag
        # 保存任务状态以便恢复
        self.config.last_task_state = {
            "channel": request.channel,
            "tag": request.tag,
            "params": params,
        }
        self.config.save()
        self.current_request = request
        self.current_open_after = bool(params.get("open_after"))
        self.cancelled = False
        self.queue.insert(
            0,
            TaskRow(request.channel, request.tag or "全部", "下载中", 0, 0, 0),
        )
        self.window.set_task_queue(self.queue)
        self.window.set_task_progress(0, 0, 0)
        assert self.worker is not None
        self.worker.start_scan(request)

    def save_template(self, params: dict) -> None:
        """保存当前任务配置为模板（实际就是更新默认设置）"""
        if params.get("save_root"):
            self.config.save_root = params["save_root"]
        if params.get("save_mode") and params["save_mode"] != "default":
            self.config.save_mode = params["save_mode"]
        state = dict(self.config.last_task_state or {})
        state["channel"] = state.get("channel", self.config.channel)
        state["tag"] = state.get("tag", self.config.tag)
        state["params"] = dict(params)
        self.config.last_task_state = state
        self.config.save()
        self.window.show_success("已保存为默认模板")
        self.window.set_task_defaults(
            self.config.save_root,
            SAVE_MODE_LABELS.get(self.config.save_mode, self.config.save_mode),
            self.config.save_mode,
        )

    def save_advanced_rules(self, rules: list[dict]) -> None:
        self.config.advanced_rules = rules
        self.config.save()

    def resume_last_task(self) -> None:
        """继续上次任务"""
        if not self.config.last_task_state:
            self.window.show_info("暂无可恢复的任务")
            return
        state = self.config.last_task_state
        self.window.navigate_to_task()
        self.window.task_page.restore_last_params(
            state.get("channel", ""),
            state.get("tag", "")
        )
        self.window.task_page.restore_task_options(state.get("params", {}))

    def start_preview(self, params: dict) -> None:
        channel = normalize_channel_reference(str(params.get("channel", "")))
        tag = str(params.get("tag", "")).strip()
        if not channel:
            self.window.show_error("请先填写要搜索的频道、用户名或 ID")
            return
        if not self.authorized:
            self.window.show_error("请先登录 Telegram，再搜索预览")
            self.window.navigate_to_login()
            return
        if not self._ensure_worker() or not self.worker:
            return
        self.config.channel = channel
        self.config.tag = tag
        self.config.save()
        self.window.show_search_preview_loading(channel, tag)
        self.window.set_search_preview_progress("正在准备搜索…")
        self.worker.start_preview(
            PreviewRequest(
                channel=channel,
                tag=tag,
                max_posts=self.config.max_posts,
                max_results=self.config.preview_max_results,
            )
        )

    def cancel_preview(self) -> None:
        if self.worker:
            self.worker.cancel_preview()
        self.window.task_page.set_preview_busy(False)

    def _on_preview_finished(
        self, rows: list[dict], total_count: int, display_limit: int
    ) -> None:
        self.window.set_search_preview_results(rows, total_count, display_limit)

    def _on_preview_failed(self, message: str) -> None:
        self.window.set_search_preview_error(message)

    def cancel_task(self) -> None:
        if self.worker:
            self.cancelled = True
            self.worker.cancel_scan()
            self.window.set_task_detail("正在停止任务…")
            self.window.set_tray_task_state()

    def resume_from_tray(self) -> None:
        if self.queue and self.queue[0].status == "已暂停":
            self.pause_task(0)

    def pause_from_tray(self) -> None:
        if self.queue and self.queue[0].status == "下载中":
            self.pause_task(0)

    def pause_task(self, index: int) -> None:
        """暂停/继续切换：按钮根据当前状态决定行为"""
        if not (0 <= index < len(self.queue)):
            return
        task = self.queue[index]
        if index == 0 and self.worker and self.worker.isRunning():
            if task.status == "已暂停":
                # 继续
                task.status = "下载中"
                self.worker.resume_scan()
            else:
                # 暂停
                task.status = "已暂停"
                self.worker.pause_scan()
        elif index > 0:
            # 队列中等待的任务直接标记暂停（不影响当前运行）
            task.status = "已暂停" if task.status != "已暂停" else "排队中"
        self.window.set_task_queue(self.queue)
        if index == 0:
            paused = task.status == "已暂停"
            self.window.set_tray_task_state(
                can_pause=not paused,
                can_resume=paused,
                can_stop=True,
            )

    def delete_task(self, index: int) -> None:
        if 0 <= index < len(self.queue):
            if index == 0 and self.worker and self.worker.isRunning():
                self._discard_current_task = True
                self.cancel_task()
            self.queue.pop(index)
            self.window.set_task_queue(self.queue)
            if index == 0:
                self.window.set_tray_task_state()
            self.window.show_success("任务已删除")

    def _on_scan_started(self) -> None:
        self.window.set_task_busy(True)
        self.window.set_tray_task_state(can_pause=True, can_stop=True)

    def _on_scan_plan_ready(self, posts: int, total: int) -> None:
        if not self.queue:
            return
        task = self.queue[0]
        task.total = max(0, total)
        task.progress = 0
        self.window.set_task_progress(task.downloaded, task.skipped, task.total)
        self.window.set_task_queue(self.queue)
        self.window.set_task_detail(f"已从预览缓存载入 {posts} 篇帖子，共 {total} 个待处理文件")

    def _on_scan_discovery_finished(self, posts: int, files: int) -> None:
        self.window.set_task_detail(
            f"扫描完成 · 匹配 {posts} 篇帖子 · 发现 {files} 个文件 · 正在等待下载完成"
        )

    def _on_scan_progress(self, downloaded: int, skipped: int, location: str) -> None:
        self.window.set_task_detail(f"{location} · 已下载 {downloaded} 张 · 已跳过 {skipped} 张")
        if self.queue:
            task = self.queue[0]
            task.downloaded = downloaded
            task.skipped = skipped
            completed = downloaded + skipped
            if task.total > 0:
                task.progress = min(100, int(completed * 100 / task.total))
            self.window.set_task_progress(downloaded, skipped, task.total)
            self.window.set_task_queue(self.queue)

    def _on_post_status_changed(self, post_id: int, status: str) -> None:
        if not self.queue:
            return
        task = self.queue[0]
        task.post_statuses[post_id] = status
        completed = sum(
            1 for value in task.post_statuses.values() if value.startswith("已完成")
        )
        if task.total <= 0:
            task.progress = int(completed * 100 / max(1, len(task.post_statuses)))
        self.window.set_task_queue(self.queue)
        # 只在帖子真正完成时刷新日志，不在每次状态变化时刷新
        if status.startswith("已完成"):
            self._refresh_log_view()

    def _on_scan_finished(self, posts: int, downloaded: int, skipped: int) -> None:
        self.window.set_task_busy(False)
        self.window.set_tray_task_state()
        status = "已取消" if self.cancelled else "已完成"
        if self.queue:
            self.queue[0].status = status
            if self.cancelled:
                for post_id, post_status in self.queue[0].post_statuses.items():
                    if not post_status.startswith("已完成"):
                        self.queue[0].post_statuses[post_id] = "未完成 · 任务已取消"
                completed = sum(
                    1 for value in self.queue[0].post_statuses.values()
                    if value.startswith("已完成")
                )
                self.queue[0].progress = int(
                    completed * 100 / max(1, len(self.queue[0].post_statuses))
                )
            else:
                self.queue[0].progress = 100
            self.queue[0].downloaded = downloaded
            self.queue[0].skipped = skipped
            self.queue[0].total = max(self.queue[0].total, downloaded + skipped)
            self.window.set_task_progress(downloaded, skipped, self.queue[0].total)
            self.window.set_task_queue(self.queue)
        self.window.set_task_detail(
            f"{status}：匹配 {posts} 篇帖子，下载 {downloaded} 张，跳过 {skipped} 张"
        )
        if self.current_request and not self._discard_current_task:
            self.config.add_history(
                {
                    "channel": self.current_request.channel,
                    "tag": self.current_request.tag,
                    "status": status,
                    "posts": posts,
                    "downloaded": downloaded,
                    "skipped": skipped,
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
            )
        self._refresh_local_data()
        if self.current_open_after and self.current_request and not self._discard_current_task:
            self.open_specific_folder(str(self.current_request.save_root))
        if not self._discard_current_task:
            self.window.show_success(f"任务结束，新增 {downloaded} 张图片")
        if (
            not self._discard_current_task
            and not self.cancelled
            and self.config.enable_system_notifications
        ):
            self.window.show_system_notification(
                "下载完成",
                f"新增 {downloaded} 个文件，跳过 {skipped} 个文件。",
            )
        self._discard_current_task = False

    def _on_scan_failed(self, message: str) -> None:
        self.window.set_task_busy(False)
        self.window.set_tray_task_state()
        if self.queue:
            self.queue[0].status = "已取消"
            for post_id, status in self.queue[0].post_statuses.items():
                if not status.startswith("已完成"):
                    self.queue[0].post_statuses[post_id] = "未完成 · 任务失败"
            self.window.set_task_queue(self.queue)
        if self.current_request and not self._discard_current_task:
            downloaded = self.queue[0].downloaded if self.queue else 0
            skipped = self.queue[0].skipped if self.queue else 0
            self.config.add_history(
                {
                    "channel": self.current_request.channel,
                    "tag": self.current_request.tag,
                    "status": "失败",
                    "posts": len(self.queue[0].post_statuses) if self.queue else 0,
                    "downloaded": downloaded,
                    "skipped": skipped,
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
            )
            self._refresh_local_data()
        self._refresh_log_view()
        if not self._discard_current_task:
            self.window.show_error(f"任务失败：{message}")
        self._discard_current_task = False

    def save_settings(self, values: dict) -> None:
        old_credentials = (self.config.api_id, self.config.api_hash, self.config.session_name, self.config.session_dir)
        old_theme_mode = self.config.theme_mode
        old_lang = self.config.lang
        mode = values.get("save_mode", self.config.save_mode)
        if mode == "last":
            mode = self.config.save_mode
        self.config.save_root = values.get("save_root") or self.config.save_root
        self.config.save_mode = mode
        self.config.max_posts = int(values.get("max_posts", self.config.max_posts))
        self.config.preview_max_results = max(
            10, int(values.get("preview_max_results", self.config.preview_max_results))
        )
        self.config.concurrency = max(1, int(values.get("concurrency", self.config.concurrency)))
        self.config.file_download_interval = max(
            0.0, float(values.get("file_download_interval", self.config.file_download_interval))
        )
        self.config.filename_limit = max(
            20, int(values.get("filename_limit", self.config.filename_limit))
        )
        self.config.empty_tag_action = values.get("empty_tag_action", self.config.empty_tag_action)
        self.config.restore_on_launch = bool(
            values.get("restore_on_launch", self.config.restore_on_launch)
        )
        self.config.use_last_mode = bool(values.get("use_last_mode", self.config.use_last_mode))
        self.config.auto_fill_tag = bool(values.get("auto_fill_tag", self.config.auto_fill_tag))
        self.config.duplicate_mode = values.get("skip_duplicates", self.config.duplicate_mode)
        self.config.skip_duplicates = self.config.duplicate_mode == "skip"
        self.config.filename_template = values.get("filename_template") or self.config.filename_template
        self.config.preserve_original_name = bool(values.get("preserve_original_name", True))
        self.config.api_id = values.get("api_id", "").strip()
        self.config.api_hash = values.get("api_hash", "").strip()
        self.config.session_name = values.get("session_name", "default").strip() or "default"
        self.config.session_dir = values.get("session_path", "").strip()
        self.config.theme_mode = values.get("theme_mode", "auto")
        self.config.lang = values.get("lang") or self.config.lang
        self.config.open_after_download = bool(values.get("open_after_download"))
        self.config.enable_system_notifications = bool(
            values.get("enable_system_notifications", True)
        )
        self.config.use_dpapi_encryption = bool(values.get("use_dpapi_encryption", True))
        self.config.save()
        self.window.set_system_notifications_enabled(self.config.enable_system_notifications)
        if old_theme_mode != self.config.theme_mode:
            self._apply_theme()
        if old_lang != self.config.lang:
            self.window.apply_language(self.config.lang)
        self.window.set_task_defaults(
            self.config.save_root,
            SAVE_MODE_LABELS.get(self.config.save_mode, self.config.save_mode),
            self.config.save_mode,
        )
        self.window.set_task_rule_summary(
            self.config.filename_template,
            self.config.preserve_original_name,
            self.config.duplicate_mode,
            self.config.open_after_download,
            self.config.concurrency,
            self.config.file_download_interval,
            self.config.filename_limit,
        )
        self.window.set_summary(
            self.config.save_root,
            SAVE_MODE_LABELS.get(self.config.save_mode, self.config.save_mode),
        )
        self.window.show_success("设置已保存")
        new_credentials = (self.config.api_id, self.config.api_hash, self.config.session_name, self.config.session_dir)
        if old_credentials != new_credentials:
            self._restart_worker()

    def _apply_theme(self) -> None:
        theme = {"auto": Theme.AUTO, "light": Theme.LIGHT, "dark": Theme.DARK}.get(
            self.config.theme_mode, Theme.AUTO
        )
        setTheme(theme, lazy=True)
        self.window.refresh_tooltip_theme()

    def clear_history(self) -> None:
        self.config.history = []
        self.config.save()
        self._refresh_local_data()
        self.window.show_success("下载历史已清空")

    def delete_history(self, index: int) -> None:
        history = list(self.config.history or [])
        if not 0 <= index < len(history):
            return
        history.pop(index)
        self.config.history = history
        self.config.save()
        self._refresh_local_data()
        self.window.show_success("历史记录已删除")

    def open_folder(self) -> None:
        path = Path(self.config.save_root).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(path.as_uri())

    def open_log(self) -> None:
        path = self.logger.get_log_path().resolve()
        path.touch(exist_ok=True)
        QDesktopServices.openUrl(path.as_uri())

    def open_log_folder(self) -> None:
        path = self.logger.log_dir.resolve()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(path.as_uri())

    def _refresh_log_view(self) -> None:
        path = self.logger.get_log_path().resolve()
        try:
            content = path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError:
            content = "无法读取日志文件。"
        lines = content.splitlines()
        self.window.set_log(str(path), "\n".join(lines[-300:]))

    def _refresh_local_data(self) -> None:
        history = self.config.history or []
        today_key = datetime.now().strftime("%Y-%m-%d")
        today = sum(
            int(item.get("downloaded", 0)) for item in history if str(item.get("time", "")).startswith(today_key))
        total = sum(int(item.get("downloaded", 0)) for item in history)
        tags = {item.get("tag") for item in history if item.get("tag")}
        common_tags = []
        for item in history:
            tag = str(item.get("tag", "")).strip()
            if tag and tag not in common_tags:
                common_tags.append(tag)
        self.window.set_home_stats(
            today,
            total,
            len(history),
            len(tags),
            self._disk_usage(),
            history[0].get("time", "-")[5:16] if history else "-",
        )
        self.window.set_common_tags(common_tags)
        self.refresh_trend("day")
        self.window.set_home_recent_tasks(
            [
                {
                    "name": item.get("channel", "-"),
                    "status": item.get("status", "已完成"),
                    "progress": 100 if item.get("status") == "已完成" else 0,
                    "time": item.get("time", "-")[5:16],
                }
                for item in history[:5]
            ]
        )
        self.window.set_history(
            [
                HistoryRow(
                    item.get("channel", "-"),
                    item.get("tag", ""),
                    item.get("status", "已完成"),
                    int(item.get("posts", 0)),
                    int(item.get("downloaded", 0)),
                    item.get("time", "-"),
                )
                for item in history
            ]
        )
        self._refresh_log_view()

    def refresh_trend(self, period: str) -> None:
        history = self.config.history or []
        trend = []
        labels = []
        if period == "week":
            today = datetime.now()
            current_monday = today - timedelta(days=today.weekday())
            for offset in range(6, -1, -1):
                start = current_monday - timedelta(weeks=offset)
                end = start + timedelta(days=7)
                labels.append(start.strftime("%m-%d"))
                trend.append(
                    sum(
                        int(item.get("downloaded", 0))
                        for item in history
                        if start
                        <= self._record_datetime(item.get("time"))
                        < end
                    )
                )
        else:
            for offset in range(6, -1, -1):
                day = datetime.now() - timedelta(days=offset)
                key = day.strftime("%Y-%m-%d")
                labels.append(day.strftime("%m-%d"))
                trend.append(
                    sum(
                        int(item.get("downloaded", 0))
                        for item in history
                        if str(item.get("time", "")).startswith(key)
                    )
                )
        self.window.set_home_trend_with_labels(trend, labels)

    @staticmethod
    def _record_datetime(value) -> datetime:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d %H:%M")
        except ValueError:
            return datetime.min

    def _disk_usage(self) -> str:
        root = Path(self.config.save_root).expanduser()
        if not root.exists():
            return "0 B"
        try:
            total = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        except OSError:
            return "-"
        for unit in ("B", "KB", "MB", "GB"):
            if total < 1024 or unit == "GB":
                return f"{total:.1f} {unit}" if unit != "B" else f"{int(total)} B"
            total /= 1024
        return "0 B"

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            QTimer.singleShot(50, self._poll_shutdown)
            return
        self._finish_shutdown()

    def _poll_shutdown(self) -> None:
        if self.worker and self.worker.isRunning():
            QTimer.singleShot(50, self._poll_shutdown)
            return
        self._finish_shutdown()

    def _finish_shutdown(self) -> None:
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
        self.worker = None
        app = QApplication.instance()
        if app is not None:
            app.quit()
