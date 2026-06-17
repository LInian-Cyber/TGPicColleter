"""
tg_extractor.py — Telegram 内部套娃深挖后端
============================================
配合 task.py 中的 JsonConfigDialog 使用。
从帖子正文富文本超链接出发，跨频道追踪目标帖子媒体。

设计原则：
  • 只处理 t.me 内部消息链接；外部链接（http/https 非 t.me）全部丢弃
  • 去重：同一 URL 在一次 deep_dive 中只追踪一次，防止重复下载
  • FloodWait 强制等待，不跳过不重试
  • 所有评论区操作均加 try/except 容错（频道未开评论 / 无权限均视为正常）
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import TYPE_CHECKING

from telethon import types
from telethon.errors import FloodWaitError

if TYPE_CHECKING:
    from telethon import TelegramClient

# ── 精准匹配 Telegram 内部帖子链接的正则表达式 ─────────────────────────────
# 兼容两种形式：
#   公开频道：  t.me/username/123
#   私密频道：  t.me/c/1234567890/123
TG_LINK_PATTERN = re.compile(
    r't\.me/(?:c/)?([^/\s?#]+)/(\d+)',
    re.IGNORECASE,
)
RESOURCE_BUTTON_LABELS = (
    "sfw",
    "nsfw",
    "原图",
    "下载",
    "高清",
    "full size",
    "original",
    "source",
)
RESOURCE_LINK_LABELS = (
    "原图",
    "下载",
    "高清",
    "full size",
    "original",
    "source",
)


# ══════════════════════════════════════════════════════════════════════════════
# 公开入口
# ══════════════════════════════════════════════════════════════════════════════

async def run_advanced_telethon_task(
    client: "TelegramClient",
    message: types.Message,
    params: dict,
) -> int:
    """
    高级任务后端总入口。

    参数
    ----
    client      : 已登录的 TelegramClient 实例
    message     : 任务目标帖子的 telethon Message 对象
    params      : TaskPage._on_start() 发出的 params dict，
                  其中 custom_extract_json 为 JSON 字符串（可为空）
    """
    save_root = params.get("save_root", "").strip()
    custom_json_str = params.get("custom_extract_json", "").strip()

    config: dict = {}
    if custom_json_str:
        try:
            config = json.loads(custom_json_str)
        except json.JSONDecodeError:
            print("⚠️  自定义 JSON 解析失败，回退到常规下载模式。")

    if not config.get("enable_advanced", False):
        # 常规模式：直接下载原帖自带媒体
        if _media_allowed(message, config):
            await client.download_media(message, file=save_root)
            return 1
        return 0

    config["_only_images"] = bool(params.get("only_images", True))
    config["_include_replies"] = bool(params.get("include_replies", True))
    config["_extract_button_link"] = bool(params.get("extract_button_link", True))
    config["_button_keyword"] = str(params.get("button_keyword", "")).strip()
    config["_skip_duplicates"] = bool(params.get("skip_duplicates", True))
    config["_filename_limit"] = max(20, int(params.get("filename_limit", 100)))
    config["_source_tags"] = _extract_hashtags(str(getattr(message, "message", "") or ""))
    config["_download_callback"] = params.get("_advanced_download_callback")
    # 进入递归深挖（主帖初始深度 0）
    stats = {"downloaded": 0}
    seen_urls = params.get("_advanced_seen_urls")
    seen_media = params.get("_advanced_seen_media")
    await _deep_dive(
        client,
        message,
        config,
        save_root,
        depth=0,
        seen_urls=seen_urls if isinstance(seen_urls, set) else set(),
        seen_messages=set(),
        seen_media=seen_media if isinstance(seen_media, set) else set(),
        stats=stats,
    )
    return stats["downloaded"]


# ══════════════════════════════════════════════════════════════════════════════
# 核心递归函数
# ══════════════════════════════════════════════════════════════════════════════

async def _deep_dive(
    client: "TelegramClient",
    message: types.Message,
    config: dict,
    save_path: str,
    depth: int,
    seen_urls: set[str],
    seen_messages: set[tuple[int, int]],
    seen_media: set[tuple[str, int]],
    stats: dict[str, int],
    role: str = "index",
) -> bool:
    """Traverse index posts and download only media reached through resource links."""
    max_depth: int = config.get("follow_tg_links", {}).get("max_depth", 1)
    if depth > max_depth:
        return False

    message_key = _message_identity(message)
    if message_key in seen_messages:
        return False
    seen_messages.add(message_key)

    role_label = "资源帖" if role == "resource" else "索引帖"
    print(
        f"🔍 [深度 {depth}] 正在处理{role_label} ID={message.id} | 保存至: {save_path}"
    )
    os.makedirs(save_path, exist_ok=True)

    follow_cfg: dict = config.get("follow_tg_links", {})
    configured_keywords = [
        str(keyword).casefold()
        for keyword in follow_cfg.get("keywords", [])
        if str(keyword).strip()
    ]
    # Empty configured keywords deliberately means "follow every Telegram link".
    task_keyword = str(config.get("_button_keyword", "")).strip().casefold()
    keywords = list(configured_keywords)
    if configured_keywords and task_keyword and task_keyword not in keywords:
        keywords.append(task_keyword)

    if role == "resource":
        downloaded_here = await _download_resource_message(
            client, message, config, save_path, seen_media, stats
        )
        if downloaded_here:
            return False
        # Some resource links point to another forwarding post before the files.
        for label, url in _unique_links(_message_tg_links(message, keywords)):
            await _follow_tg_link(
                client, label, url, "resource", config, save_path, depth,
                seen_urls, seen_messages, seen_media, stats,
            )
        return False

    # Index posts A/B never download their own media. Body SFW/NSFW links lead
    # to another index; explicit original/download labels lead to resources.
    body_links = _message_tg_links(message, keywords)
    body_links.extend(await _callback_tg_links(client, message))
    for label, url in _unique_links(body_links):
        target_role = _body_link_role(label)
        print(f"    🔗 正文{target_role}链接「{label}」: {url}")
        await _follow_tg_link(
            client, label, url, target_role, config, save_path, depth,
            seen_urls, seen_messages, seen_media, stats,
        )

    if config.get("_include_replies", True):
        await _scan_index_comments(
            client, message, config, save_path, depth,
            seen_urls, seen_messages, seen_media, stats,
        )
    return False


async def _scan_index_comments(
    client: "TelegramClient",
    index_message: types.Message,
    config: dict,
    save_path: str,
    depth: int,
    seen_urls: set[str],
    seen_messages: set[tuple[int, int]],
    seen_media: set[tuple[str, int]],
    stats: dict[str, int],
) -> None:
    """Scan every reached index post's comments; comment links are resources."""
    try:
        input_chat = await index_message.get_input_chat()
        async for comment in client.iter_messages(input_chat, reply_to=index_message.id):
            if _media_allowed(comment, config):
                await _download_resource_message(
                    client, comment, config, save_path, seen_media, stats
                )
            comment_links = _message_tg_links(comment, [])
            comment_links.extend(await _callback_tg_links(client, comment))
            for label, url in _unique_links(comment_links):
                print(f"    💬 评论区资源链接「{label}」: {url}")
                await _follow_tg_link(
                    client, label, url, "resource", config, save_path, depth,
                    seen_urls, seen_messages, seen_media, stats,
                )
    except FloodWaitError as exc:
        print(f"    🛑 扫描评论区受限，等待 {exc.seconds} 秒……")
        await asyncio.sleep(exc.seconds)
    except Exception as exc:
        print(f"    ⚠️ 无法扫描索引帖 #{index_message.id} 评论区: {exc}")


async def _follow_tg_link(
    client: "TelegramClient",
    label: str,
    url: str,
    role: str,
    config: dict,
    save_path: str,
    depth: int,
    seen_urls: set[str],
    seen_messages: set[tuple[int, int]],
    seen_media: set[tuple[str, int]],
    stats: dict[str, int],
) -> None:
    normalized = _normalize_tg_url(url)
    if not normalized or normalized in seen_urls:
        if normalized:
            print(f"    ⏭️ 跳过已处理链接，防止循环: {normalized}")
        return
    seen_urls.add(normalized)
    match = TG_LINK_PATTERN.search(normalized)
    if not match:
        return
    peer_raw, msg_id_text = match.groups()
    peer: str | int = int(f"-100{peer_raw}") if peer_raw.isdigit() else peer_raw
    msg_id = int(msg_id_text)
    print(f"    🚀 [深度 {depth}→{depth + 1}] 跟随{role}链接: {normalized}")
    try:
        target_msg = await asyncio.wait_for(
            client.get_messages(peer, ids=msg_id), timeout=20
        )
        for item in await _expand_album(client, peer, target_msg):
            await _deep_dive(
                client, item, config, save_path, depth + 1,
                seen_urls, seen_messages, seen_media, stats,
                role=role,
            )
    except FloodWaitError as exc:
        print(f"    🛑 Telegram 限流，等待 {exc.seconds} 秒……")
        await asyncio.sleep(exc.seconds)
    except Exception as exc:
        print(f"    ❌ 无法跟随链接「{label}」: {normalized} | {exc}")


async def _expand_album(
    client: "TelegramClient", peer: str | int, message: types.Message | None
) -> list[types.Message]:
    if not message:
        return []
    grouped_id = getattr(message, "grouped_id", None)
    if not grouped_id:
        return [message]
    nearby = await asyncio.wait_for(
        client.get_messages(
            peer, ids=list(range(max(1, int(message.id) - 10), int(message.id) + 11))
        ),
        timeout=20,
    )
    return [
        item for item in nearby
        if item and getattr(item, "grouped_id", None) == grouped_id
    ] or [message]


async def _download_resource_message(
    client: "TelegramClient",
    message: types.Message,
    config: dict,
    save_path: str,
    seen_media: set[tuple[str, int]],
    stats: dict[str, int],
) -> bool:
    if not _media_allowed(message, config):
        return False
    media_key = _media_identity(message)
    if media_key is not None and media_key in seen_media:
        print(f"    ⏭️ 跳过任务中已下载的媒体: {media_key}")
        return True
    download_callback = config.get("_download_callback")
    if callable(download_callback):
        success = bool(await download_callback(message, save_path, config))
    else:
        success = await _download_media(client, message, save_path, config)
    if success:
        stats["downloaded"] += 1
        if media_key is not None:
            seen_media.add(media_key)
        print(f"    📥 真正资源媒体已加入并行下载队列: {media_key or message.id}")
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_tg_url(url: str) -> str | None:
    """
    将各种形式的 t.me 链接规整为统一的 https://t.me/peer/id 形式，
    用于去重比较。非 TG 内部链接返回 None。
    """
    match = TG_LINK_PATTERN.search(url)
    if not match:
        return None
    return f"https://t.me/{match.group(1)}/{match.group(2)}"


def _unique_links(links: list[tuple[str, str]]) -> list[tuple[str, str]]:
    unique: dict[str, str] = {}
    for label, url in links:
        normalized = _normalize_tg_url(url)
        if normalized and normalized not in unique:
            unique[normalized] = label or normalized
    return [(label, url) for url, label in unique.items()]


def _body_link_role(label: str) -> str:
    folded = label.casefold()
    if any(word in folded for word in RESOURCE_LINK_LABELS):
        return "resource"
    return "index"


def _media_allowed(message: types.Message, config: dict) -> bool:
    media_kind = _real_media_kind(message)
    if media_kind is None:
        return False
    if not config.get("_only_images", True):
        return True
    if media_kind == "photo":
        return True
    mime_type = str(getattr(getattr(message, "document", None), "mime_type", "") or "")
    return mime_type.startswith("image/")


async def _download_media(
    client: "TelegramClient", message: types.Message, save_path: str, config: dict
) -> bool:
    if _real_media_kind(message) is None:
        return False
    file_info = getattr(message, "file", None)
    original_name = os.path.basename(str(getattr(file_info, "name", "") or ""))
    extension = str(getattr(file_info, "ext", "") or "")
    if not extension and getattr(message, "photo", None):
        extension = ".jpg"
    filename = original_name or f"media_{message.chat_id}_{message.id}{extension}"
    target = os.path.join(save_path, filename)
    if os.path.exists(target):
        target = _tagged_available_path(
            target,
            config.get("_source_tags", []),
            int(config.get("_filename_limit", 100)),
        )
    result = await client.download_media(message, file=target)
    return bool(result)


def _real_media_kind(message: types.Message) -> str | None:
    media = getattr(message, "media", None)
    if isinstance(media, types.MessageMediaPhoto) and getattr(media, "photo", None):
        return "photo"
    if isinstance(media, types.MessageMediaDocument) and getattr(media, "document", None):
        return "document"
    return None


def _media_identity(message: types.Message) -> tuple[str, int] | None:
    media_kind = _real_media_kind(message)
    if media_kind == "photo":
        media_id = getattr(getattr(message, "photo", None), "id", None)
    elif media_kind == "document":
        media_id = getattr(getattr(message, "document", None), "id", None)
    else:
        return None
    return (media_kind, int(media_id)) if media_id is not None else None


def _message_identity(message: types.Message) -> tuple[int, int]:
    return (
        int(getattr(message, "chat_id", 0) or 0),
        int(getattr(message, "id", 0) or 0),
    )


def _message_tg_links(message: types.Message, keywords: list[str]) -> list[tuple[str, str]]:
    """Collect Telegram post URLs from body entities, buttons and web previews."""
    raw_text = str(getattr(message, "message", "") or "")
    body_matches = not keywords or any(keyword in raw_text.casefold() for keyword in keywords)
    links: list[tuple[str, str]] = []
    try:
        entities_text = message.get_entities_text()
    except (AttributeError, TypeError, ValueError):
        entities_text = []
    for entity, entity_text in entities_text:
        visible_text = str(entity_text or "").strip()
        url = str(getattr(entity, "url", "") or "").strip()
        if not url and isinstance(entity, types.MessageEntityUrl):
            url = visible_text
        label_matches = not keywords or any(
            keyword in visible_text.casefold() for keyword in keywords
        )
        if TG_LINK_PATTERN.search(url) and (label_matches or body_matches):
            links.append((visible_text, url))
    for url in re.findall(
        r"(?:https?://)?t\.me/(?:c/)?[^/\s?#)]+/\d+",
        raw_text,
        flags=re.IGNORECASE,
    ):
        if body_matches:
            links.append((url, url))

    for row in getattr(message, "buttons", None) or []:
        for button in row:
            label = str(getattr(button, "text", "") or "").strip()
            url = str(getattr(button, "url", "") or "").strip()
            label_matches = not keywords or any(
                keyword in label.casefold() for keyword in keywords
            )
            if TG_LINK_PATTERN.search(url) and (label_matches or body_matches):
                links.append((label or url, url))
            elif url and any(
                word in label.casefold()
                for word in ("sfw", "nsfw", "原图", "下载", "full size")
            ):
                print(f"    ⚠️ 资源按钮「{label}」不是 Telegram 帖子链接: {url}")

    reply_markup = getattr(message, "reply_markup", None)
    for row in getattr(reply_markup, "rows", None) or []:
        for button in getattr(row, "buttons", None) or []:
            label = str(getattr(button, "text", "") or "").strip()
            url = str(getattr(button, "url", "") or "").strip()
            label_matches = not keywords or any(
                keyword in label.casefold() for keyword in keywords
            )
            if TG_LINK_PATTERN.search(url) and (label_matches or body_matches):
                links.append((label or url, url))
            elif url and any(
                word in label.casefold()
                for word in ("sfw", "nsfw", "原图", "下载", "full size")
            ):
                print(f"    ⚠️ 资源按钮「{label}」不是 Telegram 帖子链接: {url}")

    media = getattr(message, "media", None)
    webpage = getattr(media, "webpage", None)
    preview_url = str(getattr(webpage, "url", "") or "").strip()
    preview_title = str(
        getattr(webpage, "title", "") or getattr(webpage, "site_name", "") or ""
    ).strip()
    preview_matches = not keywords or any(
        keyword in f"{preview_title} {preview_url}".casefold() for keyword in keywords
    )
    if TG_LINK_PATTERN.search(preview_url) and (preview_matches or body_matches):
        links.append((preview_title or preview_url, preview_url))
    return links


async def _callback_tg_links(
    client: "TelegramClient", message: types.Message
) -> list[tuple[str, str]]:
    """Click safe resource callback buttons and collect links they reveal."""
    links: list[tuple[str, str]] = []
    reply_markup = getattr(message, "reply_markup", None)
    for row in getattr(reply_markup, "rows", None) or []:
        for button in getattr(row, "buttons", None) or []:
            label = str(getattr(button, "text", "") or "").strip()
            data = getattr(button, "data", None)
            if not data or not any(
                word in label.casefold() for word in RESOURCE_BUTTON_LABELS
            ):
                continue
            try:
                answer = await asyncio.wait_for(message.click(data=data), timeout=8)
                answer_url = str(getattr(answer, "url", "") or "").strip()
                if TG_LINK_PATTERN.search(answer_url):
                    links.append((label, answer_url))
                answer_text = str(getattr(answer, "message", "") or "")
                for url in _tg_urls_from_text(answer_text):
                    links.append((label, url))

                await asyncio.sleep(0.4)
                refreshed = await asyncio.wait_for(
                    client.get_messages(
                        getattr(message, "chat_id", None), ids=int(message.id)
                    ),
                    timeout=8,
                )
                if refreshed:
                    links.extend(_message_tg_links(refreshed, []))
            except asyncio.TimeoutError:
                print(f"    ⚠️ 点击资源按钮「{label}」超时，已跳过避免任务卡住")
            except FloodWaitError as exc:
                print(f"    🛑 点击资源按钮受限，等待 {exc.seconds} 秒……")
                await asyncio.sleep(exc.seconds)
            except Exception as exc:
                print(f"    ⚠️ 无法点击资源按钮「{label}」: {exc}")
    return links


def _tg_urls_from_text(text: str) -> list[str]:
    return re.findall(
        r"(?:https?://)?t\.me/(?:c/)?[^/\s?#)]+/\d+",
        text,
        flags=re.IGNORECASE,
    )


def _extract_hashtags(text: str) -> list[str]:
    tags: list[str] = []
    for tag in re.findall(r"(?<![\w#])#([\w]+)", text, flags=re.UNICODE):
        cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", tag).strip(" .")[:60]
        if cleaned and cleaned not in tags:
            tags.append(cleaned)
    return tags


def _tagged_available_path(target: str, tags: list[str], filename_limit: int) -> str:
    directory, filename = os.path.split(target)
    stem, suffix = os.path.splitext(filename)
    max_stem_length = max(1, min(filename_limit, 255 - len(suffix)))
    for tag in tags:
        tag_limit = max(1, max_stem_length - 2)
        prefix = f"{tag[:tag_limit]}_"
        stem_limit = max(1, max_stem_length - len(prefix))
        candidate = os.path.join(directory, f"{prefix}{stem[:stem_limit]}{suffix}")
        if not os.path.exists(candidate):
            return candidate
    index = 2
    while True:
        tail = f"_{index}"
        stem_limit = max(1, max_stem_length - len(tail))
        candidate = os.path.join(directory, f"{stem[:stem_limit]}{tail}{suffix}")
        if not os.path.exists(candidate):
            return candidate
        index += 1
