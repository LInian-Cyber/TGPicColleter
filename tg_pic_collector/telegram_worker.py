from __future__ import annotations

import asyncio
import json
import mimetypes
import queue
import re
import threading
import time
from contextlib import suppress
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal
from telethon import TelegramClient, errors, types

from .logger import get_logger
from .igp import write_sidecar
from .models import (
    PreviewRequest,
    ScanRequest,
    TelegramCredentials,
    normalize_channel_reference,
)
from .network import proxy_label, telethon_proxy


PreviewCacheKey = tuple[str, str, str, str]
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}

try:
    from .crypto import decrypt_session, encrypt_session
except ImportError:
    def decrypt_session(path: Path) -> bool:
        return False


    def encrypt_session(path: Path, use_encryption: bool = True) -> bool:
        return False

try:
    from .tg_extractor import run_advanced_telethon_task as _run_advanced

    _HAS_EXTRACTOR = True
except ImportError:
    _HAS_EXTRACTOR = False


def safe_name(value: str, fallback: str = "untitled", max_length: int = 90) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    value = value[:max_length].rstrip(" .")
    if not value:
        return fallback
    if value.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        value = f"_{value}"
    return value[:max_length].rstrip(" .") or fallback


def is_webpage_preview(message: Any) -> bool:
    """Return True for Telegram-generated link preview media."""
    media = getattr(message, "media", None)
    return bool(media and getattr(media, "webpage", None) is not None)


def message_document(message: Any) -> Any | None:
    media = getattr(message, "media", None)
    return getattr(media, "document", None) or getattr(message, "document", None)


def is_sticker_message(message: Any) -> bool:
    document = message_document(message)
    if not document:
        return False
    mime_type = str(getattr(document, "mime_type", "") or "").casefold()
    attributes = getattr(document, "attributes", []) or []
    attr_names = {type(attr).__name__ for attr in attributes}
    if "DocumentAttributeSticker" in attr_names:
        return True
    if mime_type == "application/x-tgsticker":
        return True
    # Video stickers are usually webm documents with the animated flag.
    return mime_type == "video/webm" and "DocumentAttributeAnimated" in attr_names


def real_media_kind(message: Any) -> str | None:
    """Identify only media actually uploaded to the Telegram message."""
    media = getattr(message, "media", None)
    if isinstance(media, types.MessageMediaPhoto) and getattr(media, "photo", None):
        return "photo"
    if isinstance(media, types.MessageMediaDocument) and getattr(media, "document", None):
        return "document"
    if getattr(message, "photo", None):
        return "photo"
    if getattr(message, "document", None):
        return "document"
    return None


def is_image_message(message: Any) -> bool:
    """检查消息是否为图片（排除贴纸）"""
    if is_sticker_message(message):
        return False
    media_kind = real_media_kind(message)
    if media_kind is None:
        return False
    if media_kind == "photo":
        return True
    document = message_document(message)
    if not document:
        return False

    mime_type = str(getattr(document, "mime_type", "") or "")

    return mime_type.startswith("image/")


def is_downloadable_message(message: Any) -> bool:
    return real_media_kind(message) is not None and not is_sticker_message(message)


async def resolve_channel_entity(
    client: TelegramClient, value: str
) -> tuple[str, Any]:
    """Resolve a channel reference, refreshing dialogs for uncached private channels."""
    channel_ref = normalize_channel_reference(value)
    entity_ref: str | int = (
        int(channel_ref) if channel_ref.lstrip("-").isdigit() else channel_ref
    )
    try:
        return channel_ref, await client.get_entity(entity_ref)
    except ValueError as exc:
        if not (isinstance(entity_ref, int) and channel_ref.startswith("-100")):
            raise
        await client.get_dialogs()
        try:
            return channel_ref, await client.get_entity(entity_ref)
        except ValueError as retry_exc:
            raise ValueError(
                "无法访问该私密频道，请确认当前登录账号已加入，并在 Telegram 中打开过该频道。"
            ) from retry_exc


class TelegramWorker(QThread):
    status_changed = Signal(str)
    ready = Signal(bool)
    authorized = Signal(str, str)
    code_sent = Signal(str)
    qr_ready = Signal(str)
    password_required = Signal()
    auth_failed = Signal(str)
    connection_failed = Signal(str)
    logged_out = Signal()
    scan_started = Signal()
    scan_plan_ready = Signal(int, int)  # matched posts, downloadable files
    scan_discovery_finished = Signal(int, int)  # matched posts, discovered files
    scan_progress = Signal(int, int, str)
    scan_metrics_changed = Signal(dict)
    post_status_changed = Signal(int, str)
    scan_finished = Signal(int, int, int)
    scan_failed = Signal(str)
    preview_started = Signal()
    preview_progress = Signal(str)
    preview_finished = Signal(list, int, int)  # displayed rows, total matches, display limit
    preview_failed = Signal(str)
    user_profile_updated = Signal(str, str, bytes)  # name, phone, avatar_bytes
    channel_info_fetched = Signal(str, str, bytes)  # channel_id, channel_name, avatar_bytes
    dialogs_loaded = Signal(list)  # 对话列表加载完成

    def __init__(self, credentials: TelegramCredentials, parent=None, use_encryption: bool = True) -> None:
        super().__init__(parent)
        self.credentials = credentials
        self.use_encryption = use_encryption
        self.commands: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.pause_event = threading.Event()   # set = 正在运行，clear = 暂停中
        self.pause_event.set()                  # 默认运行状态
        self.preview_cancel_event = threading.Event()
        self.qr_cancel_event = threading.Event()
        self._stopping = threading.Event()
        self.logger = get_logger()
        self._phone_code_hash: str | None = None
        self._phone = credentials.phone
        self._client: TelegramClient | None = None
        # 搜索预览缓存：UI 摘要之外还保留帖子和媒体消息，下载时无需再次扫描。
        self._preview_cache: dict[PreviewCacheKey, list[dict]] = {}
        # 仅完整扫描过对应数量的预览缓存，才允许正式下载复用。
        self._preview_cache_limits: dict[PreviewCacheKey, int] = {}
        self._preview_cache_totals: dict[PreviewCacheKey, int] = {}
        self._preview_cache_requests: dict[PreviewCacheKey, tuple[Any, ...]] = {}
        self._downloaded_media_keys: set[str] = set()
        self._downloaded_media_paths: dict[str, str] = {}
        self._downloaded_media_index_path: Path | None = None
        self._thumbnail_cache: dict[str, tuple[float, bytes]] = {}
        self._thumbnail_cache_ttl = 24 * 60 * 60
        self._scan_retry_attempts: dict[tuple[str, str, str], int] = {}

    def _put_command(
        self,
        command: str,
        payload: Any = None,
        *,
        allow_while_stopping: bool = False,
    ) -> None:
        if self._stopping.is_set() and not allow_while_stopping:
            return
        self.commands.put((command, payload))

    def load_dialogs(self) -> None:
        """加载用户的对话列表（频道、群组等）"""
        self._put_command("load_dialogs")

    def request_code(self, phone: str) -> None:
        if self._stopping.is_set():
            return
        self.qr_cancel_event.set()
        self._put_command("request_code", phone)

    def sign_in(self, phone: str, code: str, password: str = "") -> None:
        if self._stopping.is_set():
            return
        self.qr_cancel_event.set()
        self._put_command("sign_in", (phone, code, password))

    def start_qr_login(self) -> None:
        if self._stopping.is_set():
            return
        self.cancel_event.clear()
        self.qr_cancel_event.set()
        self._put_command("qr_login")

    def log_out(self) -> None:
        self._put_command("logout")

    def start_scan(self, request: ScanRequest) -> None:
        if self._stopping.is_set():
            return
        self.cancel_event.clear()
        self._put_command("scan", request)

    def cancel_scan(self) -> None:
        self.cancel_event.set()
        self.pause_event.set()  # 取消时确保解除暂停，避免协程永远挂起

    def pause_scan(self) -> None:
        """暂停当前下载（_scan 会在每个 post 前检查）"""
        self.pause_event.clear()

    def resume_scan(self) -> None:
        """继续被暂停的下载"""
        self.pause_event.set()

    def start_preview(self, request: PreviewRequest) -> None:
        if self._stopping.is_set():
            return
        self.preview_cancel_event.clear()
        self._put_command("preview", request)

    def cancel_preview(self) -> None:
        self.preview_cancel_event.set()

    def stop(self) -> None:
        self._stopping.set()
        self.cancel_event.set()
        self.preview_cancel_event.set()
        self.qr_cancel_event.set()
        self.pause_event.set()
        self._put_command("stop", allow_while_stopping=True)

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._main())
        except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
            message = str(exc) or exc.__class__.__name__
            self.status_changed.emit(f"连接失败：{message}")
            self.connection_failed.emit(message)
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            self.status_changed.emit(f"连接失败：{message}")
            self.connection_failed.emit(message)
        finally:
            self._shutdown_event_loop(loop)
            asyncio.set_event_loop(None)
            loop.close()

    @staticmethod
    def _shutdown_event_loop(loop: asyncio.AbstractEventLoop) -> None:
        for _ in range(6):
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            if not pending:
                break
            for task in pending:
                task.cancel()
            done, _ = loop.run_until_complete(asyncio.wait(pending, timeout=2))
            for task in done:
                with suppress(asyncio.CancelledError, Exception):
                    task.result()
            loop.run_until_complete(asyncio.sleep(0.05))
        with suppress(Exception):
            loop.run_until_complete(loop.shutdown_asyncgens())
        shutdown_executor = getattr(loop, "shutdown_default_executor", None)
        if callable(shutdown_executor):
            with suppress(Exception):
                loop.run_until_complete(shutdown_executor())

    @staticmethod
    async def _disconnect_client(client: TelegramClient) -> None:
        try:
            await asyncio.wait_for(client.disconnect(), timeout=8)
            disconnected = getattr(client, "disconnected", None)
            if disconnected is not None and not disconnected.done():
                with suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(disconnected, timeout=2)
        except asyncio.TimeoutError:
            pass
        finally:
            for _ in range(8):
                await asyncio.sleep(0.05)

    async def _next_command(self) -> tuple[str, Any]:
        while True:
            if self._stopping.is_set():
                while True:
                    try:
                        command, payload = self.commands.get_nowait()
                    except queue.Empty:
                        return "stop", None
                    if command == "stop":
                        return command, payload
            try:
                return self.commands.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)

    async def _main(self) -> None:
        self.credentials.session_path.parent.mkdir(parents=True, exist_ok=True)

        # 连接前先尝试解密 session
        decrypt_session(self.credentials.session_path)

        try:
            proxy = telethon_proxy(
                self.credentials.proxy_url,
                self.credentials.use_system_proxy,
            )
            proxy_text = proxy_label(
                self.credentials.proxy_url,
                self.credentials.use_system_proxy,
            )
        except (RuntimeError, ValueError) as exc:
            raise ConnectionError(str(exc)) from exc

        client = TelegramClient(
            str(self.credentials.session_path),
            self.credentials.api_id,
            self.credentials.api_hash,
            proxy=proxy,
            timeout=10,
            connection_retries=2,
            retry_delay=1,
        )
        self._client = client
        self.status_changed.emit(
            "正在连接 Telegram…" if proxy is None else f"正在通过代理连接 Telegram：{proxy_text}"
        )
        try:
            await asyncio.wait_for(client.connect(), timeout=25)
        except asyncio.TimeoutError as exc:
            await self._disconnect_client(client)
            raise ConnectionError("连接 Telegram 超时，请检查网络或代理设置") from exc
        except Exception:
            await self._disconnect_client(client)
            raise
        if not client.is_connected():
            await self._disconnect_client(client)
            raise ConnectionError("无法连接 Telegram，请检查网络或代理设置")
        try:
            try:
                authorized = await asyncio.wait_for(client.is_user_authorized(), timeout=15)
            except asyncio.TimeoutError as exc:
                raise ConnectionError("检查 Telegram 会话超时，请稍后重试") from exc
            self.ready.emit(authorized)
            if authorized:
                await self._emit_identity(client)
            else:
                self.status_changed.emit("未登录")

            while True:
                command, payload = await self._next_command()
                if command == "stop":
                    break
                if command == "request_code":
                    await self._request_code(client, payload)
                elif command == "sign_in":
                    await self._sign_in(client, *payload)
                elif command == "qr_login":
                    if await client.is_user_authorized():
                        await self._emit_identity(client)
                    else:
                        await self._qr_login(client)
                elif command == "logout":
                    await client.log_out()
                    self.logged_out.emit()
                    self.status_changed.emit("已退出登录")
                    break
                elif command == "scan":
                    if await client.is_user_authorized():
                        await self._scan(client, payload)
                    else:
                        self.scan_failed.emit("请先登录 Telegram")
                elif command == "preview":
                    if await client.is_user_authorized():
                        await self._preview(client, payload)
                    else:
                        self.preview_failed.emit("请先登录 Telegram")
                elif command == "load_dialogs":
                    if await client.is_user_authorized():
                        await self._load_dialogs(client)
                    else:
                        self.dialogs_loaded.emit([])
        finally:
            await self._disconnect_client(client)
            self._client = None
            # 断开后加密 session
            if self.use_encryption:
                encrypt_session(self.credentials.session_path, self.use_encryption)

    async def _request_code(self, client: TelegramClient, phone: str) -> None:
        try:
            self._phone = phone.strip()
            sent = await client.send_code_request(self._phone)
            self._phone_code_hash = sent.phone_code_hash
            self.code_sent.emit(self._phone)
            self.status_changed.emit("验证码已发送")
        except Exception as exc:
            self.auth_failed.emit(f"发送验证码失败：{exc}")

    async def _sign_in(
            self, client: TelegramClient, phone: str, code: str, password: str
    ) -> None:
        try:
            if password and not code:
                await client.sign_in(password=password)
            else:
                await client.sign_in(
                    phone=phone.strip(),
                    code=code.strip(),
                    phone_code_hash=self._phone_code_hash,
                )
            await self._emit_identity(client)
        except errors.SessionPasswordNeededError:
            if password:
                try:
                    await client.sign_in(password=password)
                    await self._emit_identity(client)
                except errors.PasswordHashInvalidError:
                    self.auth_failed.emit("两步验证密码错误")
            else:
                self.password_required.emit()
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError):
            self.auth_failed.emit("验证码无效或已过期")
        except Exception as exc:
            self.auth_failed.emit(f"登录失败：{exc}")

    async def _qr_login(self, client: TelegramClient) -> None:
        try:
            self.qr_cancel_event.clear()
            qr_login = await client.qr_login()
            self.qr_ready.emit(qr_login.url)
            self.status_changed.emit("等待扫码确认")
            wait_task = asyncio.create_task(qr_login.wait(timeout=120))
            while not wait_task.done():
                if self.cancel_event.is_set() or self.qr_cancel_event.is_set():
                    wait_task.cancel()
                    await asyncio.gather(wait_task, return_exceptions=True)
                    return
                await asyncio.sleep(0.2)
            await wait_task
            await self._emit_identity(client)
        except asyncio.CancelledError:
            return
        except asyncio.TimeoutError:
            self.auth_failed.emit("二维码已过期，请刷新后重试")
        except errors.SessionPasswordNeededError:
            self.password_required.emit()
        except Exception as exc:
            self.auth_failed.emit(f"扫码登录失败：{exc}")

    async def _emit_identity(self, client: TelegramClient) -> None:
        me = await client.get_me()
        display_name = " ".join(filter(None, [me.first_name, me.last_name])).strip()
        phone = f"+{me.phone}" if getattr(me, "phone", None) else self._phone
        self.authorized.emit(display_name or me.username or phone or "Telegram 用户", phone or "")
        self.status_changed.emit("会话有效")

        # 获取用户头像
        try:
            avatar_bytes = await asyncio.wait_for(
                client.download_profile_photo(me, file=bytes),
                timeout=8,
            )
            if isinstance(avatar_bytes, bytes):
                self.user_profile_updated.emit(
                    display_name or me.username or phone or "Telegram 用户",
                    phone or "",
                    avatar_bytes
                )
        except Exception:
            # 如果没有头像或下载失败，发送空字节
            self.user_profile_updated.emit(
                display_name or me.username or phone or "Telegram 用户",
                phone or "",
                b""
            )

    async def _load_dialogs(self, client: TelegramClient) -> None:
        """加载用户的对话列表（频道、群组等）"""
        try:
            self.status_changed.emit("正在加载频道列表…")
            dialogs = []
            async for dialog in client.iter_dialogs(limit=100):
                entity = dialog.entity

                # 只选择频道和超级群组
                if hasattr(entity, 'broadcast') and entity.broadcast:  # 频道
                    entity_type = "channel"
                elif hasattr(entity, 'megagroup') and entity.megagroup:  # 超级群组
                    entity_type = "supergroup"
                elif hasattr(entity, 'username') and entity.username:  # 有用户名的群组/频道
                    entity_type = "public"
                else:
                    continue  # 跳过普通用户和私聊群组

                # 获取名称和ID
                name = getattr(entity, 'title', '') or getattr(entity, 'username', '')
                username = getattr(entity, 'username', '')
                entity_id = getattr(entity, 'id', '')

                if not name:
                    continue

                # 构建显示ID
                if username:
                    display_id = f"@{username}"
                else:
                    display_id = f"-100{entity_id}" if entity_id else ""

                if not display_id:
                    continue

                dialogs.append({
                    "name": name,
                    "id": display_id,
                    "link": f"https://t.me/{username}" if username else (
                        f"https://t.me/c/{str(display_id)[4:]}"
                        if str(display_id).startswith("-100")
                        else display_id
                    ),
                    "avatar": b"",
                    "_entity": entity,
                    "type": entity_type
                })

            # UI 最多展示 20 个频道。头像并发加载并设置超时，避免阻塞后续任务。
            dialogs.sort(key=lambda x: x["name"].lower())
            dialogs = dialogs[:20]

            async def load_avatar(item: dict) -> None:
                try:
                    avatar_data = await asyncio.wait_for(
                        client.download_profile_photo(item["_entity"], file=bytes),
                        timeout=4,
                    )
                    if isinstance(avatar_data, bytes):
                        item["avatar"] = avatar_data
                except Exception:
                    pass
                item.pop("_entity", None)

            await asyncio.gather(*(load_avatar(item) for item in dialogs))
            self.dialogs_loaded.emit(dialogs)
            self.status_changed.emit("会话有效")

        except Exception:
            self.dialogs_loaded.emit([])
            self.status_changed.emit("会话有效")

    async def _emit_channel_info(self, client: TelegramClient, entity: Any, fallback_ref: str) -> None:
        """Fetch and emit channel display metadata for the local channel cache."""
        username = str(getattr(entity, "username", "") or "").strip()
        entity_id = getattr(entity, "id", None)
        channel_id = (
            f"@{username}"
            if username
            else f"-100{entity_id}" if entity_id is not None else fallback_ref
        )
        channel_name = str(
            getattr(entity, "title", None)
            or getattr(entity, "username", None)
            or fallback_ref
        ).strip()
        avatar_bytes = b""
        try:
            avatar_data = await asyncio.wait_for(
                client.download_profile_photo(entity, file=bytes),
                timeout=5,
            )
            if isinstance(avatar_data, bytes):
                avatar_bytes = avatar_data
        except Exception:
            pass
        self.channel_info_fetched.emit(channel_id, channel_name, avatar_bytes)

    async def _scan(self, client: TelegramClient, request: ScanRequest) -> None:
        self.scan_started.emit()
        self.pause_event.set()  # 开始新任务时确保非暂停状态
        if not request.tag.strip() and request.empty_tag_action == "skip":
            self.logger.info("Tag 为空且设置为跳过，任务未扫描")
            self.status_changed.emit("Tag 为空且设置为跳过，未扫描帖子")
            self.scan_plan_ready.emit(0, 0)
            self.scan_discovery_finished.emit(0, 0)
            self.scan_finished.emit(0, 0, 0)
            return

        async def wait_if_paused() -> bool:
            """如果处于暂停状态就挂起，直到继续或取消。返回 True 表示应该 continue/break。"""
            while not self.pause_event.is_set():
                if self.cancel_event.is_set():
                    return True
                await asyncio.sleep(0.3)
            return self.cancel_event.is_set()

        matched_posts = 0
        downloaded = 0
        skipped = 0
        planned_total = 0
        scan_started_at = time.monotonic()
        last_metric_emit = 0.0
        semaphore = asyncio.Semaphore(max(1, request.concurrency))
        download_queue: asyncio.Queue[tuple[int, Any, Path, str, dict[str, Any]] | None] = asyncio.Queue(
            maxsize=max(1, request.concurrency) * 3
        )
        download_workers: list[asyncio.Task[None]] = []
        reserved_targets: set[Path] = set()
        advanced_seen_urls: set[str] = set()
        advanced_seen_media: set[tuple[str, int]] = set()
        post_downloads: dict[int, int] = {}
        post_skips: dict[int, int] = {}
        post_pending: dict[int, int] = {}
        post_discovery_done: set[int] = set()
        post_status_emitted: set[int] = set()
        pending_media_targets: dict[str, Path] = {}
        self._load_media_index(request.save_root)

        def emit_metrics(force: bool = False) -> None:
            nonlocal last_metric_emit
            now = time.monotonic()
            if not force and now - last_metric_emit < 0.5:
                return
            last_metric_emit = now
            completed = downloaded + skipped
            elapsed = max(0.001, now - scan_started_at)
            speed = downloaded / elapsed
            total = max(planned_total, completed + sum(post_pending.values()))
            remaining = max(0, total - completed)
            eta_seconds = int(remaining / speed) if speed > 0 else -1
            self.scan_metrics_changed.emit(
                {
                    "downloaded": downloaded,
                    "skipped": skipped,
                    "completed": completed,
                    "total": total,
                    "remaining": remaining,
                    "speed": speed,
                    "eta_seconds": eta_seconds,
                    "queue_size": download_queue.qsize(),
                }
            )

        def record_file(
                post_id: int,
                target: Path,
                success: bool,
                reason: str = "",
        ) -> None:
            nonlocal downloaded, skipped
            if success:
                downloaded += 1
                post_downloads[post_id] = post_downloads.get(post_id, 0) + 1
                self.logger.file_downloaded(post_id, str(target))
            else:
                skipped += 1
                post_skips[post_id] = post_skips.get(post_id, 0) + 1
                self.logger.file_skipped(post_id, str(target), reason or "已存在或下载失败")
            self.scan_progress.emit(downloaded, skipped, f"帖子 #{post_id}")
            emit_metrics(True)

        def write_extended_info(
            post_id: int,
            message: Any,
            target: Path,
            media_key: str,
            metadata_context: dict[str, Any],
        ) -> None:
            if not request.save_extended_info or not target.exists():
                return
            try:
                payload = self._download_sidecar_payload(
                    request=request,
                    channel_ref=channel_ref,
                    channel_name=channel_name,
                    post_id=post_id,
                    message=message,
                    target=target,
                    media_key=media_key,
                    context=metadata_context,
                )
                write_sidecar(target, payload)
            except Exception as exc:
                self.logger.warning(f"扩展信息保存失败 - 帖子 #{post_id}: {target} ({exc})")

        def begin_post(post: Any) -> None:
            post_id = int(post.id)
            has_replies = bool(
                getattr(getattr(post, "replies", None), "replies", 0) or 0
            )
            self.logger.post_scanning(
                post_id,
                has_replies,
                scan_links=bool(request.custom_extract_json) or request.extract_button_link,
                scan_replies=request.include_replies,
            )
            self.post_status_changed.emit(post_id, "正在处理")

        def emit_finished_post(post_id: int) -> None:
            if post_id not in post_discovery_done or post_id in post_status_emitted:
                return
            if post_pending.get(post_id, 0) > 0:
                return
            downloaded_count = post_downloads.get(post_id, 0)
            skipped_count = post_skips.get(post_id, 0)
            if self.cancel_event.is_set():
                status = "未完成 · 任务已取消"
            elif downloaded_count:
                status = f"已完成 · 下载 {downloaded_count} · 跳过 {skipped_count}"
            elif skipped_count:
                status = f"已完成 · 无新增文件（跳过 {skipped_count}）"
            else:
                status = "已完成 · 未发现可下载文件"
            post_status_emitted.add(post_id)
            self.post_status_changed.emit(post_id, status)
            self.logger.info(f"帖子 #{post_id}: {status}")

        async def download_consumer() -> None:
            while True:
                item = await download_queue.get()
                if item is None:
                    download_queue.task_done()
                    return
                post_id, message, target, media_key, metadata_context = item
                try:
                    if self.cancel_event.is_set():
                        continue
                    success = await self._download_media(
                        client,
                        message,
                        target,
                        semaphore,
                        request.file_download_interval,
                        chunk_concurrency=request.chunk_concurrency,
                    )
                    if success and media_key:
                        self._remember_media_download(media_key, target)
                    if success:
                        write_extended_info(
                            post_id,
                            message,
                            target,
                            media_key,
                            metadata_context,
                        )
                    record_file(post_id, target, success, "" if success else "下载未返回文件")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.logger.error(f"下载失败 - 帖子 #{post_id}: {target} ({exc})")
                    record_file(post_id, target, False, f"下载失败: {exc}")
                finally:
                    if media_key and pending_media_targets.get(media_key) == target:
                        pending_media_targets.pop(media_key, None)
                    post_pending[post_id] = max(0, post_pending.get(post_id, 1) - 1)
                    download_queue.task_done()
                    emit_finished_post(post_id)

        async def enqueue_download(
            post_id: int,
            message: Any,
            target: Path,
            metadata_context: dict[str, Any] | None = None,
        ) -> None:
            media_key = self._media_key(message)
            if request.skip_duplicates and media_key:
                indexed_target = self._indexed_media_path(media_key, target)
                if indexed_target:
                    record_file(post_id, indexed_target, False, "媒体已下载过")
                    return
                pending_target = pending_media_targets.get(media_key)
                if pending_target:
                    record_file(post_id, pending_target, False, "媒体已在本次任务入队")
                    return
            post_pending[post_id] = post_pending.get(post_id, 0) + 1
            try:
                await download_queue.put((post_id, message, target, media_key, metadata_context or {}))
                if request.skip_duplicates and media_key:
                    pending_media_targets[media_key] = target
                emit_metrics()
            except BaseException:
                if media_key and pending_media_targets.get(media_key) == target:
                    pending_media_targets.pop(media_key, None)
                post_pending[post_id] = max(0, post_pending.get(post_id, 1) - 1)
                raise

        async def enqueue_advanced_media(
            source_post_id: int,
            message: Any,
            save_path: str,
            config: dict,
            source_message: Any | None = None,
        ) -> bool:
            """Route advanced C/D resource media through the shared download queue."""
            target_dir = Path(save_path)
            target_dir.mkdir(parents=True, exist_ok=True)
            raw_filename = self._file_name(
                message,
                source_post_id,
                request.filename_template,
                request.preserve_original_name,
            )
            suffix = Path(raw_filename).suffix
            stem_limit = max(1, min(request.filename_limit, 255 - len(suffix)))
            target = target_dir / f"{Path(raw_filename).stem[:stem_limit]}{suffix}"
            if target.exists() or target in reserved_targets:
                target = self._tagged_available_target(
                    target,
                    list(config.get("_source_tags", [])),
                    reserved_targets,
                    request.filename_limit,
                )
            reserved_targets.add(target)
            await enqueue_download(
                source_post_id,
                message,
                target,
                {
                    "source": "advanced",
                    "source_message": source_message or message,
                    "parent_post": source_message,
                    "extra_tags": list(config.get("_source_tags", [])),
                },
            )
            return True

        async def enqueue_linked_media(
            source_post: Any, link_text: str, url: str, target_dir: Path
        ) -> int:
            """Follow a t.me post link and enqueue the target post's actual media."""
            source_post_id = int(source_post.id)
            source_tags = self._extract_hashtags(
                str(getattr(source_post, "message", "") or "")
            )
            request_tag = request.tag.strip().lstrip("#")
            if request_tag and request_tag not in source_tags:
                source_tags.append(request_tag)
            match = re.search(
                r"(?:https?://)?(?:t|telegram)\.me/(?:c/)?([^/\s?#]+)/(\d+)",
                url,
                re.IGNORECASE,
            )
            if not match:
                self.logger.info(f"帖子 #{source_post_id}: 忽略非 Telegram 帖子链接 {url}")
                return 0
            self.logger.debug(
                f"帖子 #{source_post_id}: 命中正文链接「{link_text}」 -> {url}"
            )

            peer_raw, message_id_text = match.groups()
            peer: str | int = peer_raw
            if peer_raw.isdigit():
                peer = int(f"-100{peer_raw}")
            message_id = int(message_id_text)

            try:
                linked_message = await client.get_messages(peer, ids=message_id)
            except Exception as exc:
                self.logger.error(
                    f"帖子 #{source_post_id}: 无法打开原图链接 {url} ({exc})"
                )
                return 0
            if not linked_message:
                self.logger.info(f"帖子 #{source_post_id}: 原图链接目标消息不存在 {url}")
                return 0

            linked_messages = [linked_message]
            grouped_id = getattr(linked_message, "grouped_id", None)
            if grouped_id:
                try:
                    nearby = await client.get_messages(
                        peer,
                        ids=list(range(max(1, message_id - 10), message_id + 11)),
                    )
                    linked_messages = [
                        item
                        for item in nearby
                        if item and getattr(item, "grouped_id", None) == grouped_id
                    ] or linked_messages
                except Exception as exc:
                    self.logger.info(
                        f"帖子 #{source_post_id}: 无法展开目标帖相册，改为下载当前媒体 ({exc})"
                    )

            queued = 0
            target_dir.mkdir(parents=True, exist_ok=True)
            for media_message in linked_messages:
                if request.only_images and not is_image_message(media_message):
                    continue
                if not request.only_images and not is_downloadable_message(media_message):
                    continue
                raw_filename = self._file_name(
                    media_message,
                    int(getattr(media_message, "id", message_id)),
                    request.filename_template,
                    request.preserve_original_name,
                )
                suffix = Path(raw_filename).suffix
                stem_limit = max(1, min(request.filename_limit, 255 - len(suffix)))
                target = target_dir / f"{Path(raw_filename).stem[:stem_limit]}{suffix}"
                if target.exists() or target in reserved_targets:
                    target = self._tagged_available_target(
                        target,
                        source_tags,
                        reserved_targets,
                        request.filename_limit,
                    )
                reserved_targets.add(target)
                await enqueue_download(
                    source_post_id,
                    media_message,
                    target,
                    {
                        "source": "linked_post",
                        "parent_post": source_post,
                        "source_message": media_message,
                        "link_text": link_text,
                        "link_url": url,
                        "extra_tags": source_tags,
                    },
                )
                queued += 1

            if not queued:
                self.logger.info(
                    f"帖子 #{source_post_id}: 链接「{link_text}」的目标帖子没有符合条件的媒体"
                )
            else:
                self.logger.debug(
                    f"帖子 #{source_post_id}: 正文链接目标媒体已加入下载队列，共 {queued} 个"
                )
            return queued

        async def process_comment(parent_post: Any, comment: Any) -> None:
            """Process both direct comment media and original-media links."""
            post_id = int(parent_post.id)
            target_dir = self._target_dir(request, channel_name, post_id)
            target_dir.mkdir(parents=True, exist_ok=True)

            if request.custom_extract_json and _HAS_EXTRACTOR:
                adv_params = {
                    "save_root": str(target_dir),
                    "custom_extract_json": request.custom_extract_json,
                    "only_images": request.only_images,
                    "include_replies": False,
                    "extract_button_link": True,
                    "button_keyword": request.button_keyword,
                    "skip_duplicates": request.skip_duplicates,
                    "filename_limit": request.filename_limit,
                    "_advanced_seen_urls": advanced_seen_urls,
                    "_advanced_seen_media": advanced_seen_media,
                    "_advanced_download_callback": (
                        lambda media, path, cfg, pid=post_id, src=comment:
                        enqueue_advanced_media(pid, media, path, cfg, src)
                    ),
                }
                try:
                    advanced_count = int(
                        await _run_advanced(client, comment, adv_params) or 0
                    )
                    if advanced_count:
                        self.logger.debug(
                            f"帖子 #{post_id}: 高级资源已入队 {advanced_count} 个"
                        )
                except Exception as exc:
                    self.logger.error(
                        f"帖子 #{post_id}: 评论 #{comment.id} 高级链接提取失败: {exc}"
                    )
            elif request.extract_button_link:
                original_link = self._find_original_link(
                    comment, request.button_keyword
                )
                if original_link:
                    link_text, original_url = original_link
                    await enqueue_linked_media(
                        parent_post, link_text, original_url, target_dir
                    )

            if request.only_images and not is_image_message(comment):
                return
            if not request.only_images and not is_downloadable_message(comment):
                return

            raw_filename = self._file_name(
                comment,
                post_id,
                request.filename_template,
                request.preserve_original_name,
            )
            suffix = Path(raw_filename).suffix
            stem_limit = max(1, min(request.filename_limit, 255 - len(suffix)))
            stem = Path(raw_filename).stem[:stem_limit]
            target = target_dir / f"{stem}{suffix}"
            if target.exists() or target in reserved_targets:
                if request.skip_duplicates or request.duplicate_mode == "skip":
                    record_file(post_id, target, False, "文件已存在")
                    return
                if request.duplicate_mode == "rename":
                    target = self._available_target(target, reserved_targets)
            reserved_targets.add(target)
            await enqueue_download(
                post_id,
                comment,
                target,
                {
                    "source": "comment",
                    "parent_post": parent_post,
                    "source_message": comment,
                },
            )

        async def finish_post(post_id: int) -> None:
            post_discovery_done.add(post_id)
            emit_finished_post(post_id)

        download_workers = [
            asyncio.create_task(download_consumer())
            for _ in range(max(1, request.concurrency))
        ]

        try:
            self.logger.task_started(request.channel, request.tag)
            channel_ref, entity = await resolve_channel_entity(client, request.channel)
            channel_name = safe_name(
                getattr(entity, "title", None)
                or getattr(entity, "username", None)
                or "channel"
            )
            await self._emit_channel_info(client, entity, channel_ref)

            tag = request.tag.strip()
            date_from, date_to = self._date_bounds(request)
            date_note = ""
            if date_from or date_to:
                date_note = f"，日期 {date_from or '不限'} 至 {date_to or '不限'}"

            # 检查是否有预览缓存
            cache_key = (
                normalize_channel_reference(request.channel),
                request.tag.strip(),
                request.date_from,
                request.date_to,
            )
            cached_posts: list[dict] | None = (
                self._preview_cache.get(cache_key)
                if request.only_images
                and self._preview_cache_limits.get(cache_key, 0) >= request.max_posts
                else None
            )
            if cached_posts is None and request.resume_post_ids:
                resume_ids = list(dict.fromkeys(int(item) for item in request.resume_post_ids))
                self.status_changed.emit(f"从恢复队列载入 {len(resume_ids)} 篇帖子…")
                try:
                    resumed = await client.get_messages(entity, ids=resume_ids)
                except Exception as exc:
                    self.logger.warning(f"恢复队列载入失败，改为重新扫描: {exc}")
                    resumed = []
                if resumed and not isinstance(resumed, list):
                    resumed = [resumed]
                cached_posts = [
                    {
                        "post_id": int(item.id),
                        "_post": item,
                        "_comments": None,
                        "_media_messages": [],
                    }
                    for item in (resumed or [])
                    if item
                ]
                if cached_posts:
                    matched_posts = len(cached_posts)
                    planned_total = 0
                    self.scan_plan_ready.emit(matched_posts, planned_total)
                    emit_metrics(True)
                else:
                    cached_posts = None
            if cached_posts is not None:
                if request.resume_post_ids:
                    self.status_changed.emit("使用上次扫描恢复队列，继续处理未完成帖子")
                else:
                    self.status_changed.emit("使用搜索预览缓存，直接下载已发现图片")
                matched_posts = len(cached_posts)
                planned_files = 0
                if request.include_replies:
                    planned_files += sum(
                        len(item.get("_media_messages", [])) for item in cached_posts
                    )
                if request.extract_button_link and not (
                    request.custom_extract_json and _HAS_EXTRACTOR
                ):
                    planned_files += sum(
                        1
                        for item in cached_posts
                        if item.get("_post")
                        and self._find_original_link(item["_post"], request.button_keyword)
                    )
                planned_total = planned_files
                self.scan_plan_ready.emit(matched_posts, planned_files)
                emit_metrics(True)
            else:
                self.status_changed.emit(
                    f"从最新帖子开始搜索 {tag or '全部帖子'}，"
                    f"最多匹配 {request.max_posts} 篇{date_note}"
                )

            # 如果有缓存，直接使用预览时保存的帖子和媒体消息。
            if cached_posts is not None:
                for cached_post in cached_posts:
                    if self.cancel_event.is_set():
                        break

                    post_id = cached_post.get("post_id")
                    if not post_id:
                        continue

                    try:
                        # 暂停检查
                        if await wait_if_paused():
                            break
                        post = cached_post.get("_post")
                        if post is None:
                            post = await client.get_messages(entity, ids=post_id)
                        if not post:
                            continue

                        begin_post(post)
                        self.status_changed.emit(f"正在检查帖子 #{post.id} 的正文链接与媒体")

                        # ── 高级套娃提取路径 ──────────────────────────────
                        if request.custom_extract_json and _HAS_EXTRACTOR:
                            self.status_changed.emit(f"[高级模式] 正在深挖帖子 #{post.id}…")
                            target_dir = self._target_dir(request, channel_name, post.id)
                            target_dir.mkdir(parents=True, exist_ok=True)
                            adv_params = {
                                "save_root": str(target_dir),
                                "custom_extract_json": request.custom_extract_json,
                                "only_images": request.only_images,
                                "include_replies": request.include_replies,
                                "extract_button_link": True,
                                "button_keyword": request.button_keyword,
                                "skip_duplicates": request.skip_duplicates,
                                "filename_limit": request.filename_limit,
                                "_advanced_seen_urls": advanced_seen_urls,
                                "_advanced_seen_media": advanced_seen_media,
                                "_advanced_download_callback": (
                                    lambda media, path, cfg, pid=int(post.id), src=post:
                                    enqueue_advanced_media(pid, media, path, cfg, src)
                                ),
                            }
                            try:
                                advanced_count = int(
                                    await _run_advanced(client, post, adv_params) or 0
                                )
                                if advanced_count:
                                    self.logger.debug(
                                        f"帖子 #{post.id}: 高级资源已入队 {advanced_count} 个"
                                    )
                            except Exception as _adv_exc:
                                self.logger.error(f"高级提取失败 #{post.id}: {_adv_exc}")
                            await finish_post(post.id)
                            continue
                        # 跟随帖子正文或按钮中的 Telegram 链接，下载目标帖媒体。
                        if request.extract_button_link and not (
                            request.custom_extract_json and _HAS_EXTRACTOR
                        ):
                            original_link = self._find_original_link(post, request.button_keyword)
                            if original_link:
                                link_text, original_url = original_link
                                target_dir = self._target_dir(request, channel_name, post.id)
                                await enqueue_linked_media(
                                    post, link_text, original_url, target_dir
                                )
                            else:
                                self.logger.debug(
                                    f"帖子 #{post.id}: 正文中未找到包含"
                                    f"「{request.button_keyword}」的 Telegram 帖子链接"
                                )

                        if not request.include_replies:
                            await finish_post(post.id)
                            continue

                        try:
                            cached_comments = cached_post.get("_comments")
                            if cached_comments is not None:
                                comments = cached_comments
                            else:
                                comments = [
                                    comment
                                    async for comment in client.iter_messages(entity, reply_to=post.id)
                                ]
                            for comment in comments:
                                if self.cancel_event.is_set():
                                    break
                                await process_comment(post, comment)
                        except errors.RPCError:
                            pass
                        await finish_post(post.id)
                    except Exception as exc:
                        self.logger.error(f"帖子 #{post_id} 处理失败: {exc}")
                        self.post_status_changed.emit(int(post_id), f"未完成 · {exc}")
                        continue
            else:
                # 没有缓存，正常扫描
                async for post in client.iter_messages(
                        entity,
                        search=tag or None,
                        limit=None,
                        reverse=False,
                ):
                    if self.cancel_event.is_set():
                        break
                    if matched_posts >= request.max_posts:
                        break
                    if self._is_older_than_start(post, date_from):
                        break
                    if not self._matches_date_bounds(post, date_from, date_to):
                        continue
                    if tag and tag.casefold() not in (post.message or "").casefold():
                        continue

                    # 暂停检查
                    if await wait_if_paused():
                        break
                    matched_posts += 1
                    begin_post(post)
                    self.status_changed.emit(f"正在检查帖子 #{post.id} 的正文链接与媒体")

                    # ── 高级套娃提取路径 ──────────────────────────────
                    if request.custom_extract_json and _HAS_EXTRACTOR:
                        self.status_changed.emit(f"[高级模式] 正在深挖帖子 #{post.id}…")
                        target_dir = self._target_dir(request, channel_name, post.id)
                        target_dir.mkdir(parents=True, exist_ok=True)
                        adv_params = {
                            "save_root": str(target_dir),
                            "custom_extract_json": request.custom_extract_json,
                            "only_images": request.only_images,
                            "include_replies": request.include_replies,
                            "extract_button_link": True,
                            "button_keyword": request.button_keyword,
                            "skip_duplicates": request.skip_duplicates,
                            "filename_limit": request.filename_limit,
                            "_advanced_seen_urls": advanced_seen_urls,
                            "_advanced_seen_media": advanced_seen_media,
                            "_advanced_download_callback": (
                                lambda media, path, cfg, pid=int(post.id), src=post:
                                enqueue_advanced_media(pid, media, path, cfg, src)
                            ),
                        }
                        try:
                            advanced_count = int(
                                await _run_advanced(client, post, adv_params) or 0
                            )
                            if advanced_count:
                                self.logger.debug(
                                    f"帖子 #{post.id}: 高级资源已入队 {advanced_count} 个"
                                )
                        except Exception as _adv_exc:
                            self.logger.error(f"高级提取失败 #{post.id}: {_adv_exc}")
                        await finish_post(post.id)
                        continue
                    if request.extract_button_link and not (
                        request.custom_extract_json and _HAS_EXTRACTOR
                    ):
                        original_link = self._find_original_link(post, request.button_keyword)
                        if original_link:
                            link_text, original_url = original_link
                            target_dir = self._target_dir(request, channel_name, post.id)
                            await enqueue_linked_media(
                                post, link_text, original_url, target_dir
                            )
                        else:
                            self.logger.debug(
                                f"帖子 #{post.id}: 正文中未找到包含"
                                f"「{request.button_keyword}」的 Telegram 帖子链接"
                            )

                    if not request.include_replies:
                        await finish_post(post.id)
                        continue

                    try:
                        comment_iter = client.iter_messages(entity, reply_to=post.id)
                        async for comment in comment_iter:
                            if self.cancel_event.is_set():
                                break
                            await process_comment(post, comment)
                    except errors.RPCError:
                        # 该帖子没有评论区或评论区不可访问，跳过继续处理下一条帖子
                        pass
                    await finish_post(post.id)

            if not self.cancel_event.is_set():
                discovered_files = downloaded + skipped + sum(post_pending.values())
                planned_total = max(planned_total, discovered_files)
                self.scan_discovery_finished.emit(matched_posts, discovered_files)
                emit_metrics(True)

            await download_queue.join()

            self.logger.task_completed(
                matched_posts, downloaded, skipped, self.cancel_event.is_set()
            )
            retry_key = (request.channel, request.tag, str(request.save_root))
            self._scan_retry_attempts.pop(retry_key, None)
            self.scan_finished.emit(matched_posts, downloaded, skipped)
            self.status_changed.emit("任务已取消" if self.cancel_event.is_set() else "下载完成")
        except errors.FloodWaitError as exc:
            wait_seconds = max(1, int(getattr(exc, "seconds", 1)))
            self.logger.warning(f"Telegram FloodWait: 自动等待 {wait_seconds} 秒后继续")
            for remaining in range(wait_seconds, 0, -1):
                if self.cancel_event.is_set():
                    break
                if remaining == wait_seconds or remaining <= 5 or remaining % 10 == 0:
                    self.status_changed.emit(f"Telegram 限流，{remaining} 秒后自动继续")
                await asyncio.sleep(1)
            if not self.cancel_event.is_set() and not self._stopping.is_set():
                self._put_command("scan", request)
                self.status_changed.emit("限流等待结束，正在自动恢复任务…")
            return
        except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
            retry_key = (request.channel, request.tag, str(request.save_root))
            attempts = self._scan_retry_attempts.get(retry_key, 0)
            if not self.cancel_event.is_set() and not self._stopping.is_set() and attempts < 3:
                self._scan_retry_attempts[retry_key] = attempts + 1
                delay = 3 * (attempts + 1)
                self.logger.warning(f"网络中断，{delay} 秒后自动重试 ({attempts + 1}/3): {exc}")
                self.status_changed.emit(f"网络中断，{delay} 秒后自动重试 ({attempts + 1}/3)")
                await asyncio.sleep(delay)
                self._put_command("scan", request)
            else:
                self._scan_retry_attempts.pop(retry_key, None)
                self.logger.error(f"任务失败: {exc}")
                self.scan_failed.emit(str(exc))
        except Exception as exc:
            self.logger.error(f"任务失败: {exc}")
            self.scan_failed.emit(str(exc))
        finally:
            for _ in download_workers:
                await download_queue.put(None)
            if download_workers:
                await asyncio.gather(*download_workers, return_exceptions=True)

    async def _preview(self, client: TelegramClient, request: PreviewRequest) -> None:
        self.preview_started.emit()

        # 检查缓存
        cache_key = (
            normalize_channel_reference(request.channel),
            request.tag.strip(),
            request.date_from,
            request.date_to,
        )
        request_signature = (
            request.max_posts,
            request.max_results,
            request.include_replies,
            request.extract_button_link,
            request.button_keyword,
            request.custom_extract_json,
            request.date_from,
            request.date_to,
        )
        if (
            cache_key in self._preview_cache
            and self._preview_cache_requests.get(cache_key) == request_signature
        ):
            self.preview_progress.emit("正在从缓存加载…")
            await asyncio.sleep(0.3)  # 短暂延迟以显示消息
            rows = self._preview_cache[cache_key]
            self.preview_finished.emit(
                self._public_preview_rows(rows),
                self._preview_cache_totals.get(cache_key, len(rows)),
                request.max_results,
            )
            return

        results: list[dict[str, Any]] = []
        total_count = 0
        preview_complete = True
        try:
            channel_ref, entity = await resolve_channel_entity(client, request.channel)
            await self._emit_channel_info(client, entity, channel_ref)
            channel_name = (
                    getattr(entity, "title", None)
                    or getattr(entity, "username", None)
                    or request.channel
            )
            tag = request.tag.strip()
            date_from, date_to = self._date_bounds(request)
            date_note = ""
            if date_from or date_to:
                date_note = f"（{date_from or '不限'} 至 {date_to or '不限'}）"
            self.preview_progress.emit(
                f"正在搜索 {channel_name} 中的 {tag or '全部帖子'}{date_note}…"
            )

            async for post in client.iter_messages(
                    entity,
                    search=tag or None,
                    limit=None,
                    reverse=False,
            ):
                if self.preview_cancel_event.is_set():
                    preview_complete = False
                    break
                if total_count >= request.max_posts:
                    break
                if self._is_older_than_start(post, date_from):
                    break
                if not self._matches_date_bounds(post, date_from, date_to):
                    continue
                text = (post.message or "").strip()
                if tag and tag.casefold() not in text.casefold():
                    continue
                total_count += 1
                if len(results) >= request.max_results:
                    if total_count % 25 == 0:
                        self.preview_progress.emit(
                            f"已找到 {total_count} 篇匹配帖子，继续统计总数…"
                        )
                    continue

                image_count = 0
                thumbnails: list[bytes] = []
                comments: list[Any] = []
                media_messages: list[Any] = []
                hit_sources: list[str] = []
                debug_trace: list[str] = [f"A 帖子 #{post.id}"]
                body_link = (
                    self._find_original_link(post, request.button_keyword)
                    if request.extract_button_link
                    else None
                )
                has_tg_link = bool(body_link or self._telegram_post_links(post))
                if body_link:
                    hit_sources.append("正文链接命中")
                    debug_trace.append(f"正文链接「{body_link[0]}」 -> {body_link[1]}")
                if request.custom_extract_json and has_tg_link:
                    hit_sources.append("高级规则命中")
                    debug_trace.append("高级规则会继续深挖正文/评论区中的 Telegram 链接")
                self.preview_progress.emit(f"正在检查帖子 #{post.id} 的评论图片…")
                try:
                    async for comment in client.iter_messages(entity, reply_to=post.id):
                        if self.preview_cancel_event.is_set():
                            preview_complete = False
                            break
                        comments.append(comment)
                        comment_link = (
                            self._find_original_link(comment, request.button_keyword)
                            if request.extract_button_link
                            else None
                        )
                        if comment_link and "评论区链接命中" not in hit_sources:
                            hit_sources.append("评论区链接命中")
                            debug_trace.append(
                                f"评论 #{comment.id} 链接「{comment_link[0]}」 -> {comment_link[1]}"
                            )
                        if not is_image_message(comment):
                            continue
                        image_count += 1
                        media_messages.append(comment)
                        if len(thumbnails) < request.thumbnails_per_post:
                            thumbnail = await self._thumbnail_bytes(client, comment)
                            if thumbnail:
                                thumbnails.append(thumbnail)
                except errors.RPCError:
                    # Some posts have no linked discussion or comments are unavailable.
                    pass
                if image_count:
                    hit_sources.append("评论区图片命中")
                    debug_trace.append(f"评论区发现 {image_count} 张图片")
                if not hit_sources:
                    hit_sources.append("仅文本匹配")

                results.append(
                    {
                        "channel": str(channel_name),
                        "post_id": int(post.id),
                        "text": text,
                        "date": post.date.astimezone().strftime("%Y-%m-%d %H:%M")
                        if getattr(post, "date", None)
                        else "-",
                        "views": int(getattr(post, "views", 0) or 0),
                        "replies": int(
                            getattr(getattr(post, "replies", None), "replies", 0) or 0
                        ),
                        "image_count": image_count,
                        "hit_sources": hit_sources,
                        "debug_trace": debug_trace,
                        "thumbnails": thumbnails,
                        "_post": post,
                        "_comments": comments,
                        "_media_messages": media_messages,
                    }
                )

            # 保存到缓存
            self._preview_cache[cache_key] = results
            self._preview_cache_totals[cache_key] = total_count
            self._preview_cache_requests[cache_key] = request_signature
            self._preview_cache_limits[cache_key] = (
                request.max_posts
                if preview_complete and total_count <= request.max_results
                else 0
            )
            self.preview_finished.emit(
                self._public_preview_rows(results),
                total_count,
                request.max_results,
            )
        except errors.FloodWaitError as exc:
            self.preview_failed.emit(f"Telegram 要求等待 {exc.seconds} 秒后重试")
        except Exception as exc:
            self.preview_failed.emit(str(exc))

    @staticmethod
    def _public_preview_rows(rows: list[dict]) -> list[dict]:
        """Remove worker-only Telegram objects before sending preview data to the UI."""
        return [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in rows
        ]

    @staticmethod
    def _parse_filter_date(value: str) -> date | None:
        value = str(value or "").strip()
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return None

    @classmethod
    def _date_bounds(cls, request: ScanRequest | PreviewRequest) -> tuple[date | None, date | None]:
        start = cls._parse_filter_date(getattr(request, "date_from", ""))
        end = cls._parse_filter_date(getattr(request, "date_to", ""))
        if start and end and start > end:
            start, end = end, start
        return start, end

    @staticmethod
    def _message_local_date(message: Any) -> date | None:
        value = getattr(message, "date", None)
        if value is None:
            return None
        try:
            return value.astimezone().date()
        except (AttributeError, ValueError, OSError):
            return None

    @classmethod
    def _matches_date_bounds(
        cls, message: Any, start: date | None, end: date | None
    ) -> bool:
        if not start and not end:
            return True
        current = cls._message_local_date(message)
        if current is None:
            return False
        if start and current < start:
            return False
        if end and current > end:
            return False
        return True

    @classmethod
    def _is_older_than_start(cls, message: Any, start: date | None) -> bool:
        current = cls._message_local_date(message)
        return bool(start and current and current < start)

    async def _thumbnail_bytes(self, client: TelegramClient, message: Any) -> bytes | None:
        if is_webpage_preview(message) or is_sticker_message(message):
            return None
        cache_key = self._media_key(message)
        now = time.time()
        if cache_key:
            cached = self._thumbnail_cache.get(cache_key)
            if cached and now - cached[0] <= self._thumbnail_cache_ttl:
                return cached[1]
        document = getattr(message, "document", None)
        has_thumbnail = bool(getattr(message, "photo", None)) or bool(
            getattr(document, "thumbs", None)
        )
        if not has_thumbnail:
            return None
        try:
            result = await client.download_media(message, file=bytes, thumb=0)
            if isinstance(result, bytes):
                if cache_key:
                    self._thumbnail_cache[cache_key] = (now, result)
                    if len(self._thumbnail_cache) > 500:
                        expired = [
                            key for key, (saved_at, _) in self._thumbnail_cache.items()
                            if now - saved_at > self._thumbnail_cache_ttl
                        ]
                        for key in expired:
                            self._thumbnail_cache.pop(key, None)
                return result
            return None
        except (errors.RPCError, OSError, ValueError):
            return None

    @staticmethod
    async def _download_media(
            client: TelegramClient,
            message: Any,
            target: Path,
            semaphore: asyncio.Semaphore,
            file_download_interval: float,
            chunk_concurrency: int = 1,
    ) -> bool:
        """
        下载单个媒体文件。

        chunk_concurrency == 1（默认）：走 Telethon 原生单线程流式下载。
        chunk_concurrency >= 2：启用分片并发下载。
          原理：先获取文件总大小，将其等分为 N 块，N 个协程同时用
          iter_download(offset, limit) 拉取对应字节段，全部完成后
          按顺序写入磁盘，速度可提升 2-4x（受服务器限速影响）。
        """
        if not is_downloadable_message(message):
            return False

        async def download() -> bool:
            target.parent.mkdir(parents=True, exist_ok=True)
            if chunk_concurrency <= 1:
                result = await client.download_media(message, file=str(target))
                return bool(result)

            media = getattr(message, "media", None)
            document = (
                message_document(message)
                or getattr(media, "photo", None)
                or getattr(message, "photo", None)
            )
            file_info = getattr(message, "file", None)
            file_size = int(
                getattr(document, "size", 0)
                or getattr(file_info, "size", 0)
                or 0
            )

            MIN_CHUNK_SIZE = 512 * 1024  # 512 KB，低于这个没必要分片
            if file_size < MIN_CHUNK_SIZE * chunk_concurrency:
                result = await client.download_media(message, file=str(target))
                return bool(result)

            chunk_size = (file_size + chunk_concurrency - 1) // chunk_concurrency
            ALIGN = 4096
            chunk_size = ((chunk_size + ALIGN - 1) // ALIGN) * ALIGN

            ranges: list[tuple[int, int, Path]] = []
            offset = 0
            index = 0
            while offset < file_size:
                end = min(offset + chunk_size, file_size)
                ranges.append(
                    (
                        offset,
                        end - offset,
                        target.with_name(f"{target.name}.part.{index}"),
                    )
                )
                offset = end
                index += 1

            request_size = MIN_CHUNK_SIZE

            async def fetch_chunk(off: int, length: int, part_path: Path) -> Path:
                written = 0
                limit = (length + request_size - 1) // request_size
                part_path.unlink(missing_ok=True)
                with part_path.open("wb") as fh:
                    async for block in client.iter_download(
                        message,
                        offset=off,
                        limit=limit,
                        chunk_size=request_size,
                        request_size=request_size,
                        file_size=file_size,
                    ):
                        if written >= length:
                            break
                        remaining = length - written
                        data = bytes(block)[:remaining]
                        fh.write(data)
                        written += len(data)
                if written != length:
                    raise OSError(
                        f"incomplete chunk at offset {off}: {written} != {length}"
                    )
                return part_path

            tmp_path = target.with_suffix(target.suffix + ".part")
            try:
                parts: list[Path | BaseException] = await asyncio.gather(
                    *(fetch_chunk(off, lim, part) for off, lim, part in ranges),
                    return_exceptions=True,
                )

                if any(isinstance(part, BaseException) for part in parts):
                    raise OSError("chunked download failed")

                target.parent.mkdir(parents=True, exist_ok=True)
                tmp_path.unlink(missing_ok=True)
                with tmp_path.open("wb") as out:
                    for _, _, part_path in ranges:
                        with part_path.open("rb") as part_file:
                            while True:
                                data = part_file.read(1024 * 512)
                                if not data:
                                    break
                                out.write(data)
                if tmp_path.stat().st_size != file_size:
                    raise OSError(
                        f"merged file size mismatch: {tmp_path.stat().st_size} != {file_size}"
                    )
                tmp_path.replace(target)
                return target.exists() and target.stat().st_size > 0
            except OSError:
                tmp_path.unlink(missing_ok=True)
                result = await client.download_media(message, file=str(target))
                return bool(result)
            finally:
                for _, _, part_path in ranges:
                    part_path.unlink(missing_ok=True)

        async with semaphore:
            success = await download()
        # 冷却不占用下载并发槽，其他文件可以继续传输。
        if file_download_interval > 0:
            await asyncio.sleep(file_download_interval)
        return success

    def _load_media_index(self, save_root: Path) -> None:
        """Load per-save-root media ids used for duplicate detection."""
        self._downloaded_media_index_path = save_root / ".tg_pic_collector_media.json"
        self._downloaded_media_keys = set()
        self._downloaded_media_paths = {}
        try:
            if self._downloaded_media_index_path.exists():
                payload = json.loads(self._downloaded_media_index_path.read_text(encoding="utf-8"))
                self._downloaded_media_keys = {
                    str(item) for item in payload.get("media_keys", []) if item
                }
                media_paths = payload.get("media_paths", {})
                if isinstance(media_paths, dict):
                    self._downloaded_media_paths = {
                        str(key): str(value)
                        for key, value in media_paths.items()
                        if key and value
                    }
                    self._downloaded_media_keys.update(self._downloaded_media_paths)
        except (OSError, ValueError, TypeError):
            self._downloaded_media_keys = set()
            self._downloaded_media_paths = {}

    def _save_media_index(self) -> None:
        if not self._downloaded_media_index_path:
            return
        try:
            self._downloaded_media_index_path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {
                    "version": 2,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                    "media_keys": sorted(self._downloaded_media_keys),
                    "media_paths": {
                        key: self._downloaded_media_paths[key]
                        for key in sorted(self._downloaded_media_paths)
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            tmp_path = self._downloaded_media_index_path.with_name(
                f"{self._downloaded_media_index_path.name}.tmp"
            )
            tmp_path.write_text(
                payload,
                encoding="utf-8",
            )
            tmp_path.replace(self._downloaded_media_index_path)
        except OSError:
            pass

    def _indexed_media_path(self, media_key: str, fallback_target: Path | None = None) -> Path | None:
        if not media_key:
            return None
        root = self._downloaded_media_index_path.parent if self._downloaded_media_index_path else None
        raw_path = self._downloaded_media_paths.get(media_key, "")
        if raw_path and root:
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = root / candidate
            if candidate.exists():
                return candidate
            self._downloaded_media_paths.pop(media_key, None)
            self._downloaded_media_keys.discard(media_key)
            self._save_media_index()
        if fallback_target and media_key in self._downloaded_media_keys:
            if fallback_target.exists():
                return fallback_target
            self._downloaded_media_keys.discard(media_key)
            self._save_media_index()
        return None

    def _remember_media_download(self, media_key: str, target: Path) -> None:
        if not media_key or not target.exists():
            return
        self._downloaded_media_keys.add(media_key)
        root = self._downloaded_media_index_path.parent if self._downloaded_media_index_path else None
        stored_path = str(target)
        if root:
            try:
                stored_path = str(target.resolve().relative_to(root.resolve()))
            except (OSError, ValueError):
                stored_path = str(target.resolve())
        self._downloaded_media_paths[media_key] = stored_path
        self._save_media_index()

    @staticmethod
    def _media_key(message: Any) -> str:
        """Stable Telegram media identity used for cross-task duplicate checks."""
        media = getattr(message, "media", None)
        document = getattr(media, "document", None) or getattr(message, "document", None)
        if document and getattr(document, "id", None):
            return f"doc:{document.id}"
        photo = getattr(media, "photo", None) or getattr(message, "photo", None)
        if photo and getattr(photo, "id", None):
            return f"photo:{photo.id}"
        peer_id = getattr(getattr(message, "peer_id", None), "channel_id", "")
        message_id = getattr(message, "id", "")
        return f"msg:{peer_id}:{message_id}" if message_id else ""

    @staticmethod
    def _message_text(message: Any, limit: int = 5000) -> str:
        text = str(getattr(message, "message", "") or "").strip()
        if len(text) > limit:
            return f"{text[:limit]}..."
        return text

    @staticmethod
    def _message_date(message: Any) -> str | None:
        value = getattr(message, "date", None)
        if not value:
            return None
        try:
            return value.astimezone().isoformat(timespec="seconds")
        except (AttributeError, ValueError, TypeError):
            return str(value)

    @staticmethod
    def _message_id(message: Any) -> int | None:
        try:
            return int(getattr(message, "id"))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _message_url(channel_ref: str, message: Any) -> str:
        message_id = TelegramWorker._message_id(message)
        if not message_id:
            return ""
        if channel_ref.startswith("@"):
            return f"https://t.me/{channel_ref[1:]}/{message_id}"
        if channel_ref.startswith("-100") and channel_ref[4:].isdigit():
            return f"https://t.me/c/{channel_ref[4:]}/{message_id}"
        return ""

    @classmethod
    def _metadata_tags(
        cls,
        request_tag: str,
        messages: list[Any],
        extra_tags: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        tagged: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(name: str, source: str, confidence: float = 1.0) -> None:
            clean = name.strip().lstrip("#")
            if not clean or clean.casefold() in seen:
                return
            seen.add(clean.casefold())
            tagged.append(
                {
                    "name": clean,
                    "source": source,
                    "confidence": confidence,
                }
            )

        add(request_tag, "task")
        for item in extra_tags or []:
            add(str(item), "source")
        for message in messages:
            for tag in cls._extract_hashtags(cls._message_text(message)):
                add(tag, "telegram_hashtag")
        return tagged

    @classmethod
    def _download_sidecar_payload(
        cls,
        request: ScanRequest,
        channel_ref: str,
        channel_name: str,
        post_id: int,
        message: Any,
        target: Path,
        media_key: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        parent_post = context.get("parent_post")
        source_message = context.get("source_message") or message
        file_info = getattr(message, "file", None)
        original_name = str(getattr(file_info, "name", "") or "")
        mime_type = str(
            getattr(file_info, "mime_type", "")
            or getattr(getattr(message, "document", None), "mime_type", "")
            or mimetypes.guess_type(target.name)[0]
            or ""
        )
        return {
            "image": {
                "path": target.name,
                "original_filename": original_name,
                "mime": mime_type,
            },
            "tags": cls._metadata_tags(
                request.tag,
                [item for item in (parent_post, source_message, message) if item],
                list(context.get("extra_tags", []) or []),
            ),
            "telegram": {
                "channel": request.channel,
                "channel_ref": channel_ref,
                "channel_name": channel_name,
                "post_id": int(post_id),
                "post_url": cls._message_url(channel_ref, parent_post or message),
                "message_id": cls._message_id(message),
                "message_date": cls._message_date(message),
                "media_key": media_key,
                "source": str(context.get("source", "direct")),
                "source_message_id": cls._message_id(source_message),
                "source_message_date": cls._message_date(source_message),
                "source_url": cls._message_url(channel_ref, source_message),
                "link_text": str(context.get("link_text", "") or ""),
                "link_url": str(context.get("link_url", "") or ""),
            },
            "text": {
                "post": cls._message_text(parent_post) if parent_post else "",
                "source": cls._message_text(source_message),
                "message": cls._message_text(message),
            },
            "download": {
                "filename": target.name,
                "directory": str(target.parent),
            },
        }

    @staticmethod
    def _is_telegram_post_url(url: str) -> bool:
        return bool(
            re.search(
                r"(?:https?://)?(?:t|telegram)\.me/(?:c/)?[^/\s?#]+/\d+",
                str(url or ""),
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _find_button_url(message: Any, keyword: str) -> tuple[str, str] | None:
        keyword_folded = keyword.strip().casefold()
        if not keyword_folded:
            return None
        for row in getattr(message, "buttons", None) or []:
            buttons = row if isinstance(row, (list, tuple)) else [row]
            for button in buttons:
                text = str(getattr(button, "text", "") or "").strip()
                url = str(getattr(button, "url", "") or "").strip()
                if url and keyword_folded in text.casefold():
                    return text, url
        return None

    @staticmethod
    def _write_link_shortcut(target: Path, url: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")

    @staticmethod
    def _telegram_post_links(message: Any) -> list[str]:
        raw_text = str(getattr(message, "message", "") or "")
        links: list[str] = []
        try:
            entities_text = message.get_entities_text()
        except (AttributeError, TypeError, ValueError):
            entities_text = []
        for entity, visible_text in entities_text:
            text = str(visible_text or "").strip()
            url = str(getattr(entity, "url", "") or "").strip()
            if not url and type(entity).__name__ == "MessageEntityUrl":
                url = text
            if TelegramWorker._is_telegram_post_url(url):
                links.append(url)
        links.extend(
            re.findall(
                r"(?:https?://)?(?:t|telegram)\.me/(?:c/)?[^/\s?#)]+/\d+",
                raw_text,
                flags=re.IGNORECASE,
            )
        )
        deduped: list[str] = []
        for link in links:
            if link not in deduped:
                deduped.append(link)
        return deduped

    @staticmethod
    def _find_original_link(message: Any, keyword: str) -> tuple[str, str] | None:
        """Find a matching Telegram post URL in buttons or message text."""
        keyword_folded = keyword.strip().casefold()
        if not keyword_folded:
            return None

        button_link = TelegramWorker._find_button_url(message, keyword)
        if button_link and TelegramWorker._is_telegram_post_url(button_link[1]):
            return button_link

        raw_text = str(getattr(message, "message", "") or "")
        candidates: list[tuple[str, str]] = []
        try:
            entities_text = message.get_entities_text()
        except (AttributeError, TypeError, ValueError):
            entities_text = []
        for entity, visible_text in entities_text:
            text = str(visible_text or "").strip()
            url = str(getattr(entity, "url", "") or "").strip()
            if not url and type(entity).__name__ == "MessageEntityUrl":
                url = text
            if TelegramWorker._is_telegram_post_url(url):
                if keyword_folded in text.casefold():
                    return text, url
                candidates.append((text, url))

        # Also support messages where Markdown-like source text was posted literally.
        for text, url in re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", raw_text):
            if (
                keyword_folded in text.casefold()
                and TelegramWorker._is_telegram_post_url(url)
            ):
                return text.strip(), url.strip()

        for url in re.findall(
            r"(?:https?://)?(?:t|telegram)\.me/(?:c/)?[^/\s?#)]+/\d+",
            raw_text,
            flags=re.IGNORECASE,
        ):
            candidates.append((url, url))

        # Some Telegram posts store the label and URL as separate entities. If the
        # body contains the keyword, use the first unique Telegram post link.
        if keyword_folded in raw_text.casefold():
            seen: set[str] = set()
            for text, url in candidates:
                if url in seen:
                    continue
                seen.add(url)
                return text, url
        return None

    @staticmethod
    def _target_dir(request: ScanRequest, channel_name: str, post_id: int) -> Path:
        tag_name = request.tag.lstrip("#")

        # ✨ 处理 Tag 为空的情况
        if not tag_name:
            if request.empty_tag_action == "channel":
                tag_name = channel_name
            else:  # "uncategorized"
                tag_name = "未分类"

        tag_name = safe_name(tag_name, "未分类")

        if request.save_mode == "channel_tag":
            return request.save_root / channel_name / tag_name
        if request.save_mode == "tag":
            return request.save_root / tag_name
        if request.save_mode == "post":
            return request.save_root / tag_name / f"post_{post_id}"

        return request.save_root

    @staticmethod
    def _file_name(
            message: Any,
            post_id: int,
            template: str = "{date}_post{post_id}_comment{comment_id}",
            preserve_original_name: bool = False,
    ) -> str:
        original = getattr(getattr(message, "file", None), "name", None)
        suffix = Path(original).suffix if original else ""
        if not suffix:
            mime_type = getattr(getattr(message, "file", None), "mime_type", None)
            suffix = mimetypes.guess_extension(mime_type or "") or ".jpg"
        date = getattr(message, "date", None) or datetime.now()
        stamp = date.strftime("%Y%m%d_%H%M%S")
        if preserve_original_name and original:
            return f"{safe_name(Path(original).stem, str(message.id), 255)}{suffix}"
        try:
            stem = template.format(
                date=stamp,
                post_id=post_id,
                comment_id=message.id,
                index=message.id,
                tag="",
                id=message.id,
                ext=suffix.lstrip("."),
            )
        except (KeyError, ValueError):
            stem = f"{stamp}_post{post_id}_comment{message.id}"
        stem = Path(stem).stem if Path(stem).suffix else stem
        return f"{safe_name(stem, str(message.id), 255)}{suffix}"

    @staticmethod
    def _available_target(target: Path, reserved: set[Path] | None = None) -> Path:
        index = 2
        candidate = target
        occupied = reserved or set()
        while candidate.exists() or candidate in occupied:
            candidate = target.with_name(f"{target.stem}_{index}{target.suffix}")
            index += 1
        return candidate

    @staticmethod
    def _extract_hashtags(text: str) -> list[str]:
        tags: list[str] = []
        for tag in re.findall(r"(?<![\w#])#([\w]+)", text, flags=re.UNICODE):
            cleaned = safe_name(tag, "", 60)
            if cleaned and cleaned not in tags:
                tags.append(cleaned)
        return tags

    @classmethod
    def _tagged_available_target(
        cls,
        target: Path,
        tags: list[str],
        reserved: set[Path] | None = None,
        filename_limit: int = 100,
    ) -> Path:
        occupied = reserved or set()
        suffix = target.suffix
        max_stem_length = max(1, min(filename_limit, 255 - len(suffix)))
        for tag in tags:
            tag_limit = max(1, max_stem_length - 2)
            prefix = f"{safe_name(tag, '', tag_limit)}_"
            stem_limit = max(1, max_stem_length - len(prefix))
            candidate = target.with_name(f"{prefix}{target.stem[:stem_limit]}{suffix}")
            if not candidate.exists() and candidate not in occupied:
                return candidate
        index = 2
        while True:
            tail = f"_{index}"
            stem_limit = max(1, max_stem_length - len(tail))
            candidate = target.with_name(f"{target.stem[:stem_limit]}{tail}{suffix}")
            if not candidate.exists() and candidate not in occupied:
                return candidate
            index += 1
