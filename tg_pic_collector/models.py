from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
    file_download_interval: float = 1.0
    filename_limit: int = 100
    empty_tag_action: str = "uncategorized"  # uncategorized | skip | channel

@dataclass(frozen=True)
class PreviewRequest:
    channel: str
    tag: str
    max_posts: int
    max_results: int = 30
    thumbnails_per_post: int = 4


SAVE_MODE_LABELS = {
    "channel_tag": "按频道 / Tag 建立文件夹",
    "tag": "按 Tag 建立文件夹",
    "post": "按 Tag / 帖子建立文件夹",
    "flat": "全部保存到同一文件夹",
}
