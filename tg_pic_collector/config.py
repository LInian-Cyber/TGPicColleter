from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from .store import AppStore


DEFAULT_SAVE_ROOT = str(Path.home() / "Pictures" / "TG Pic Collector")
DEFAULT_MAX_POSTS = 100
DEFAULT_PREVIEW_MAX_RESULTS = 50
DEFAULT_CONCURRENCY = 6
DEFAULT_CHUNK_CONCURRENCY = 1
DEFAULT_FILE_DOWNLOAD_INTERVAL = 0.5
DEFAULT_FILENAME_LIMIT = 100
STORE_BACKED_FIELDS = {
    "history",
    "yande_tag_history",
    "last_task_state",
    "channel_history",
    "account_sessions",
}
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def _safe_fs_name(value: str, fallback: str = "default") -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value or "").strip(" .")
    if not name:
        name = fallback
    if name.upper() in WINDOWS_RESERVED_NAMES:
        name = f"_{name}"
    return name


def _stable_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass
class AppConfig:
    api_id: str = ""
    api_hash: str = ""
    phone: str = ""
    channel: str = ""
    tag: str = ""
    save_root: str = DEFAULT_SAVE_ROOT
    save_mode: str = "channel_tag"
    max_posts: int = DEFAULT_MAX_POSTS
    preview_max_results: int = DEFAULT_PREVIEW_MAX_RESULTS
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
    concurrency: int = DEFAULT_CONCURRENCY
    chunk_concurrency: int = DEFAULT_CHUNK_CONCURRENCY
    file_download_interval: float = DEFAULT_FILE_DOWNLOAD_INTERVAL
    filename_limit: int = DEFAULT_FILENAME_LIMIT
    empty_tag_action: str = "uncategorized"
    restore_on_launch: bool = True
    use_last_mode: bool = True
    auto_fill_tag: bool = True
    enable_animations: bool = True
    enable_rounded_corners: bool = True
    enable_system_notifications: bool = True
    close_behavior: str = "ask"
    remember_close_behavior: bool = False
    use_dpapi_encryption: bool = True
    save_extended_info: bool = False
    save_telegraph_images: bool = False
    yande_cookie: str = ""
    yande_tags: str = ""
    yande_tag_history: list[str] | None = None
    use_system_proxy: bool = True
    proxy_url: str = ""
    last_task_state: dict | None = None
    channel_history: list[dict] | None = None
    advanced_rules: list[dict] | None = None
    account_sessions: list[dict] | None = None

    @property
    def config_dir(self) -> Path:
        root = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
        return Path(root) / "TGCommentCollector"

    @property
    def session_path(self) -> Path:
        safe_session = _safe_fs_name(self.session_name, "default")
        root = Path(self.session_dir).expanduser() if self.session_dir else self.config_dir / "sessions"
        return root / safe_session

    @staticmethod
    def account_key(session_name: str, session_dir: str = "") -> str:
        safe_session = (session_name or "default").strip() or "default"
        safe_dir = str(session_dir or "").strip()
        return f"{safe_dir}::{safe_session}"

    @property
    def current_account_key(self) -> str:
        return self.account_key(self.session_name, self.session_dir)

    @property
    def store(self) -> AppStore:
        store = self.__dict__.get("_store")
        if store is None:
            store = AppStore(self.config_dir / "app_state.sqlite3")
            self.__dict__["_store"] = store
        return store

    def save(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.save_runtime_fields(*STORE_BACKED_FIELDS)
        payload = {
            key: value
            for key, value in asdict(self).items()
            if key not in STORE_BACKED_FIELDS
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        config_path = self.config_dir / "config.json"
        try:
            if config_path.exists() and config_path.read_text(encoding="utf-8") == content:
                return
        except OSError:
            pass
        tmp_path = config_path.with_name(f"{config_path.name}.tmp")
        tmp_path.write_text(
            content,
            encoding="utf-8",
        )
        tmp_path.replace(config_path)

    def save_runtime_fields(self, *fields: str) -> None:
        for field_name in fields:
            if not self._runtime_field_changed(field_name):
                continue
            if field_name == "history" and self.history is not None:
                self.history = self.store.replace_history(self.history)
            elif field_name == "yande_tag_history" and self.yande_tag_history is not None:
                self.yande_tag_history = self.store.replace_yande_tag_history(
                    self.yande_tag_history
                )
            elif field_name == "channel_history" and self.channel_history is not None:
                self.channel_history = self.store.replace_channel_cache(
                    self.channel_history
                )
            elif field_name == "account_sessions" and self.account_sessions is not None:
                self.account_sessions = self.store.replace_account_sessions(
                    self.account_sessions
                )
            elif field_name == "last_task_state":
                self.store.set_runtime_state("last_task_state", self.last_task_state)
            self._mark_runtime_field_clean(field_name)

    def _runtime_field_changed(self, field_name: str) -> bool:
        signatures = self.__dict__.setdefault("_runtime_signatures", {})
        return signatures.get(field_name) != _stable_json(
            getattr(self, field_name, None)
        )

    def _mark_runtime_field_clean(self, field_name: str) -> None:
        signatures = self.__dict__.setdefault("_runtime_signatures", {})
        signatures[field_name] = _stable_json(getattr(self, field_name, None))

    def load_runtime_state(self) -> None:
        self.history = self.store.list_history()
        self.yande_tag_history = self.store.list_yande_tag_history()
        self.channel_history = self.store.list_channel_cache()
        self.account_sessions = self.store.list_account_sessions()
        state = self.store.get_runtime_state("last_task_state")
        if state is not None:
            self.last_task_state = state
        for field_name in STORE_BACKED_FIELDS:
            self._mark_runtime_field_clean(field_name)

    def add_history(self, record: dict) -> None:
        self.history = self.store.add_history(record, limit=100)
        self._mark_runtime_field_clean("history")

    def add_yande_tag_history(self, tags: str) -> None:
        values = [
            part.strip("# ")
            for part in re.split(r"[\s,]+", tags or "")
            if part.strip("# ")
        ]
        if not values:
            return
        history = list(self.yande_tag_history or [])
        for tag in reversed(values):
            if tag in history:
                history.remove(tag)
            history.insert(0, tag)
        self.yande_tag_history = self.store.replace_yande_tag_history(
            history[:30]
        )
        self._mark_runtime_field_clean("yande_tag_history")

    def add_channel_to_history(
        self,
        channel_id: str,
        channel_name: str = "",
        avatar_bytes: bytes = b"",
        channel_link: str = "",
    ) -> None:
        history = list(self.channel_history or [])
        channel_id = str(channel_id or "").strip()
        channel_name = str(channel_name or "").strip()
        channel_link = str(channel_link or "").strip() or self._channel_display_link(channel_id)
        if not channel_id:
            return

        for index, item in enumerate(history):
            if item.get("id") == channel_id:
                item["name"] = channel_name or item.get("name", "")
                item["link"] = channel_link or item.get("link", "")
                if avatar_bytes:
                    avatar_path = self._save_channel_avatar(channel_id, avatar_bytes)
                    if avatar_path:
                        item["avatar_path"] = avatar_path
                        item["avatar_updated_at"] = datetime.now().isoformat(timespec="seconds")
                history.insert(0, history.pop(index))
                self.channel_history = self.store.replace_channel_cache(
                    history[:20]
                )
                self._mark_runtime_field_clean("channel_history")
                return

        avatar_path = ""
        if avatar_bytes:
            avatar_path = self._save_channel_avatar(channel_id, avatar_bytes)

        history.insert(
            0,
            {
                "id": channel_id,
                "name": channel_name,
                "link": channel_link,
                "avatar_path": avatar_path,
                "avatar_updated_at": datetime.now().isoformat(timespec="seconds")
                if avatar_path
                else "",
            },
        )
        self.channel_history = self.store.replace_channel_cache(history[:20])
        self._mark_runtime_field_clean("channel_history")

    @staticmethod
    def _channel_display_link(channel_id: str) -> str:
        if channel_id.startswith("@") and len(channel_id) > 1:
            return f"https://t.me/{channel_id[1:]}"
        if channel_id.startswith("-100") and channel_id[4:].isdigit():
            return f"https://t.me/c/{channel_id[4:]}"
        return channel_id

    def _save_channel_avatar(self, channel_id: str, avatar_bytes: bytes) -> str:
        if not avatar_bytes:
            return ""
        avatar_dir = self.config_dir / "channel_avatars"
        avatar_dir.mkdir(parents=True, exist_ok=True)
        safe_id = _safe_fs_name(re.sub(r"[@-]", "_", channel_id), "channel")
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
                self.account_sessions = self.store.replace_account_sessions(
                    sessions[:12]
                )
                self._mark_runtime_field_clean("account_sessions")
                return

        sessions.insert(0, payload)
        self.account_sessions = self.store.replace_account_sessions(sessions[:12])
        self._mark_runtime_field_clean("account_sessions")

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
            self.account_sessions = self.store.replace_account_sessions(
                self.account_sessions
            )
            self._mark_runtime_field_clean("account_sessions")
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
        result = []
        for item in list(self.channel_history or []):
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
                    "id": item.get("id", ""),
                    "name": item.get("name", ""),
                    "link": item.get("link", "")
                    or self._channel_display_link(str(item.get("id", ""))),
                    "avatar": avatar_bytes,
                }
            )
        return result

    @classmethod
    def load(cls) -> "AppConfig":
        probe = cls()
        path = probe.config_dir / "config.json"
        if not path.exists():
            probe.load_runtime_state()
            return probe
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if "file_download_interval" not in payload and "request_interval" in payload:
                payload["file_download_interval"] = payload["request_interval"]
            valid = {
                key: value
                for key, value in payload.items()
                if key in cls.__dataclass_fields__
            }
            config = cls(**valid)
            config.store.migrate_from_config_payload(payload)
            config.load_runtime_state()
            return config
        except (OSError, ValueError, TypeError):
            probe.load_runtime_state()
            return probe
