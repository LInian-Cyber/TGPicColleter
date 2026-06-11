from __future__ import annotations

import asyncio
import mimetypes
import queue
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal
from telethon import TelegramClient, errors

from .logger import get_logger
from .models import PreviewRequest, ScanRequest, TelegramCredentials

try:
    from .crypto import decrypt_session, encrypt_session
except ImportError:
    def decrypt_session(path: Path) -> bool:
        return False


    def encrypt_session(path: Path, use_encryption: bool = True) -> bool:
        return False


def safe_name(value: str, fallback: str = "untitled", max_length: int = 90) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return value[:max_length] or fallback


def is_image_message(message: Any) -> bool:
    """检查消息是否为图片（排除贴纸）"""
    if getattr(message, "photo", None):
        return True
    document = getattr(message, "document", None)
    if not document:
        return False
    
    mime_type = getattr(document, "mime_type", "") if document else ""
    
    # 排除贴纸 (webp 动画贴纸)
    attributes = getattr(document, "attributes", [])
    for attr in attributes:
        # 检查是否为贴纸属性
        if type(attr).__name__ == "DocumentAttributeSticker":
            return False
        # 检查是否为动画贴纸
        if type(attr).__name__ == "DocumentAttributeAnimated":
            return False
    
    return mime_type.startswith("image/")


def is_downloadable_message(message: Any) -> bool:
    return bool(
        getattr(message, "photo", None)
        or getattr(message, "document", None)
        or getattr(message, "media", None)
    )


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
    scan_progress = Signal(int, int, str)
    post_status_changed = Signal(int, str)
    scan_finished = Signal(int, int, int)
    scan_failed = Signal(str)
    preview_started = Signal()
    preview_progress = Signal(str)
    preview_finished = Signal(list)
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
        self.preview_cancel_event = threading.Event()
        self.qr_cancel_event = threading.Event()
        self.logger = get_logger()
        self._phone_code_hash: str | None = None
        self._phone = credentials.phone
        # 搜索预览缓存：{(channel, tag): results}
        self._preview_cache: dict[tuple[str, str], list[dict]] = {}

    def load_dialogs(self) -> None:
        """加载用户的对话列表（频道、群组等）"""
        self.commands.put(("load_dialogs", None))

    def request_code(self, phone: str) -> None:
        self.qr_cancel_event.set()
        self.commands.put(("request_code", phone))

    def sign_in(self, phone: str, code: str, password: str = "") -> None:
        self.qr_cancel_event.set()
        self.commands.put(("sign_in", (phone, code, password)))

    def start_qr_login(self) -> None:
        self.cancel_event.clear()
        self.qr_cancel_event.set()
        self.commands.put(("qr_login", None))

    def log_out(self) -> None:
        self.commands.put(("logout", None))

    def start_scan(self, request: ScanRequest) -> None:
        self.cancel_event.clear()
        self.commands.put(("scan", request))

    def cancel_scan(self) -> None:
        self.cancel_event.set()

    def start_preview(self, request: PreviewRequest) -> None:
        self.preview_cancel_event.clear()
        self.commands.put(("preview", request))

    def cancel_preview(self) -> None:
        self.preview_cancel_event.set()

    def stop(self) -> None:
        self.cancel_event.set()
        self.preview_cancel_event.set()
        self.qr_cancel_event.set()
        self.commands.put(("stop", None))

    def run(self) -> None:
        try:
            asyncio.run(self._main())
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            self.status_changed.emit(f"连接失败：{message}")
            self.connection_failed.emit(message)

    async def _main(self) -> None:
        self.credentials.session_path.parent.mkdir(parents=True, exist_ok=True)

        # 连接前先尝试解密 session
        decrypt_session(self.credentials.session_path)

        client = TelegramClient(
            str(self.credentials.session_path),
            self.credentials.api_id,
            self.credentials.api_hash,
            timeout=10,
            connection_retries=2,
            retry_delay=1,
        )
        self.status_changed.emit("正在连接 Telegram…")
        try:
            await asyncio.wait_for(client.connect(), timeout=25)
        except asyncio.TimeoutError as exc:
            raise ConnectionError("连接 Telegram 超时，请检查网络或代理设置") from exc
        if not client.is_connected():
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
                command, payload = await asyncio.to_thread(self.commands.get)
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
            await client.disconnect()
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

    async def _scan(self, client: TelegramClient, request: ScanRequest) -> None:
        self.scan_started.emit()
        matched_posts = 0
        downloaded = 0
        skipped = 0
        semaphore = asyncio.Semaphore(max(1, request.concurrency))
        pending: dict[asyncio.Task[bool], tuple[int, Path]] = {}
        reserved_targets: set[Path] = set()
        post_downloads: dict[int, int] = {}
        post_skips: dict[int, int] = {}

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

        def begin_post(post: Any) -> None:
            post_id = int(post.id)
            has_replies = bool(
                getattr(getattr(post, "replies", None), "replies", 0) or 0
            )
            self.logger.post_scanning(post_id, has_replies)
            self.post_status_changed.emit(post_id, "正在处理")

        async def collect_finished(wait_all: bool = False) -> None:
            if not pending:
                return
            done, _ = await asyncio.wait(
                set(pending),
                return_when=asyncio.ALL_COMPLETED if wait_all else asyncio.FIRST_COMPLETED,
            )
            for task in done:
                post_id, target = pending.pop(task)
                try:
                    success = task.result()
                    record_file(post_id, target, success, "" if success else "下载未返回文件")
                except Exception as exc:
                    self.logger.error(f"下载失败 - 帖子 #{post_id}: {target} ({exc})")
                    record_file(post_id, target, False, f"下载失败: {exc}")

        async def finish_post(post_id: int) -> None:
            await collect_finished(wait_all=True)
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
            self.post_status_changed.emit(post_id, status)
            self.logger.info(f"帖子 #{post_id}: {status}")

        try:
            self.logger.task_started(request.channel, request.tag)
            channel_ref = request.channel.strip()
            entity_ref: str | int = (
                int(channel_ref) if channel_ref.lstrip("-").isdigit() else channel_ref
            )
            entity = await client.get_entity(entity_ref)
            channel_name = safe_name(
                getattr(entity, "title", None)
                or getattr(entity, "username", None)
                or "channel"
            )
            
            # 获取频道头像
            channel_id = getattr(entity, "username", None) or str(getattr(entity, "id", channel_ref))
            if not channel_id.startswith("@") and not channel_id.startswith("-"):
                channel_id = f"@{channel_id}" if hasattr(entity, "username") else f"-{channel_id}"
            
            try:
                avatar_bytes = await client.download_profile_photo(entity, file=bytes)
                if isinstance(avatar_bytes, bytes):
                    self.channel_info_fetched.emit(channel_id, channel_name, avatar_bytes)
                else:
                    self.channel_info_fetched.emit(channel_id, channel_name, b"")
            except Exception:
                self.channel_info_fetched.emit(channel_id, channel_name, b"")
            
            tag = request.tag.strip()
            
            # 检查是否有预览缓存
            cache_key = (request.channel.strip(), request.tag.strip())
            cached_posts = None
            if cache_key in self._preview_cache:
                self.status_changed.emit(f"使用搜索预览缓存，开始下载")
                cached_posts = self._preview_cache[cache_key]
                matched_posts = len(cached_posts)
            else:
                self.status_changed.emit(f"正在频道中搜索 {tag or '全部帖子'}")

            # 如果有缓存，使用缓存的帖子ID列表
            if cached_posts:
                for cached_post in cached_posts:
                    if self.cancel_event.is_set():
                        break
                    
                    post_id = cached_post.get("post_id")
                    if not post_id:
                        continue
                    
                    try:
                        # 获取完整的帖子对象以下载媒体
                        post = await client.get_messages(entity, ids=post_id)
                        if not post:
                            continue
                        
                        begin_post(post)
                        self.status_changed.emit(f"正在下载帖子 #{post.id} 的评论区图片")
                        
                        # 提取按钮链接
                        if request.extract_button_link:
                            button_link = self._find_button_url(post, request.button_keyword)
                            if button_link:
                                button_text, original_url = button_link
                                target_dir = self._target_dir(request, channel_name, post.id)
                                target_dir.mkdir(parents=True, exist_ok=True)
                                target = target_dir / (
                                    f"post_{post.id}_{safe_name(button_text, '原图链接')}.url"
                                )
                                if target.exists():
                                    if request.skip_duplicates or request.duplicate_mode == "skip":
                                        record_file(post.id, target, False, "原图链接已存在")
                                    else:
                                        if request.duplicate_mode == "rename":
                                            target = self._available_target(target)
                                        self._write_url_shortcut(target, original_url)
                                        record_file(post.id, target, True)
                                else:
                                    self._write_url_shortcut(target, original_url)
                                    record_file(post.id, target, True)

                        if not request.include_replies:
                            await finish_post(post.id)
                            continue

                        try:
                            comment_iter = client.iter_messages(entity, reply_to=post.id)
                            async for comment in comment_iter:
                                if self.cancel_event.is_set():
                                    break
                                if request.only_images and not is_image_message(comment):
                                    continue
                                if not request.only_images and not is_downloadable_message(comment):
                                    continue

                                target_dir = self._target_dir(request, channel_name, post.id)
                                target_dir.mkdir(parents=True, exist_ok=True)
                                raw_filename = self._file_name(
                                    comment,
                                    post.id,
                                    request.filename_template,
                                    request.preserve_original_name,
                                )
                                suffix = Path(raw_filename).suffix
                                stem_limit = max(1, min(request.filename_limit, 255 - len(suffix)))
                                stem = Path(raw_filename).stem[:stem_limit]
                                target = target_dir / f"{stem}{suffix}"
                                if target.exists() or target in reserved_targets:
                                    if request.skip_duplicates or request.duplicate_mode == "skip":
                                        record_file(post.id, target, False, "文件已存在")
                                        continue
                                    if request.duplicate_mode == "rename":
                                        target = self._available_target(target, reserved_targets)
                                elif target in reserved_targets:
                                    await collect_finished(wait_all=True)
                                reserved_targets.add(target)
                                download_task = asyncio.create_task(
                                    self._download_media(
                                        client,
                                        comment,
                                        target,
                                        semaphore,
                                        request.file_download_interval,
                                    )
                                )
                                pending[download_task] = (int(post.id), target)
                                if len(pending) >= max(1, request.concurrency):
                                    await collect_finished()
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
                        entity, search=tag or None, limit=request.max_posts
                ):
                    if self.cancel_event.is_set():
                        break
                    if tag and tag.casefold() not in (post.message or "").casefold():
                        continue
                    if not tag and request.empty_tag_action == "skip":
                        continue

                    matched_posts += 1
                    begin_post(post)
                    self.status_changed.emit(f"正在检查帖子 #{post.id} 的评论")
                    if request.extract_button_link:
                        button_link = self._find_button_url(post, request.button_keyword)
                        if button_link:
                            button_text, original_url = button_link
                            target_dir = self._target_dir(request, channel_name, post.id)
                            target_dir.mkdir(parents=True, exist_ok=True)
                            target = target_dir / (
                                f"post_{post.id}_{safe_name(button_text, '原图链接')}.url"
                            )
                            if target.exists():
                                if request.skip_duplicates or request.duplicate_mode == "skip":
                                    record_file(post.id, target, False, "原图链接已存在")
                                else:
                                    if request.duplicate_mode == "rename":
                                        target = self._available_target(target)
                                    self._write_url_shortcut(target, original_url)
                                    record_file(post.id, target, True)
                            else:
                                self._write_url_shortcut(target, original_url)
                                record_file(post.id, target, True)

                    if not request.include_replies:
                        await finish_post(post.id)
                        continue

                    try:
                        comment_iter = client.iter_messages(entity, reply_to=post.id)
                        async for comment in comment_iter:
                            if self.cancel_event.is_set():
                                break
                            if request.only_images and not is_image_message(comment):
                                continue
                            if not request.only_images and not is_downloadable_message(comment):
                                continue

                            target_dir = self._target_dir(request, channel_name, post.id)
                            target_dir.mkdir(parents=True, exist_ok=True)
                            raw_filename = self._file_name(
                                comment,
                                post.id,
                                request.filename_template,
                                request.preserve_original_name,
                            )
                            suffix = Path(raw_filename).suffix
                            stem_limit = max(1, min(request.filename_limit, 255 - len(suffix)))
                            stem = Path(raw_filename).stem[:stem_limit]
                            target = target_dir / f"{stem}{suffix}"
                            if target.exists() or target in reserved_targets:
                                if request.skip_duplicates or request.duplicate_mode == "skip":
                                    record_file(post.id, target, False, "文件已存在")
                                    continue
                                if request.duplicate_mode == "rename":
                                    target = self._available_target(target, reserved_targets)
                            elif target in reserved_targets:
                                await collect_finished(wait_all=True)
                            reserved_targets.add(target)
                            download_task = asyncio.create_task(
                                self._download_media(
                                    client,
                                    comment,
                                    target,
                                    semaphore,
                                    request.file_download_interval,
                                )
                            )
                            pending[download_task] = (int(post.id), target)
                            if len(pending) >= max(1, request.concurrency):
                                await collect_finished()
                    except errors.RPCError:
                        # 该帖子没有评论区或评论区不可访问，跳过继续处理下一条帖子
                        pass
                    await finish_post(post.id)

            await collect_finished(wait_all=True)

            self.logger.task_completed(
                matched_posts, downloaded, skipped, self.cancel_event.is_set()
            )
            self.scan_finished.emit(matched_posts, downloaded, skipped)
            self.status_changed.emit("任务已取消" if self.cancel_event.is_set() else "下载完成")
        except errors.FloodWaitError as exc:
            self.logger.error(f"Telegram 限流，需要等待 {exc.seconds} 秒")
            self.scan_failed.emit(f"Telegram 要求等待 {exc.seconds} 秒后重试")
        except Exception as exc:
            self.logger.error(f"任务失败: {exc}")
            self.scan_failed.emit(str(exc))
        finally:
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def _preview(self, client: TelegramClient, request: PreviewRequest) -> None:
        self.preview_started.emit()
        
        # 检查缓存
        cache_key = (request.channel.strip(), request.tag.strip())
        if cache_key in self._preview_cache:
            self.preview_progress.emit("正在从缓存加载…")
            await asyncio.sleep(0.3)  # 短暂延迟以显示消息
            self.preview_finished.emit(self._preview_cache[cache_key])
            return
        
        results: list[dict[str, Any]] = []
        try:
            channel_ref = request.channel.strip()
            entity_ref: str | int = (
                int(channel_ref) if channel_ref.lstrip("-").isdigit() else channel_ref
            )
            entity = await client.get_entity(entity_ref)
            channel_name = (
                    getattr(entity, "title", None)
                    or getattr(entity, "username", None)
                    or request.channel
            )
            tag = request.tag.strip()
            self.preview_progress.emit(f"正在搜索 {channel_name} 中的 {tag or '全部帖子'}…")

            async for post in client.iter_messages(
                    entity, search=tag or None, limit=request.max_posts
            ):
                if self.preview_cancel_event.is_set() or len(results) >= request.max_results:
                    break
                text = (post.message or "").strip()
                if tag and tag.casefold() not in text.casefold():
                    continue

                image_count = 0
                thumbnails: list[bytes] = []
                self.preview_progress.emit(f"正在检查帖子 #{post.id} 的评论图片…")
                try:
                    async for comment in client.iter_messages(entity, reply_to=post.id):
                        if self.preview_cancel_event.is_set():
                            break
                        if not is_image_message(comment):
                            continue
                        image_count += 1
                        if len(thumbnails) < request.thumbnails_per_post:
                            thumbnail = await self._thumbnail_bytes(client, comment)
                            if thumbnail:
                                thumbnails.append(thumbnail)
                except errors.RPCError:
                    # Some posts have no linked discussion or comments are unavailable.
                    pass

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
                        "thumbnails": thumbnails,
                    }
                )

            # 保存到缓存
            self._preview_cache[cache_key] = results
            self.preview_finished.emit(results)
        except errors.FloodWaitError as exc:
            self.preview_failed.emit(f"Telegram 要求等待 {exc.seconds} 秒后重试")
        except Exception as exc:
            self.preview_failed.emit(str(exc))

    @staticmethod
    async def _thumbnail_bytes(client: TelegramClient, message: Any) -> bytes | None:
        document = getattr(message, "document", None)
        has_thumbnail = bool(getattr(message, "photo", None)) or bool(
            getattr(document, "thumbs", None)
        )
        if not has_thumbnail:
            return None
        try:
            result = await client.download_media(message, file=bytes, thumb=0)
            return result if isinstance(result, bytes) else None
        except (errors.RPCError, OSError, ValueError):
            return None

    @staticmethod
    async def _download_media(
            client: TelegramClient,
            message: Any,
            target: Path,
            semaphore: asyncio.Semaphore,
            file_download_interval: float,
    ) -> bool:
        async with semaphore:
            result = await client.download_media(message, file=str(target))
            if file_download_interval > 0:
                await asyncio.sleep(file_download_interval)
            return bool(result)

    @staticmethod
    def _find_button_url(message: Any, keyword: str) -> tuple[str, str] | None:
        keyword_folded = keyword.strip().casefold()
        if not keyword_folded:
            return None
        for row in getattr(message, "buttons", None) or []:
            for button in row:
                text = str(getattr(button, "text", "") or "").strip()
                url = str(getattr(button, "url", "") or "").strip()
                if keyword_folded in text.casefold() and url:
                    return text, url
        return None

    @staticmethod
    def _write_url_shortcut(target: Path, url: str) -> None:
        clean_url = url.replace("\r", "").replace("\n", "").strip()
        target.write_text(
            f"[InternetShortcut]\nURL={clean_url}\n",
            encoding="utf-8",
        )

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
