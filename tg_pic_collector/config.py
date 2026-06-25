from __future__ import annotations

import json
import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime
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
    close_behavior: str = "ask"  # ask | minimize | exit
    remember_close_behavior: bool = False
    use_dpapi_encryption: bool = True
    save_extended_info: bool = False
    last_task_state: dict | None = None
    channel_history: list[dict] | None = None  # [{"name": "频道名", "id": "@username", "link": "https://t.me/xxx", "avatar_path": "..."}]
    advanced_rules: list[dict] | None = None  # [{"name": str, "description": str, "json": str}]
    account_sessions: list[dict] | None = None  # [{"key": str, "session_name": str, "name": str, "phone": str, "avatar_path": "..."}]

    @property
    def config_dir(self) -> Path:
        root = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
        return Path(root) / "TGCommentCollector"

    @property
    def session_path(self) -> Path:
        safe_session = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", self.session_name).strip(" .")
        root = Path(self.session_dir).expanduser() if self.session_dir else self.config_dir / "sessions"
        return root / (safe_session or "default")

    @staticmethod
    def account_key(session_name: str, session_dir: str = "") -> str:
        safe_session = (session_name or "default").strip() or "default"
        safe_dir = str(session_dir or "").strip()
        return f"{safe_dir}::{safe_session}"

    @property
    def current_account_key(self) -> str:
        return self.account_key(self.session_name, self.session_dir)

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
                        item["avatar_updated_at"] = datetime.now().isoformat(timespec="seconds")
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
            "avatar_updated_at": datetime.now().isoformat(timespec="seconds") if avatar_path else "",
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

    def add_account_session(
        self,
        session_name: str,
        session_dir: str = "",
        name: str = "",
        phone: str = "",
        avatar_bytes: bytes = b"",
    ) -> None:
        session_name = (session_name or "default").strip() or "default"
        session_dir = str(session_dir or "").strip()
        key = self.account_key(session_name, session_dir)
        sessions = list(self.account_sessions or [])
        payload = {
            "key": key,
            "session_name": session_name,
            "session_dir": session_dir,
            "name": str(name or "").strip(),
            "phone": str(phone or "").strip(),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        if avatar_bytes:
            avatar_path = self._save_account_avatar(key, avatar_bytes)
            if avatar_path:
                payload["avatar_path"] = avatar_path
                payload["avatar_updated_at"] = datetime.now().isoformat(timespec="seconds")

        for index, item in enumerate(sessions):
            if item.get("key") == key:
                merged = dict(item)
                for field, value in payload.items():
                    if value or field in {"key", "session_name", "session_dir", "updated_at"}:
                        merged[field] = value
                sessions.insert(0, sessions.pop(index))
                sessions[0] = merged
                self.account_sessions = sessions[:12]
                self.save()
                return

        sessions.insert(0, payload)
        self.account_sessions = sessions[:12]
        self.save()

    def remove_account_session(self, key: str) -> bool:
        sessions = list(self.account_sessions or [])
        kept: list[dict] = []
        removed = False
        for item in sessions:
            if item.get("key") == key:
                removed = True
                avatar_path = item.get("avatar_path")
                if avatar_path:
                    try:
                        Path(avatar_path).unlink(missing_ok=True)
                    except OSError:
                        pass
                continue
            kept.append(item)
        self.account_sessions = kept
        if removed:
            self.save()
        return removed

    def _save_account_avatar(self, key: str, avatar_bytes: bytes) -> str:
        if not avatar_bytes:
            return ""
        avatar_dir = self.config_dir / "account_avatars"
        avatar_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha1(key.encode("utf-8", errors="ignore")).hexdigest()[:16]
        avatar_path = avatar_dir / f"{digest}.jpg"
        try:
            avatar_path.write_bytes(avatar_bytes)
            return str(avatar_path)
        except OSError:
            return ""

    def get_account_sessions_with_avatars(self) -> list[dict]:
        result: list[dict] = []
        for item in list(self.account_sessions or []):
            avatar_bytes = b""
            avatar_path = item.get("avatar_path", "")
            if avatar_path:
                try:
                    path = Path(avatar_path)
                    if path.exists():
                        avatar_bytes = path.read_bytes()
                except OSError:
                    pass
            result.append(
                {
                    "key": item.get("key", ""),
                    "session_name": item.get("session_name", "default"),
                    "session_dir": item.get("session_dir", ""),
                    "name": item.get("name", ""),
                    "phone": item.get("phone", ""),
                    "avatar": avatar_bytes,
                    "updated_at": item.get("updated_at", ""),
                }
            )
        return result
    
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
