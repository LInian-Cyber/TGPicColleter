from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication
from qfluentwidgets import Theme, setTheme

from .config import AppConfig
from .igp import (
    UnsupportedMetadataFormat,
    create_igp_package,
    default_sidecar_path,
    discover_sidecar_pairs,
    embed_metadata_file,
    image_path_from_sidecar,
    validate_sidecar_pair,
)
from .logger import get_logger
from .models import (
    PreviewRequest,
    SAVE_MODE_LABELS,
    ScanRequest,
    TelegramCredentials,
    normalize_channel_reference,
)
from .network import run_network_diagnostics
from .telegram_worker import TelegramWorker
from .ui import HistoryRow, MainWindow, TaskRow
from .yande_worker import YandeWorker


class NetworkTestWorker(QThread):
    result_ready = Signal(bool, str)

    def __init__(self, proxy_url: str, use_system_proxy: bool, parent=None):
        super().__init__(parent)
        self.proxy_url = proxy_url
        self.use_system_proxy = use_system_proxy

    def run(self) -> None:
        ok, message = run_network_diagnostics(self.proxy_url, self.use_system_proxy)
        self.result_ready.emit(ok, message)


class AppController(QObject):
    """Connects the pure UI layer to configuration and Telegram services."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.logger = get_logger()
        self.window = MainWindow()
        self.worker: TelegramWorker | None = None
        self.yande_worker: YandeWorker | None = None
        self.network_test_worker: NetworkTestWorker | None = None
        self.authorized = False
        self.current_request: ScanRequest | None = None
        self.current_open_after = False
        self.cancelled = False
        self.queue: list[TaskRow] = []
        self._loaded_dialogs: list[dict] = []
        self._last_preview_params: dict = {}
        self._discard_current_task = False
        self._shutting_down = False
        self._shutdown_complete = False
        self._current_account_name = ""
        self._current_account_phone = ""

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
            self.config.save_extended_info,
            self.config.open_after_download,
            self.config.duplicate_mode == "skip",
        )

        # 加载频道历史
        channel_history = self.config.get_channel_history_with_avatars()
        self.window.task_page.add_channel_history(channel_history)
        self.window.set_channel_cache_rows(channel_history)

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
            self.config.chunk_concurrency,
            self.config.file_download_interval,
            self.config.filename_limit,
            self.config.empty_tag_action,
        )
        self.window.set_summary(
            self.config.save_root,
            SAVE_MODE_LABELS.get(self.config.save_mode, self.config.save_mode),
        )
        self.window.set_settings_defaults(self._settings_dict())
        self.window.set_yande_defaults(
            self.config.save_root,
            self.config.yande_cookie,
            self.config.yande_tags,
            list(self.config.yande_tag_history or []),
        )
        self._refresh_account_sessions()
        self.window.set_system_notifications_enabled(self.config.enable_system_notifications)
        self.window.set_close_behavior(
            self.config.close_behavior,
            self.config.remember_close_behavior,
        )
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
            "chunk_concurrency": self.config.chunk_concurrency,
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
            "close_behavior": self.config.close_behavior,
            "remember_close_behavior": self.config.remember_close_behavior,
            "use_dpapi_encryption": self.config.use_dpapi_encryption,
            "save_extended_info": self.config.save_extended_info,
            "use_system_proxy": self.config.use_system_proxy,
            "proxy_url": self.config.proxy_url,
        }

    def _connect_ui(self) -> None:
        w = self.window
        w.task_start_requested.connect(self.start_task)
        w.task_cancel_requested.connect(self.cancel_task)
        w.task_pause_requested.connect(self.pause_task)
        w.task_delete_requested.connect(self.delete_task)
        w.task_preview_requested.connect(self.start_preview)
        w.task_preview_cancel_requested.connect(self.cancel_preview)
        w.task_preview_download_requested.connect(self.start_preview_download)
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
        w.account_switch_requested.connect(self.switch_account)
        w.account_add_requested.connect(self.add_account)
        w.settings_save_requested.connect(self.save_settings)
        w.settings_network_test_requested.connect(self.test_network_proxy)
        w.settings_data_dir_open_requested.connect(self.open_data_folder)
        w.settings_logout_requested.connect(self.logout)
        w.settings_cache_clear_requested.connect(self.clear_cache)
        w.settings_channel_cache_refresh_requested.connect(self.refresh_channel_cache)
        w.settings_channel_cache_delete_requested.connect(self.delete_channel_cache)
        w.settings_channel_cache_clear_requested.connect(self.clear_channel_cache)
        w.close_behavior_changed.connect(self.save_close_behavior)
        w.export_requested.connect(self.export_images)
        w.export_open_output_requested.connect(self.open_specific_folder)
        w.yande_preview_requested.connect(self.preview_yande)
        w.yande_download_requested.connect(self.download_yande)
        w.yande_cancel_requested.connect(self.cancel_yande)
        w.yande_open_folder_requested.connect(self.open_specific_folder)
        w.open_folder_requested.connect(self.open_folder)
        w.open_log_requested.connect(self.open_log)
        w.open_log_folder_requested.connect(self.open_log_folder)
        w.history_clear_requested.connect(self.clear_history)
        w.history_delete_requested.connect(self.delete_history)
        w.history_open_folder_requested.connect(self.open_specific_folder)
        w.trend_period_changed.connect(self.refresh_trend)
        w.window_closing.connect(self.shutdown)
        w.task_page.open_current_folder_requested.connect(self.open_specific_folder)

    def open_specific_folder(self, path_str: str) -> None:
        raw_path = str(path_str or "").strip()
        if not raw_path:
            self.window.show_error("请先选择目录")
            return
        try:
            path = Path(raw_path).expanduser().resolve()
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.window.show_error(f"无法打开目录：{exc}")
            return
        QDesktopServices.openUrl(path.as_uri())

    @staticmethod
    def _available_export_path(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(2, 10000):
            candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
            if not candidate.exists():
                return candidate
        return path.with_name(f"{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix}")

    def _single_export_pair(self, target: Path) -> tuple[Path, Path]:
        sidecar_image = image_path_from_sidecar(target)
        if sidecar_image is not None:
            image_path = sidecar_image
            sidecar_path = target
        else:
            image_path = target
            sidecar_path = default_sidecar_path(image_path)
        validate_sidecar_pair(image_path, sidecar_path, strict_name=True)
        return image_path, sidecar_path

    def _export_text(self, zh: str, en: str) -> str:
        return en if getattr(self.window, "_language", "zh_CN") == "en_US" else zh

    def export_images(self, params: dict) -> None:
        source_raw = str(params.get("source_path", "")).strip()
        if not source_raw:
            self.window.show_error("请先选择来源")
            return
        source_path = Path(source_raw).expanduser().resolve()
        if not source_path.exists():
            self.window.show_error("来源不存在")
            return

        mode = str(params.get("mode", "igp")).strip()
        if mode not in {"igp", "metadata"}:
            self.window.show_error("导出模式无效")
            return

        try:
            if source_path.is_dir():
                pairs, orphan_images, orphan_sidecars = discover_sidecar_pairs(
                    source_path,
                    recursive=bool(params.get("recursive", False)),
                )
            else:
                pairs = [self._single_export_pair(source_path)]
                orphan_images = 0
                orphan_sidecars = 0
        except (OSError, ValueError) as exc:
            self.window.show_error(str(exc))
            return

        skipped = orphan_images + orphan_sidecars
        if not pairs:
            summary = self._export_text(
                f"没有找到可导出的匹配文件。跳过不匹配 {skipped} 个。",
                f"No matched files found. Skipped {skipped} unmatched files.",
            )
            self.window.set_export_result(summary, [])
            self.window.show_error("没有找到可导出的匹配文件")
            return

        output_raw = str(params.get("output_path", "")).strip()
        output_dir = Path(output_raw).expanduser().resolve() if output_raw else None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)

        igp_options = dict(params.get("igp_options", {}) or {})
        metadata_sections = igp_options.get("metadata_sections")
        include_checksums = bool(igp_options.get("include_checksums", True))

        rows: list[dict] = []
        succeeded = 0
        failed = 0
        for image_path, sidecar_path in pairs:
            target_dir = output_dir or image_path.parent
            target_dir.mkdir(parents=True, exist_ok=True)
            try:
                if mode == "igp":
                    output_path = self._available_export_path(target_dir / f"{image_path.stem}.igp")
                    result = create_igp_package(
                        image_path,
                        sidecar_path,
                        output_path,
                        metadata_sections=metadata_sections,
                        include_checksums=include_checksums,
                    )
                    mode_label = "IGP"
                else:
                    output_path = self._available_export_path(
                        target_dir / f"{image_path.stem}.igpmeta{image_path.suffix}"
                    )
                    result = embed_metadata_file(image_path, sidecar_path, output_path)
                    mode_label = self._export_text("元数据", "Metadata")
                succeeded += 1
                rows.append(
                    {
                        "file": image_path.name,
                        "mode": mode_label,
                        "status": self._export_text("成功", "Done"),
                        "output": str(result),
                        "message": "",
                    }
                )
            except (OSError, ValueError, UnsupportedMetadataFormat) as exc:
                failed += 1
                rows.append(
                    {
                        "file": image_path.name,
                        "mode": "IGP" if mode == "igp" else self._export_text("元数据", "Metadata"),
                        "status": self._export_text("失败", "Failed"),
                        "output": "",
                        "message": str(exc),
                    }
                )

        summary = self._export_text(
            f"导出完成：成功 {succeeded}，失败 {failed}，跳过不匹配 {skipped}。",
            f"Export complete: {succeeded} succeeded, {failed} failed, {skipped} unmatched skipped.",
        )
        self.window.set_export_result(summary, rows)
        if failed:
            self.window.show_info("导出完成，部分文件失败")
        else:
            self.window.show_success("导出完成")

    def preview_yande(self, params: dict) -> None:
        if self.yande_worker and self.yande_worker.isRunning():
            self.window.show_info("Yande 任务正在运行，请稍候")
            return
        params = self._with_network_params(params)
        self._save_yande_params(params)
        self.window.set_yande_busy(True)
        self.window.set_yande_progress(0, 1, "正在从 yande.re 读取帖子…")
        self.yande_worker = YandeWorker(params, mode="preview")
        self.yande_worker.rows_ready.connect(self.window.set_yande_rows)
        self.yande_worker.progress.connect(self._on_yande_progress)
        self.yande_worker.finished.connect(lambda summary: self._on_yande_finished(summary, "preview", params))
        self.yande_worker.failed.connect(self._on_yande_failed)
        self.yande_worker.start()

    def download_yande(self, params: dict) -> None:
        if self.yande_worker and self.yande_worker.isRunning():
            self.window.show_info("Yande 任务正在运行，请稍候")
            return
        params = self._with_network_params(params)
        if not str(params.get("save_root", "")).strip():
            self.window.show_error("请先设置 Yande 保存目录")
            return
        rating = str(params.get("rating", "all"))
        if rating == "explicit" and not str(params.get("cookie", "")).strip():
            self.window.show_info("Explicit 内容通常需要 Yande 登录态 Cookie，未填写时可能没有结果")
        self._save_yande_params(params)
        self.window.set_yande_busy(True)
        has_preview_rows = bool(params.get("rows"))
        self.window.set_yande_progress(
            0,
            1,
            "正在下载当前预览结果…" if has_preview_rows else "正在搜索并准备 Yande 下载…",
        )
        self.yande_worker = YandeWorker(params, mode="download")
        self.yande_worker.rows_ready.connect(self.window.set_yande_rows)
        self.yande_worker.row_updated.connect(self._on_yande_row_updated)
        self.yande_worker.progress.connect(self._on_yande_progress)
        self.yande_worker.finished.connect(lambda summary: self._on_yande_finished(summary, "download", params))
        self.yande_worker.failed.connect(self._on_yande_failed)
        self.yande_worker.start()

    def _with_network_params(self, params: dict) -> dict:
        params = dict(params)
        params["proxy_url"] = self.config.proxy_url
        params["use_system_proxy"] = self.config.use_system_proxy
        return params

    def test_network_proxy(self, values: dict) -> None:
        if self.network_test_worker and self.network_test_worker.isRunning():
            self.window.show_info("网络代理测试正在运行，请稍候")
            return
        proxy_url = str(values.get("proxy_url", "") or "").strip()
        use_system_proxy = bool(values.get("use_system_proxy", True))
        self.window.show_info("正在测试网络代理…")
        worker = NetworkTestWorker(proxy_url, use_system_proxy, self)
        self.network_test_worker = worker
        worker.result_ready.connect(self._on_network_test_finished)
        worker.finished.connect(worker.deleteLater)
        worker.finished.connect(lambda: setattr(self, "network_test_worker", None))
        worker.start()

    def _on_network_test_finished(self, ok: bool, message: str) -> None:
        self.logger.info(f"网络代理测试结果: {message.replace(chr(10), ' | ')}")
        if ok:
            self.window.show_success(f"网络代理测试通过：{message}")
        else:
            self.window.show_error(f"网络代理测试未通过：{message}")

    def cancel_yande(self) -> None:
        if self.yande_worker and self.yande_worker.isRunning():
            self.yande_worker.cancel()
            self.window.set_yande_progress(0, 1, "正在停止 Yande 任务…")

    def _on_yande_progress(self, completed: int, total: int, message: str) -> None:
        self.window.set_yande_progress(completed, total, message)
        self._refresh_log_view()

    def _on_yande_row_updated(self, index: int, status: str, message: str) -> None:
        self.window.update_yande_row(index, status, message)
        self._refresh_log_view()

    def _save_yande_params(self, params: dict) -> None:
        tags = str(params.get("tags", "") or "").strip()
        self.config.yande_tags = tags
        self.config.save_root = str(params.get("save_root", self.config.save_root) or self.config.save_root)
        current_cookie = str(params.get("cookie", "") or "").strip()
        if bool(params.get("remember_cookie")):
            self.config.yande_cookie = current_cookie
        if tags:
            self.config.add_yande_tag_history(tags)
        else:
            self.config.save()
        self.window.set_yande_defaults(
            self.config.save_root,
            self.config.yande_cookie if bool(params.get("remember_cookie")) else current_cookie,
            self.config.yande_tags,
            list(self.config.yande_tag_history or []),
        )

    def _on_yande_finished(self, summary: dict, mode: str, params: dict) -> None:
        self.window.set_yande_busy(False)
        total = int(summary.get("total", 0) or 0)
        downloaded = int(summary.get("downloaded", 0) or 0)
        skipped = int(summary.get("skipped", 0) or 0)
        failed = int(summary.get("failed", 0) or 0)
        cancelled = bool(summary.get("cancelled"))
        if mode == "preview":
            self.window.set_yande_progress(total, max(1, total), f"预览完成：找到 {total} 条。")
            self._refresh_log_view()
            if not total:
                self.window.show_info("Yande 没有找到匹配结果")
            return

        status = "已取消" if cancelled else ("失败" if failed and not downloaded else "已完成")
        self.config.add_history(
            {
                "channel": "yande.re",
                "tag": str(params.get("tags", "") or "未分类"),
                "status": status,
                "posts": total,
                "downloaded": downloaded,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "save_root": summary.get("save_root", params.get("save_root", self.config.save_root)),
            }
        )
        self._refresh_local_data()
        self.window.set_yande_progress(
            downloaded + skipped + failed,
            max(1, total),
            f"Yande 下载结束：下载 {downloaded}，跳过 {skipped}，失败 {failed}。",
        )
        if cancelled:
            self.window.show_info("Yande 下载已停止")
        elif failed:
            self.window.show_info("Yande 下载完成，部分文件失败")
        else:
            self.window.show_success("Yande 下载完成")
        self._refresh_log_view()

    def _on_yande_failed(self, message: str) -> None:
        self.window.set_yande_busy(False)
        self.window.set_yande_progress(0, 1, f"Yande 任务失败：{message}")
        self.window.show_error(f"Yande 任务失败：{message}")
        self._refresh_log_view()

    def clear_queue(self) -> None:
        if self.worker and self.worker.isRunning():
            self._discard_current_task = True
        self.cancel_task()  # 先停止当前任务
        self.queue.clear()
        self.window.set_task_queue(self.queue)
        self.window.set_tray_task_state(status_text="空闲")
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

    def refresh_channel_cache(self) -> None:
        if self._ensure_worker(quiet=True) and self.worker and self.authorized:
            self.worker.load_dialogs()
            self.window.show_info("正在刷新频道缓存…")
            return
        self.window.set_channel_cache_rows(self._combined_channel_history(self._loaded_dialogs))
        self.window.show_info("当前未连接 Telegram，仅显示本地频道缓存")

    def delete_channel_cache(self, channel_id: str) -> None:
        history = list(self.config.channel_history or [])
        kept: list[dict] = []
        removed = False
        for item in history:
            if str(item.get("id", "")).strip() == channel_id:
                removed = True
                avatar_path = item.get("avatar_path")
                if avatar_path:
                    try:
                        Path(avatar_path).unlink(missing_ok=True)
                    except OSError:
                        pass
                continue
            kept.append(item)
        self.config.channel_history = kept
        self.config.save()
        rows = self._combined_channel_history(self._loaded_dialogs)
        self.window.task_page.add_channel_history(rows)
        self.window.set_channel_cache_rows(rows)
        self.window.show_success("频道缓存已删除" if removed else "未找到该频道缓存")

    def clear_channel_cache(self) -> None:
        for item in list(self.config.channel_history or []):
            avatar_path = item.get("avatar_path")
            if avatar_path:
                try:
                    Path(avatar_path).unlink(missing_ok=True)
                except OSError:
                    pass
        self.config.channel_history = []
        self.config.save()
        rows = self._combined_channel_history(self._loaded_dialogs)
        self.window.task_page.add_channel_history(rows)
        self.window.set_channel_cache_rows(rows)
        self.window.show_success("频道缓存已清空")

    def _credentials(self) -> TelegramCredentials:
        return TelegramCredentials(
            api_id=int(self.config.api_id),
            api_hash=self.config.api_hash.strip(),
            phone=self.config.phone.strip(),
            session_path=self.config.session_path,
            proxy_url=self.config.proxy_url,
            use_system_proxy=self.config.use_system_proxy,
        )

    def _refresh_account_sessions(self) -> None:
        self.window.set_account_sessions(
            self.config.get_account_sessions_with_avatars(),
            self.config.current_account_key,
        )

    def _remember_current_account(
        self,
        name: str = "",
        phone: str = "",
        avatar_bytes: bytes = b"",
    ) -> None:
        self.config.add_account_session(
            self.config.session_name,
            self.config.session_dir,
            name or self._current_account_name,
            phone or self._current_account_phone,
            avatar_bytes,
        )
        self._refresh_account_sessions()

    def _has_active_transfer(self) -> bool:
        return bool(
            self.current_request
            and self.queue
            and self.queue[0].status in {"下载中", "已暂停", "排队中"}
        )

    def add_account(self) -> None:
        if self._has_active_transfer():
            self.window.show_error("请先停止当前下载任务，再切换或添加账号")
            return
        existing = {
            str(item.get("session_name", "") or "")
            for item in self.config.account_sessions or []
            if str(item.get("session_dir", "") or "") == self.config.session_dir
        }
        for index in range(2, 1000):
            session_name = f"account_{index}"
            if session_name not in existing and session_name != self.config.session_name:
                break
        else:
            session_name = f"account_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.config.session_name = session_name
        self.config.phone = ""
        self.config.save()
        self.window.set_settings_defaults(self._settings_dict())
        self.window.set_login_phone("")
        self._restart_worker()
        self._refresh_account_sessions()
        self.window.navigate_to_login()
        self.window.set_qr_message("新账号会话已创建，请刷新二维码或使用手机号登录", allow_auto_retry=True)
        self.window.show_info("已创建新账号会话，登录成功后会自动加入账号列表")

    def switch_account(self, account_key: str) -> None:
        account_key = str(account_key or "").strip()
        if not account_key:
            return
        if account_key == self.config.current_account_key:
            self.window.show_info("当前已经是这个账号")
            return
        if self._has_active_transfer():
            self.window.show_error("请先停止当前下载任务，再切换账号")
            return
        profile = next(
            (
                item
                for item in self.config.account_sessions or []
                if str(item.get("key", "")) == account_key
            ),
            None,
        )
        if not profile:
            self.window.show_error("没有找到这个账号档案")
            self._refresh_account_sessions()
            return
        self.config.session_name = str(profile.get("session_name", "") or "default")
        self.config.session_dir = str(profile.get("session_dir", "") or "")
        self.config.phone = str(profile.get("phone", "") or "")
        self.config.save()
        self.window.set_settings_defaults(self._settings_dict())
        self.window.set_login_phone(self.config.phone)
        self._restart_worker()
        self._refresh_account_sessions()
        self.window.navigate_to_login()
        display = str(profile.get("name", "") or profile.get("phone", "") or self.config.session_name)
        self.window.show_info(f"正在切换到 {display}")

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
        self.worker.scan_metrics_changed.connect(self._on_scan_metrics_changed)
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
            self.worker.wait(10000)
        self.worker = None
        self.authorized = False
        self.window.set_account()
        self._ensure_worker(quiet=True)

    def _on_worker_ready(self, authorized: bool) -> None:
        self.window.set_session_status(authorized, "本地 Telethon Session 已加载" if authorized else "未登录")
        self._refresh_account_sessions()
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
        self._current_account_name = name
        self._current_account_phone = phone
        self.config.phone = phone
        self.config.save()
        self._remember_current_account(name, phone)
        self.window.set_account(name, phone, "Telethon")
        self.window.set_session_status(True, "当前会话可正常使用")
        self.window.show_success(f"欢迎回来，{name}")

        # 自动加载对话列表
        if self.worker:
            self.worker.load_dialogs()

    def _on_user_profile_updated(self, name: str, phone: str, avatar_bytes: bytes) -> None:
        """处理用户头像更新"""
        self._current_account_name = name or self._current_account_name
        self._current_account_phone = phone or self._current_account_phone
        self._remember_current_account(name, phone, avatar_bytes)
        self.window.set_user_avatar(avatar_bytes)

    def _on_channel_info_fetched(self, channel_id: str, channel_name: str, avatar_bytes: bytes) -> None:
        """处理频道信息获取"""
        self.config.add_channel_to_history(channel_id, channel_name, avatar_bytes)
        # 刷新下拉列表
        self.window.task_page.add_channel_history(
            self._combined_channel_history(self._loaded_dialogs)
        )
        self.window.set_channel_cache_rows(
            self._combined_channel_history(self._loaded_dialogs)
        )

    def _on_dialogs_loaded(self, dialogs: list[dict]) -> None:
        """处理对话列表加载完成"""
        self._loaded_dialogs = dialogs
        self.window.task_page.add_channel_history(self._combined_channel_history(dialogs))
        self.window.set_channel_cache_rows(self._combined_channel_history(dialogs))

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
        self.config.remove_account_session(self.config.current_account_key)
        self.worker = None
        self.authorized = False
        self._current_account_name = ""
        self._current_account_phone = ""
        self.window.set_account()
        self.window.set_session_status(False, "已退出当前账号")
        self._refresh_account_sessions()
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
        if not str(params.get("tag", "") or "").strip() and self.config.empty_tag_action == "skip":
            self.window.show_error("当前设置为 Tag 为空时跳过；请填写 Tag 或在设置中更改空 Tag 处理方式")
            return
        duplicate_mode = "skip" if params.get("skip_duplicates", True) else self.config.duplicate_mode
        if duplicate_mode == "skip" and not params.get("skip_duplicates", True):
            duplicate_mode = "rename"
        resume_post_ids: list[int] = []
        for item in params.get("resume_post_ids", []) or []:
            try:
                resume_post_ids.append(int(item))
            except (TypeError, ValueError):
                continue
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
            chunk_concurrency=max(1, min(8, int(self.config.chunk_concurrency))),
            save_extended_info=bool(params.get("save_extended_info", False)),
            date_from=str(params.get("date_from", "") or ""),
            date_to=str(params.get("date_to", "") or ""),
            resume_post_ids=tuple(dict.fromkeys(resume_post_ids)),
        )
        self.config.channel = request.channel
        self.config.tag = request.tag
        # 保存任务状态以便恢复
        self.config.last_task_state = {
            "channel": request.channel,
            "tag": request.tag,
            "params": params,
            "status": "running",
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "downloaded": 0,
            "skipped": 0,
            "total": 0,
            "remaining": 0,
        }
        self.config.save()
        if not self._ensure_worker() or not self.worker:
            return
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
        self.config.save_extended_info = bool(params.get("save_extended_info", False))
        self.config.open_after_download = bool(params.get("open_after", False))
        if bool(params.get("skip_duplicates", True)):
            self.config.duplicate_mode = "skip"
            self.config.skip_duplicates = True
        else:
            if self.config.duplicate_mode == "skip":
                self.config.duplicate_mode = "rename"
            self.config.skip_duplicates = False
        state = dict(self.config.last_task_state or {})
        state["channel"] = params.get("channel") or state.get("channel", self.config.channel)
        state["tag"] = params.get("tag") or state.get("tag", self.config.tag)
        state["params"] = dict(params)
        self.config.last_task_state = state
        self.config.save()
        self.window.show_success("已保存为默认模板")
        self.window.set_task_defaults(
            self.config.save_root,
            SAVE_MODE_LABELS.get(self.config.save_mode, self.config.save_mode),
            self.config.save_mode,
            self.config.save_extended_info,
            self.config.open_after_download,
            self.config.duplicate_mode == "skip",
        )
        self.window.set_task_rule_summary(
            self.config.filename_template,
            self.config.preserve_original_name,
            self.config.duplicate_mode,
            self.config.open_after_download,
            self.config.concurrency,
            self.config.chunk_concurrency,
            self.config.file_download_interval,
            self.config.filename_limit,
            self.config.empty_tag_action,
        )
        self.window.set_settings_defaults(self._settings_dict())
        self.window.set_summary(
            self.config.save_root,
            SAVE_MODE_LABELS.get(self.config.save_mode, self.config.save_mode),
        )

    def save_advanced_rules(self, rules: list[dict]) -> None:
        self.config.advanced_rules = rules
        self.config.save()

    @staticmethod
    def _resumable_post_ids(state: dict) -> list[int]:
        post_statuses = dict(state.get("post_statuses", {}) or {})
        raw_ids = list(state.get("post_ids", []) or [])
        if post_statuses:
            raw_ids = [*raw_ids, *post_statuses.keys()]
        result: list[int] = []
        seen: set[int] = set()
        for item in raw_ids:
            try:
                post_id = int(item)
            except (TypeError, ValueError):
                continue
            status = str(
                post_statuses.get(str(post_id), post_statuses.get(post_id, ""))
                or ""
            )
            if post_statuses and status.startswith("已完成"):
                continue
            if post_id not in seen:
                seen.add(post_id)
                result.append(post_id)
        return result

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
        params = dict(state.get("params", {}) or {})
        params["channel"] = state.get("channel") or params.get("channel", "")
        params["tag"] = state.get("tag") or params.get("tag", "")
        resume_post_ids = self._resumable_post_ids(state)
        params["resume_post_ids"] = resume_post_ids
        if (state.get("post_statuses") or state.get("status") == "已完成") and not resume_post_ids:
            self.window.show_info("上次任务没有未完成帖子，已恢复配置；需要重跑可手动开始")
            return
        if not self.authorized:
            self.window.show_info("已恢复上次任务配置；登录 Telegram 后可继续下载")
            self.window.navigate_to_login()
            return
        if params.get("channel") and params.get("save_root"):
            self.window.show_info("正在继续上次任务；已下载媒体会按缓存跳过")
            self.start_task(params)
        else:
            self.window.show_info("已恢复上次任务配置，请确认频道和保存位置后开始下载")

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
        self._last_preview_params = dict(params)
        self._last_preview_params["channel"] = channel
        self._last_preview_params["tag"] = tag
        self.worker.start_preview(
            PreviewRequest(
                channel=channel,
                tag=tag,
                max_posts=self.config.max_posts,
                max_results=self.config.preview_max_results,
                include_replies=bool(params.get("include_replies", True)),
                extract_button_link=bool(params.get("extract_button_link", True)),
                button_keyword=str(params.get("button_keyword", "")).strip() or "原图",
                custom_extract_json=str(params.get("custom_extract_json", "")).strip(),
                date_from=str(params.get("date_from", "") or ""),
                date_to=str(params.get("date_to", "") or ""),
            )
        )

    def start_preview_download(self) -> None:
        if not self._last_preview_params:
            self.window.show_info("暂无可直接下载的预览任务")
            return
        self.start_task(dict(self._last_preview_params))

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
        self.window.set_tray_task_state(can_pause=True, can_stop=True, status_text="正在准备下载")

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

    @staticmethod
    def _format_eta(seconds: int) -> str:
        if seconds < 0:
            return "计算中"
        minutes, sec = divmod(int(seconds), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {sec}s"
        return f"{sec}s"

    def _update_last_task_snapshot(self, metrics: dict) -> None:
        if not self.config.last_task_state:
            return
        state = dict(self.config.last_task_state)
        state.update(
            {
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "downloaded": int(metrics.get("downloaded", 0)),
                "skipped": int(metrics.get("skipped", 0)),
                "total": int(metrics.get("total", 0)),
                "remaining": int(metrics.get("remaining", 0)),
                "queue_size": int(metrics.get("queue_size", 0)),
                "speed": float(metrics.get("speed", 0.0)),
            }
        )
        self.config.last_task_state = state
        self.config.save()

    def _on_scan_metrics_changed(self, metrics: dict) -> None:
        downloaded = int(metrics.get("downloaded", 0))
        skipped = int(metrics.get("skipped", 0))
        total = int(metrics.get("total", 0))
        completed = int(metrics.get("completed", downloaded + skipped))
        remaining = int(metrics.get("remaining", max(0, total - completed)))
        queue_size = int(metrics.get("queue_size", 0))
        speed = float(metrics.get("speed", 0.0))
        eta = self._format_eta(int(metrics.get("eta_seconds", -1)))
        metrics_text = f"速度 {speed:.2f} 文件/秒 · 队列 {queue_size} · 剩余 {remaining} · ETA {eta}"

        if self.queue:
            task = self.queue[0]
            task.downloaded = downloaded
            task.skipped = skipped
            task.total = max(task.total, total)
            if task.total > 0:
                task.progress = min(100, int(completed * 100 / task.total))
            task.metrics_text = metrics_text
            self.window.set_task_progress(downloaded, skipped, task.total)
            self.window.set_task_queue(self.queue)
        self.window.set_tray_task_state(
            can_pause=True,
            can_stop=True,
            status_text=f"正在下载：{completed}/{total or '?'} · 队列 {queue_size}",
        )
        self._update_last_task_snapshot(metrics)

    def _on_post_status_changed(self, post_id: int, status: str) -> None:
        if not self.queue:
            return
        task = self.queue[0]
        task.post_statuses[post_id] = status
        if self.config.last_task_state:
            state = dict(self.config.last_task_state)
            post_ids = list(dict.fromkeys([*state.get("post_ids", []), int(post_id)]))
            post_statuses = dict(state.get("post_statuses", {}) or {})
            post_statuses[str(post_id)] = status
            state["post_ids"] = post_ids
            state["post_statuses"] = post_statuses
            state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            self.config.last_task_state = state
            self.config.save()
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
        self.window.set_tray_task_state(status_text="空闲")
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
        if self.config.last_task_state:
            state = dict(self.config.last_task_state)
            state.update(
                {
                    "status": status,
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "posts": posts,
                    "downloaded": downloaded,
                    "skipped": skipped,
                }
            )
            self.config.last_task_state = state
            self.config.save()
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
                    "save_root": str(self.current_request.save_root),
                }
            )
        self._refresh_local_data()
        if self.current_open_after and self.current_request and not self._discard_current_task:
            self.open_specific_folder(str(self.current_request.save_root))
        if not self._discard_current_task:
            self.window.show_download_finished_actions(downloaded, skipped)
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
        self.window.set_tray_task_state(status_text="任务失败")
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
                    "save_root": str(self.current_request.save_root),
                }
            )
            self._refresh_local_data()
        if self.config.last_task_state:
            state = dict(self.config.last_task_state)
            state.update(
                {
                    "status": "失败",
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "error": message,
                }
            )
            self.config.last_task_state = state
            self.config.save()
        self._refresh_log_view()
        if not self._discard_current_task:
            self.window.show_error(f"任务失败：{message}")
        self._discard_current_task = False

    def save_settings(self, values: dict) -> None:
        old_credentials = (
            self.config.api_id,
            self.config.api_hash,
            self.config.session_name,
            self.config.session_dir,
            self.config.proxy_url,
            self.config.use_system_proxy,
        )
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
        self.config.chunk_concurrency = max(
            1,
            min(8, int(values.get("chunk_concurrency", self.config.chunk_concurrency))),
        )
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
        self.config.close_behavior = values.get("close_behavior", self.config.close_behavior)
        self.config.remember_close_behavior = bool(
            values.get("remember_close_behavior", self.config.remember_close_behavior)
        )
        self.config.use_dpapi_encryption = bool(values.get("use_dpapi_encryption", True))
        self.config.save_extended_info = bool(
            values.get("save_extended_info", self.config.save_extended_info)
        )
        self.config.use_system_proxy = bool(
            values.get("use_system_proxy", self.config.use_system_proxy)
        )
        self.config.proxy_url = values.get("proxy_url", self.config.proxy_url).strip()
        self.config.save()
        self.window.set_system_notifications_enabled(self.config.enable_system_notifications)
        self.window.set_close_behavior(
            self.config.close_behavior,
            self.config.remember_close_behavior,
        )
        if old_theme_mode != self.config.theme_mode:
            self._apply_theme()
        if old_lang != self.config.lang:
            self.window.apply_language(self.config.lang)
        self.window.set_task_defaults(
            self.config.save_root,
            SAVE_MODE_LABELS.get(self.config.save_mode, self.config.save_mode),
            self.config.save_mode,
            self.config.save_extended_info,
            self.config.open_after_download,
            self.config.duplicate_mode == "skip",
        )
        self.window.set_task_rule_summary(
            self.config.filename_template,
            self.config.preserve_original_name,
            self.config.duplicate_mode,
            self.config.open_after_download,
            self.config.concurrency,
            self.config.chunk_concurrency,
            self.config.file_download_interval,
            self.config.filename_limit,
            self.config.empty_tag_action,
        )
        self.window.set_summary(
            self.config.save_root,
            SAVE_MODE_LABELS.get(self.config.save_mode, self.config.save_mode),
        )
        self._refresh_account_sessions()
        self.window.show_success("设置已保存")
        new_credentials = (
            self.config.api_id,
            self.config.api_hash,
            self.config.session_name,
            self.config.session_dir,
            self.config.proxy_url,
            self.config.use_system_proxy,
        )
        if old_credentials != new_credentials:
            self._restart_worker()

    def save_close_behavior(self, behavior: str, remember: bool) -> None:
        if behavior not in {"ask", "minimize", "exit"}:
            return
        self.config.close_behavior = behavior
        self.config.remember_close_behavior = bool(remember)
        self.config.save()
        self.window.set_settings_defaults(self._settings_dict())

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
        self.open_specific_folder(self.config.save_root)

    def open_log(self) -> None:
        path = self.logger.get_log_path().resolve()
        path.touch(exist_ok=True)
        QDesktopServices.openUrl(path.as_uri())

    def open_log_folder(self) -> None:
        path = self.logger.log_dir.resolve()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(path.as_uri())

    def open_data_folder(self) -> None:
        path = self.config.config_dir.resolve()
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
                    str(item.get("save_root", "") or ""),
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
        if self.yande_worker and self.yande_worker.isRunning():
            self.yande_worker.cancel()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
        if (
            (self.worker and self.worker.isRunning())
            or (self.yande_worker and self.yande_worker.isRunning())
        ):
            QTimer.singleShot(50, self._poll_shutdown)
            return
        self._finish_shutdown()

    def _poll_shutdown(self) -> None:
        if (
            (self.worker and self.worker.isRunning())
            or (self.yande_worker and self.yande_worker.isRunning())
        ):
            QTimer.singleShot(50, self._poll_shutdown)
            return
        self._finish_shutdown()

    def cleanup_threads(self) -> None:
        """Synchronously stop background threads after the Qt loop exits."""
        if self.yande_worker and self.yande_worker.isRunning():
            self.yande_worker.cancel()
            self.yande_worker.wait(5000)
        self.yande_worker = None
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(10000)
        self.worker = None

    def _finish_shutdown(self) -> None:
        if self._shutdown_complete:
            return
        self._shutdown_complete = True
        self.yande_worker = None
        self.worker = None
        app = QApplication.instance()
        if app is not None:
            app.quit()
