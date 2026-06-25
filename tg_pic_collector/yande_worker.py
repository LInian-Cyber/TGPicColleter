from __future__ import annotations

import json
import re
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from PySide6.QtCore import QThread, Signal

from .igp import write_sidecar
from .logger import get_logger


YANDE_HOST = "https://yande.re"
USER_AGENT = "TG-Pic-Collector/1.0"
MIN_SEGMENT_SIZE = 512 * 1024
DEFAULT_DOWNLOAD_TIMEOUT = 25


def _safe_filename(name: str, fallback: str, limit: int = 180) -> str:
    raw = unquote(name or "").strip() or fallback
    raw = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw).strip(" .")
    path = Path(raw or fallback)
    suffix = path.suffix[:12] or ".jpg"
    stem = (path.stem or fallback)[: max(24, limit - len(suffix))].strip(" .")
    return f"{stem or fallback}{suffix}"


def _normalise_url(url: str) -> str:
    url = str(url or "").strip()
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"{YANDE_HOST}{url}"
    return url


def _tag_folder_name(tags: str) -> str:
    parts = [part.strip("# ") for part in re.split(r"[\s,]+", tags or "") if part.strip("# ")]
    if not parts:
        return "yande"
    return _safe_filename("_".join(parts[:6]), "yande", 100).removesuffix(".jpg")


def _post_id_from_text(text: str) -> int:
    match = re.search(r"(?:post/show/|/post\?tags=id%3A|id:)(\d+)", text or "")
    if match:
        return int(match.group(1))
    stripped = str(text or "").strip()
    return int(stripped) if stripped.isdigit() else 0


class YandeWorker(QThread):
    rows_ready = Signal(list)
    row_updated = Signal(int, str, str)
    progress = Signal(int, int, str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, params: dict, mode: str = "preview", parent=None):
        super().__init__(parent)
        self.params = dict(params)
        self.mode = mode
        self._cancelled = False
        self.logger = get_logger()

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            self.logger.info(
                f"===== Yande {'预览' if self.mode == 'preview' else '下载'}开始 ====="
            )
            self.logger.info(f"Yande Tags: {self.params.get('tags') or '全部'}")
            rows = self._collect_rows()
            self.logger.info(f"Yande 搜索命中: {len(rows)} 条")
            self.progress.emit(0, max(1, len(rows)), f"Yande 搜索命中 {len(rows)} 条")
            if self._cancelled:
                self.logger.info("Yande 任务已取消")
                self.finished.emit({"cancelled": True, "total": len(rows), "downloaded": 0, "skipped": 0})
                return
            self.rows_ready.emit(rows)
            if self.mode == "preview":
                self.logger.info(f"Yande 预览完成 - 结果: {len(rows)}")
                self.logger.info("===== Yande 预览结束 =====\n")
                self.finished.emit({"cancelled": False, "total": len(rows), "downloaded": 0, "skipped": 0})
                return
            self._download_rows(rows)
        except Exception as exc:
            self.logger.error(f"Yande 任务失败: {exc}")
            self.failed.emit(str(exc))

    def _collect_rows(self) -> list[dict]:
        cached_rows = self.params.get("rows")
        if self.mode == "download" and isinstance(cached_rows, list) and cached_rows:
            self.logger.info(f"Yande 使用当前预览结果: {len(cached_rows)} 条")
            return [dict(row) for row in cached_rows if isinstance(row, dict)]

        target = max(1, int(self.params.get("limit", 30) or 30))
        page = max(1, int(self.params.get("page", 1) or 1))
        scan_pages = max(1, int(self.params.get("scan_pages", 20) or 20))
        tags_text = str(self.params.get("tags", "") or "").strip()
        base_query = self._build_query(tags_text)
        self.logger.info(f"Yande 搜索条件: {base_query or '全部'}")
        rows: list[dict] = []
        seen: set[int] = set()

        for offset in range(scan_pages):
            if self._cancelled or len(rows) >= target:
                break
            posts = self._fetch_posts(base_query, page + offset, min(100, max(target, 20)))
            if not posts:
                break
            for post in posts:
                if self._cancelled or len(rows) >= target:
                    break
                row = self._post_to_row(post, relation="主图")
                if not row or row["id"] in seen or not self._matches_filters(row):
                    continue
                seen.add(row["id"])
                rows.append(row)
            if len(posts) < min(100, max(target, 20)):
                break

        if self.params.get("include_children", True):
            for parent in list(rows):
                if self._cancelled:
                    break
                child_query = f"{self._rating_query()} parent:{parent['id']}".strip()
                for post in self._fetch_posts(child_query, 1, 100):
                    row = self._post_to_row(post, relation=f"子图 #{parent['id']}")
                    if not row or row["id"] in seen or not self._matches_filters(row):
                        continue
                    seen.add(row["id"])
                    rows.append(row)

        return rows

    def _build_query(self, text: str) -> str:
        post_id = _post_id_from_text(text)
        if post_id:
            return f"id:{post_id}"
        terms = [term.strip("# ") for term in re.split(r"[\s,]+", text) if term.strip("# ")]
        rating = self._rating_query()
        has_rating_term = any(term.casefold().startswith("rating:") for term in terms)
        return " ".join([*terms, rating if rating and not has_rating_term else ""]).strip()

    def _rating_query(self) -> str:
        return {
            "safe": "rating:s",
            "questionable": "rating:q",
            "explicit": "rating:e",
        }.get(str(self.params.get("rating", "all")), "")

    def _fetch_posts(self, tags: str, page: int, limit: int) -> list[dict]:
        query = f"limit={limit}&page={page}"
        if tags:
            query += f"&tags={quote_plus(tags)}"
        url = f"{YANDE_HOST}/post.json?{query}"
        self.logger.debug(f"Yande 请求: {url}")
        payload = self._get_bytes(url)
        data = json.loads(payload.decode("utf-8", errors="replace"))
        return data if isinstance(data, list) else []

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Referer": f"{YANDE_HOST}/post",
            "Accept-Encoding": "identity",
            "Connection": "close",
        }
        cookie = str(self.params.get("cookie", "") or "").strip()
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _get_bytes(self, url: str, timeout: int = 35) -> bytes:
        try:
            with self._open_url(Request(url, headers=self._headers()), timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            hint = "。如果正在访问 E 级内容，请确认已填写有效的 Yande 登录态 Cookie"
            raise RuntimeError(f"请求失败 HTTP {exc.code}: {url}{hint}") from exc
        except URLError as exc:
            raise RuntimeError(
                f"网络请求失败：{url}（{self._format_network_error(exc)}）"
            ) from exc

    def _open_url(self, request: Request, timeout: int):
        url = getattr(request, "full_url", str(request))
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                if attempt == 3 and self._looks_like_cert_path_error(last_error):
                    self.logger.warning(
                        f"Yande SSL/证书路径异常，使用兼容模式重试: {url}"
                    )
                    return urlopen(
                        request,
                        timeout=timeout,
                        context=ssl._create_unverified_context(),
                    )
                return urlopen(request, timeout=timeout)
            except HTTPError:
                raise
            except (URLError, OSError) as exc:
                last_error = exc
                if attempt < 3:
                    self.logger.warning(
                        f"Yande 网络请求重试 {attempt}/3: {url} "
                        f"({self._format_network_error(exc)})"
                    )
                    time.sleep(0.35 * attempt)
                    continue
                if isinstance(exc, URLError):
                    raise
                raise URLError(exc) from exc
        raise URLError(last_error)

    @staticmethod
    def _format_network_error(exc: Exception) -> str:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, FileNotFoundError):
            return (
                f"{reason}。这通常是本机 SSL 证书文件、代理配置文件或打包后的证书路径不可用"
            )
        return str(reason or exc)

    @staticmethod
    def _looks_like_cert_path_error(exc: Exception | None) -> bool:
        reason = getattr(exc, "reason", exc)
        return isinstance(reason, FileNotFoundError)

    def _post_to_row(self, post: dict, relation: str) -> dict | None:
        post_id = int(post.get("id") or 0)
        image_url = self._select_image_url(post)
        if post_id <= 0 or not image_url:
            return None
        width = int(post.get("width") or post.get("jpeg_width") or 0)
        height = int(post.get("height") or post.get("jpeg_height") or 0)
        tags = str(post.get("tags", "") or "")
        created_ts = int(post.get("created_at") or 0)
        filename = _safe_filename(
            Path(urlparse(image_url).path).name,
            f"yande.re_{post_id}.jpg",
        )
        return {
            "id": post_id,
            "relation": relation,
            "rating": str(post.get("rating", "") or "-"),
            "score": int(post.get("score") or 0),
            "size": f"{width}x{height}" if width and height else "-",
            "tags": tags,
            "tag_list": tags.split(),
            "source": str(post.get("source", "") or ""),
            "post_url": f"{YANDE_HOST}/post/show/{post_id}",
            "image_url": image_url,
            "filename": filename,
            "created_at": datetime.fromtimestamp(created_ts).isoformat(timespec="seconds") if created_ts else "",
            "created_ts": created_ts,
            "status": "待下载" if self.mode == "download" else "已预览",
            "local_path": "",
        }

    def _select_image_url(self, post: dict) -> str:
        source = str(self.params.get("image_source", "file"))
        keys = {
            "file": ("file_url", "jpeg_url", "sample_url"),
            "jpeg": ("jpeg_url", "file_url", "sample_url"),
            "sample": ("sample_url", "jpeg_url", "file_url"),
        }.get(source, ("file_url", "jpeg_url", "sample_url"))
        for key in keys:
            url = _normalise_url(str(post.get(key, "") or ""))
            if url:
                return url
        return ""

    def _matches_filters(self, row: dict) -> bool:
        min_score = int(self.params.get("min_score", 0) or 0)
        if min_score and int(row.get("score", 0)) < min_score:
            return False
        created_ts = int(row.get("created_ts", 0) or 0)
        if not created_ts:
            return True
        created_date = datetime.fromtimestamp(created_ts).date()
        date_from = str(self.params.get("date_from", "") or "")
        date_to = str(self.params.get("date_to", "") or "")
        if date_from and created_date < datetime.fromisoformat(date_from).date():
            return False
        if date_to and created_date > datetime.fromisoformat(date_to).date():
            return False
        return True

    def _download_rows(self, rows: list[dict]) -> None:
        save_root = Path(str(self.params.get("save_root", "") or "")).expanduser()
        if not save_root:
            raise RuntimeError("请先设置保存目录")
        target_dir = save_root / _tag_folder_name(str(self.params.get("tags", ""))) \
            if self.params.get("save_mode", "tag_folder") == "tag_folder" else save_root
        target_dir.mkdir(parents=True, exist_ok=True)
        chunk_threads = max(1, int(self.params.get("chunk_threads", 8) or 8))
        file_concurrency = max(1, min(int(self.params.get("file_concurrency", 3) or 3), 8))
        download_timeout = max(8, int(self.params.get("download_timeout", DEFAULT_DOWNLOAD_TIMEOUT) or DEFAULT_DOWNLOAD_TIMEOUT))
        self.logger.info(f"Yande 保存目录: {target_dir}")
        self.logger.info(f"Yande 同时下载文件数: {file_concurrency}")
        self.logger.info(f"Yande 单文件分片数: {chunk_threads}")
        self.logger.info(f"Yande 单连接超时: {download_timeout} 秒")

        downloaded = skipped = failed = 0
        progress_lock = threading.Lock()
        reserved: set[str] = set()
        jobs: list[tuple[int, dict, Path]] = []

        for index, row in enumerate(rows):
            if self._cancelled:
                break
            existing = self._existing_file(target_dir, int(row["id"])) if self.params.get("skip_existing", True) else None
            if existing:
                skipped += 1
                self.logger.file_skipped(int(row["id"]), str(existing), "本地已存在")
                self.row_updated.emit(index, "已跳过", str(existing))
                self.progress.emit(downloaded + skipped + failed, len(rows), f"已存在：{existing.name}")
                continue
            target = self._available_path(target_dir / row["filename"], reserved)
            reserved.add(str(target.resolve()).casefold())
            jobs.append((index, row, target))

        def complete(status: str, index: int, row: dict, target: Path, message: str) -> None:
            nonlocal downloaded, skipped, failed
            with progress_lock:
                if status == "downloaded":
                    downloaded += 1
                    self.logger.file_downloaded(int(row["id"]), str(target))
                    self.row_updated.emit(index, "已下载", str(target))
                    detail = f"已下载：{target.name}"
                elif status == "failed":
                    failed += 1
                    self.logger.error(f"Yande 下载失败 - Post #{row['id']}: {target} ({message})")
                    self.row_updated.emit(index, "失败", message)
                    detail = f"失败：#{row['id']} {message}"
                else:
                    detail = message
                self.progress.emit(downloaded + skipped + failed, len(rows), detail)

        def download_job(index: int, row: dict, target: Path) -> tuple[str, int, dict, Path, str]:
            if self._cancelled:
                return "cancelled", index, row, target, "已取消"
            self.logger.info(f"Yande 开始下载 - Post #{row['id']}: {row['image_url']}")
            self.row_updated.emit(index, "下载中", str(target))
            self.progress.emit(downloaded + skipped + failed, len(rows), f"正在下载：{target.name}")
            if not self._download_file(
                row["image_url"],
                target,
                chunk_threads=chunk_threads,
                timeout=download_timeout,
            ):
                return "cancelled", index, row, target, "已取消"
            self._write_sidecars(target, row)
            interval = max(0.0, float(self.params.get("interval", 0.3) or 0.0))
            if interval and not self._cancelled:
                time.sleep(interval)
            return "downloaded", index, row, target, str(target)

        if jobs and not self._cancelled:
            with ThreadPoolExecutor(max_workers=min(file_concurrency, len(jobs))) as executor:
                futures = {
                    executor.submit(download_job, index, row, target): (index, row, target)
                    for index, row, target in jobs
                }
                for future in as_completed(futures):
                    index, row, target = futures[future]
                    if self._cancelled:
                        for pending in futures:
                            pending.cancel()
                        break
                    try:
                        status, index, row, target, message = future.result()
                    except Exception as exc:
                        complete("failed", index, row, target, str(exc))
                        continue
                    if status == "downloaded":
                        complete("downloaded", index, row, target, message)
                    elif status == "failed":
                        complete("failed", index, row, target, message)

        if failed:
            self.logger.warning(f"Yande 下载存在失败文件: {failed}")
        self.logger.info(
            f"Yande 下载完成 - 匹配帖子: {len(rows)}, 下载: {downloaded}, 跳过: {skipped}, 失败: {failed}"
        )
        self.logger.info("===== Yande 下载结束 =====\n")
        self.finished.emit({
            "cancelled": self._cancelled,
            "total": len(rows),
            "downloaded": downloaded,
            "skipped": skipped,
            "failed": failed,
            "save_root": str(target_dir),
        })

    def _download_file(
        self,
        url: str,
        target: Path,
        chunk_threads: int = 1,
        timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
    ) -> bool:
        if chunk_threads > 1:
            try:
                return self._download_file_segmented(url, target, chunk_threads, timeout=timeout)
            except Exception as exc:
                self.logger.warning(f"Yande 分片下载失败，退回普通下载: {target.name} ({exc})")
                target.with_suffix(target.suffix + ".part").unlink(missing_ok=True)
                for part in target.parent.glob(f"{target.name}.part.*"):
                    part.unlink(missing_ok=True)

        tmp = target.with_suffix(target.suffix + ".part")
        try:
            with self._open_url(Request(url, headers=self._headers()), timeout=timeout) as response, tmp.open("wb") as fh:
                while True:
                    if self._cancelled:
                        break
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    fh.write(chunk)
        except HTTPError as exc:
            raise RuntimeError(f"下载失败 HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            raise RuntimeError(f"下载失败：{exc.reason}") from exc
        if self._cancelled:
            tmp.unlink(missing_ok=True)
            return False
        tmp.replace(target)
        return True

    def _download_file_segmented(
        self,
        url: str,
        target: Path,
        chunk_threads: int,
        timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
    ) -> bool:
        file_size = self._remote_file_size(url)
        if file_size <= MIN_SEGMENT_SIZE * 2:
            self.logger.debug(f"Yande 文件较小，使用普通下载: {target.name} ({file_size} bytes)")
            return self._download_file(url, target, chunk_threads=1, timeout=timeout)

        workers = max(2, min(int(chunk_threads), 32))
        chunk_size = max(MIN_SEGMENT_SIZE, (file_size + workers - 1) // workers)
        ranges: list[tuple[int, int, Path]] = []
        offset = 0
        index = 0
        while offset < file_size:
            end = min(file_size - 1, offset + chunk_size - 1)
            ranges.append((offset, end, target.with_name(f"{target.name}.part.{index}")))
            offset = end + 1
            index += 1

        self.logger.info(
            f"Yande 分片下载 - {target.name}: {file_size} bytes, {len(ranges)} 片, {workers} 线程"
        )
        try:
            with ThreadPoolExecutor(max_workers=min(workers, len(ranges))) as executor:
                futures = [
                    executor.submit(self._fetch_range_to_file, url, start, end, part, timeout)
                    for start, end, part in ranges
                ]
                for future in as_completed(futures):
                    if self._cancelled:
                        break
                    future.result()
            if self._cancelled:
                return False

            tmp = target.with_suffix(target.suffix + ".part")
            with tmp.open("wb") as out:
                for _, _, part in ranges:
                    with part.open("rb") as fh:
                        while True:
                            data = fh.read(1024 * 512)
                            if not data:
                                break
                            out.write(data)
            if tmp.stat().st_size != file_size:
                raise RuntimeError(f"分片合并大小不一致: {tmp.stat().st_size} != {file_size}")
            tmp.replace(target)
            return True
        finally:
            for _, _, part in ranges:
                part.unlink(missing_ok=True)
            if self._cancelled:
                target.with_suffix(target.suffix + ".part").unlink(missing_ok=True)

    def _remote_file_size(self, url: str) -> int:
        try:
            request = Request(url, headers=self._headers(), method="HEAD")
            with self._open_url(request, timeout=30) as response:
                length = response.headers.get("Content-Length")
                if length and length.isdigit():
                    return int(length)
        except Exception:
            pass

        request = Request(url, headers={**self._headers(), "Range": "bytes=0-0"})
        try:
            with self._open_url(request, timeout=30) as response:
                content_range = response.headers.get("Content-Range", "")
                match = re.search(r"/(\d+)$", content_range)
                if match:
                    return int(match.group(1))
                length = response.headers.get("Content-Length")
                if length and length.isdigit():
                    return int(length)
        except Exception as exc:
            raise RuntimeError(f"无法获取远程文件大小: {exc}") from exc
        raise RuntimeError("服务器未返回文件大小，无法启用分片")

    def _fetch_range_to_file(
        self,
        url: str,
        start: int,
        end: int,
        path: Path,
        timeout: int = DEFAULT_DOWNLOAD_TIMEOUT,
    ) -> None:
        if self._cancelled:
            return
        headers = {**self._headers(), "Range": f"bytes={start}-{end}"}
        expected_size = end - start + 1
        last_error: Exception | None = None
        for attempt in range(1, 5):
            if self._cancelled:
                return
            path.unlink(missing_ok=True)
            try:
                with self._open_url(Request(url, headers=headers), timeout=timeout) as response, path.open("wb") as fh:
                    if response.getcode() != 206:
                        raise RuntimeError(f"服务器未按 Range 返回数据: HTTP {response.getcode()}")
                    while True:
                        if self._cancelled:
                            return
                        chunk = response.read(1024 * 256)
                        if not chunk:
                            break
                        fh.write(chunk)
                actual_size = path.stat().st_size if path.exists() else 0
                if actual_size == expected_size:
                    return
                raise RuntimeError(
                    f"分片大小不一致: bytes={start}-{end}, {actual_size} != {expected_size}"
                )
            except HTTPError as exc:
                last_error = RuntimeError(f"分片下载失败 HTTP {exc.code}: bytes={start}-{end}")
            except URLError as exc:
                last_error = RuntimeError(f"分片下载失败：{exc.reason}")
            except OSError as exc:
                last_error = RuntimeError(f"分片写入失败：{exc}")
            except RuntimeError as exc:
                last_error = exc

            if attempt < 4:
                self.logger.warning(
                    f"Yande 分片重试 {attempt}/4: bytes={start}-{end} ({last_error})"
                )
                time.sleep(0.25 * attempt)

        path.unlink(missing_ok=True)
        raise RuntimeError(str(last_error or f"分片下载失败: bytes={start}-{end}"))

    def _existing_file(self, folder: Path, post_id: int) -> Path | None:
        for path in folder.glob(f"*{post_id}*"):
            if path.is_file() and not path.name.endswith((".json", ".txt", ".part")):
                return path
        return None

    def _available_path(self, path: Path, reserved: set[str] | None = None) -> Path:
        reserved = reserved or set()

        def is_available(candidate: Path) -> bool:
            return not candidate.exists() and str(candidate.resolve()).casefold() not in reserved

        if is_available(path):
            return path
        for index in range(2, 10000):
            candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
            if is_available(candidate):
                return candidate
        return path.with_name(f"{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix}")

    def _write_sidecars(self, target: Path, row: dict) -> None:
        if not self.params.get("save_extended_info", True):
            return
        write_sidecar(
            target,
            {
                "tags": [
                    {"name": str(tag), "source": "yande", "confidence": 1.0}
                    for tag in row.get("tag_list", [])
                    if str(tag).strip()
                ],
                "yande": {
                    "post_id": row["id"],
                    "post_url": row["post_url"],
                    "download_url": row["image_url"],
                    "source": row["source"],
                    "rating": row["rating"],
                    "score": row["score"],
                    "size": row["size"],
                    "relation": row["relation"],
                    "created_at": row.get("created_at", ""),
                },
                "download": {
                    "service": "yande.re",
                    "filename": target.name,
                    "directory": str(target.parent),
                    "downloaded_at": datetime.now().isoformat(timespec="seconds"),
                },
            },
        )
