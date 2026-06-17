from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from PySide6.QtCore import QStandardPaths


@dataclass
class AppConfig:
    api_id: str = ""
    api_hash: str = ""
    phone: str = ""
    channel: str = ""
    tag: str = ""
    save_root: str = str(Path.home() / "Pictures" / "TG Pic Collector")
    save_mode: str = "channel_tag"
    max_posts: int = 100
    preview_max_results: int = 50
    session_name: str = "default"
    session_dir: str = ""
    skip_duplicates: bool = True
    duplicate_mode: str = "skip"
    open_after_download: bool = False
    preserve_original_name: bool = True
    filename_template: str = "{date}_post{post_id}_comment{comment_id}"
    theme_mode: str = "auto"
    lang: str = "zh_CN"
    history: list[dict] | None = None
    concurrency: int = 6
    file_download_interval: float = 0.5
    filename_limit: int = 100
    empty_tag_action: str = "uncategorized"
    restore_on_launch: bool = True
    use_last_mode: bool = True
    auto_fill_tag: bool = True
    enable_animations: bool = True
    enable_rounded_corners: bool = True
    enable_system_notifications: bool = True
    use_dpapi_encryption: bool = True
    last_task_state: dict | None = None
    channel_history: list[dict] | None = None  # [{"name": "频道名", "id": "@username", "link": "https://t.me/xxx", "avatar_path": "..."}]
    advanced_rules: list[dict] | None = None  # [{"name": str, "description": str, "json": str}]

    @property
    def config_dir(self) -> Path:
        root = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
        return Path(root) / "TGCommentCollector"

    @property
    def session_path(self) -> Path:
        safe_session = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", self.session_name).strip(" .")
        root = Path(self.session_dir).expanduser() if self.session_dir else self.config_dir / "sessions"
        return root / (safe_session or "default")

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        (self.config_dir / "config.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_history(self, record: dict) -> None:
        history = list(self.history or [])
        history.insert(0, record)
        self.history = history[:100]
        self.save()

    def add_channel_to_history(
        self,
        channel_id: str,
        channel_name: str = "",
        avatar_bytes: bytes = b"",
        channel_link: str = "",
    ) -> None:
        """添加频道到历史记录"""
        history = list(self.channel_history or [])
        channel_id = str(channel_id or "").strip()
        channel_name = str(channel_name or "").strip()
        channel_link = str(channel_link or "").strip() or self._channel_display_link(channel_id)
        if not channel_id:
            return
        
        # 检查是否已存在
        for index, item in enumerate(history):
            if item.get("id") == channel_id:
                # 更新已存在的记录
                item["name"] = channel_name or item.get("name", "")
                item["link"] = channel_link or item.get("link", "")
                if avatar_bytes:
                    avatar_path = self._save_channel_avatar(channel_id, avatar_bytes)
                    if avatar_path:
                        item["avatar_path"] = avatar_path
                # 最近搜索过的频道放到最前面，方便下次直接选。
                history.insert(0, history.pop(index))
                self.channel_history = history
                self.save()
                return
        
        # 保存头像到本地
        avatar_path = ""
        if avatar_bytes:
            avatar_path = self._save_channel_avatar(channel_id, avatar_bytes)
        
        # 添加新记录
        history.insert(0, {
            "id": channel_id,
            "name": channel_name,
            "link": channel_link,
            "avatar_path": avatar_path,
        })
        self.channel_history = history[:20]  # 最多保存20个频道
        self.save()

    @staticmethod
    def _channel_display_link(channel_id: str) -> str:
        if channel_id.startswith("@") and len(channel_id) > 1:
            return f"https://t.me/{channel_id[1:]}"
        if channel_id.startswith("-100") and channel_id[4:].isdigit():
            return f"https://t.me/c/{channel_id[4:]}"
        return channel_id
    
    def _save_channel_avatar(self, channel_id: str, avatar_bytes: bytes) -> str:
        """保存频道头像到本地，返回相对路径"""
        if not avatar_bytes:
            return ""
        
        # 创建头像缓存目录
        avatar_dir = self.config_dir / "channel_avatars"
        avatar_dir.mkdir(parents=True, exist_ok=True)
        
        # 使用频道ID作为文件名（安全化）
        safe_id = re.sub(r'[<>:"/\\|?*\x00-\x1f@-]', "_", channel_id).strip(" .")
        avatar_path = avatar_dir / f"{safe_id}.jpg"
        
        try:
            avatar_path.write_bytes(avatar_bytes)
            return str(avatar_path)
        except OSError:
            return ""
    
    def get_channel_history_with_avatars(self) -> list[dict]:
        """获取频道历史记录，包含头像字节数据"""
        history = list(self.channel_history or [])
        result = []
        
        for item in history:
            avatar_bytes = b""
            avatar_path = item.get("avatar_path", "")
            if avatar_path:
                try:
                    path = Path(avatar_path)
                    if path.exists():
                        avatar_bytes = path.read_bytes()
                except OSError:
                    pass
            
            result.append({
                "id": item.get("id", ""),
                "name": item.get("name", ""),
                "link": item.get("link", "") or self._channel_display_link(str(item.get("id", ""))),
                "avatar": avatar_bytes,
            })
        
        return result

    @classmethod
    def load(cls) -> "AppConfig":
        probe = cls()
        path = probe.config_dir / "config.json"
        if not path.exists():
            return probe
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if "file_download_interval" not in payload and "request_interval" in payload:
                payload["file_download_interval"] = payload["request_interval"]
            valid = {key: value for key, value in payload.items() if key in cls.__dataclass_fields__}
            return cls(**valid)
        except (OSError, ValueError, TypeError):
            return probe
