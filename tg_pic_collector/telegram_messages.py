from __future__ import annotations

import re
from typing import Any

from telethon import TelegramClient, types

from .models import normalize_channel_reference


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def safe_name(value: str, fallback: str = "untitled", max_length: int = 90) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    value = value[:max_length].rstrip(" .")
    if not value:
        return fallback
    if value.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        value = f"_{value}"
    return value[:max_length].rstrip(" .") or fallback


def is_webpage_preview(message: Any) -> bool:
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
    return mime_type == "video/webm" and "DocumentAttributeAnimated" in attr_names


def real_media_kind(message: Any) -> str | None:
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
