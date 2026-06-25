from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


def normalize_channel_reference(value: str) -> str:
    """Convert Telegram channel URLs into references Telethon can resolve."""
    raw = value.strip()
    if not raw:
        return raw

    url = raw.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    private_match = re.fullmatch(
        r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/c/(\d+)(?:/\d+)?",
        url,
        flags=re.IGNORECASE,
    )
    if private_match:
        return f"-100{private_match.group(1)}"

    public_match = re.fullmatch(
        r"(?:https?://)?(?:www\.)?(?:t|telegram)\.me/(?:s/)?"
        r"([A-Za-z][A-Za-z0-9_]{2,})(?:/\d+)?",
        url,
        flags=re.IGNORECASE,
    )
    if public_match:
        username = public_match.group(1)
        if username.casefold() not in {
            "addlist",
            "addstickers",
            "joinchat",
            "login",
            "proxy",
            "share",
        }:
            return f"@{username}"

    return raw


@dataclass(frozen=True)
class TelegramCredentials:
    api_id: int
    api_hash: str
    phone: str
    session_path: Path


@dataclass(frozen=True)
class ScanRequest:
    channel: str
    tag: str
    save_root: Path
    save_mode: str
    max_posts: int
    skip_duplicates: bool = True
    duplicate_mode: str = "skip"
    preserve_original_name: bool = True
    filename_template: str = "{date}_post{post_id}_comment{comment_id}"
    extract_button_link: bool = True
    button_keyword: str = "原图"
    only_images: bool = True
    include_replies: bool = True
    concurrency: int = 6
    file_download_interval: float = 0.5
    filename_limit: int = 100
    empty_tag_action: str = "uncategorized"  # uncategorized | skip | channel
    custom_extract_json: str = ""             # 高级套娃提取规则 JSON（空字符串=不启用）
    chunk_concurrency: int = 1               # 单文件分片并发数（1=关闭分片，建议 2-8）
    save_extended_info: bool = False
    date_from: str = ""
    date_to: str = ""

    resume_post_ids: tuple[int, ...] = ()

@dataclass(frozen=True)
class PreviewRequest:
    channel: str
    tag: str
    max_posts: int
    max_results: int = 50
    thumbnails_per_post: int = 4
    include_replies: bool = True
    extract_button_link: bool = True
    button_keyword: str = "原图"
    custom_extract_json: str = ""
    date_from: str = ""
    date_to: str = ""


SAVE_MODE_LABELS = {
    "channel_tag": "按频道 / Tag 建立文件夹",
    "tag": "按 Tag 建立文件夹",
    "post": "按 Tag / 帖子建立文件夹",
    "flat": "全部保存到同一文件夹",
}
