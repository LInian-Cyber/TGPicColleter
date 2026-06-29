from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QThread, Signal

from .network import run_network_diagnostics
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


class YandeControllerMixin:
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
        self.yande_worker.finished.connect(
            lambda summary: self._on_yande_finished(summary, "preview", params)
        )
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
        self.yande_worker.finished.connect(
            lambda summary: self._on_yande_finished(summary, "download", params)
        )
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
        self.config.save_root = str(
            params.get("save_root", self.config.save_root) or self.config.save_root
        )
        current_cookie = str(params.get("cookie", "") or "").strip()
        if bool(params.get("remember_cookie")):
            self.config.yande_cookie = current_cookie
        if tags:
            self.config.add_yande_tag_history(tags)
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
            self.window.set_yande_progress(
                total,
                max(1, total),
                f"预览完成：找到 {total} 条。",
            )
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
                "save_root": summary.get(
                    "save_root",
                    params.get("save_root", self.config.save_root),
                ),
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
