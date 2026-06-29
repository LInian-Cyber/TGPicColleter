from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STORE_SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


class AppStore:
    """SQLite-backed runtime data store.

    The config file should stay focused on durable user settings. Runtime data
    such as history, caches, and task snapshots lives here so frequent updates
    do not rewrite the whole JSON config file.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tag_history (
                    tag TEXT PRIMARY KEY,
                    position INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS channel_cache (
                    channel_id TEXT PRIMARY KEY,
                    position INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS account_sessions (
                    account_key TEXT PRIMARY KEY,
                    position INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS runtime_state (
                    key TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO store_meta(key, value)
                VALUES('schema_version', ?)
                """,
                (str(STORE_SCHEMA_VERSION),),
            )
        self._initialized = True

    def _get_meta(self, key: str) -> str:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM store_meta WHERE key = ?",
                (key,),
            ).fetchone()
        return str(row["value"]) if row else ""

    def _set_meta(self, key: str, value: str) -> None:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO store_meta(key, value) VALUES(?, ?)",
                (key, value),
            )

    def migrate_from_config_payload(self, payload: dict[str, Any]) -> None:
        if self._get_meta("config_runtime_migrated") == "1":
            return
        if isinstance(payload.get("history"), list):
            self.replace_history(payload["history"])
        if isinstance(payload.get("yande_tag_history"), list):
            self.replace_yande_tag_history(payload["yande_tag_history"])
        if isinstance(payload.get("channel_history"), list):
            self.replace_channel_cache(payload["channel_history"])
        if isinstance(payload.get("account_sessions"), list):
            self.replace_account_sessions(payload["account_sessions"])
        if isinstance(payload.get("last_task_state"), dict):
            self.set_runtime_state("last_task_state", payload["last_task_state"])
        self._set_meta("config_runtime_migrated", "1")

    def list_history(self, limit: int = 100) -> list[dict]:
        self.initialize()
        rows = []
        with self._connect() as conn:
            for row in conn.execute(
                "SELECT payload FROM history ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ):
                value = _json_loads(str(row["payload"]), {})
                if isinstance(value, dict):
                    rows.append(value)
        return rows

    def add_history(self, record: dict, limit: int = 100) -> list[dict]:
        self.initialize()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO history(payload, created_at) VALUES(?, ?)",
                (_json_dumps(dict(record)), _now()),
            )
            conn.execute(
                """
                DELETE FROM history
                WHERE id NOT IN (
                    SELECT id FROM history ORDER BY id DESC LIMIT ?
                )
                """,
                (int(limit),),
            )
        return self.list_history(limit)

    def replace_history(self, records: Iterable[dict], limit: int = 100) -> list[dict]:
        clean_records = [
            dict(item)
            for item in list(records or [])[: int(limit)]
            if isinstance(item, dict)
        ]
        self.initialize()
        with self._connect() as conn:
            conn.execute("DELETE FROM history")
            for record in reversed(clean_records):
                conn.execute(
                    "INSERT INTO history(payload, created_at) VALUES(?, ?)",
                    (_json_dumps(record), _history_created_at(record)),
                )
        return self.list_history(limit)

    def list_yande_tag_history(self, limit: int = 30) -> list[str]:
        self.initialize()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tag FROM tag_history
                ORDER BY position ASC, updated_at DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [str(row["tag"]) for row in rows if str(row["tag"]).strip()]

    def replace_yande_tag_history(self, tags: Iterable[str], limit: int = 30) -> list[str]:
        clean_tags: list[str] = []
        for tag in tags or []:
            value = str(tag or "").strip()
            if value and value not in clean_tags:
                clean_tags.append(value)
            if len(clean_tags) >= int(limit):
                break
        self.initialize()
        now = _now()
        with self._connect() as conn:
            conn.execute("DELETE FROM tag_history")
            for position, tag in enumerate(clean_tags):
                conn.execute(
                    """
                    INSERT INTO tag_history(tag, position, updated_at)
                    VALUES(?, ?, ?)
                    """,
                    (tag, position, now),
                )
        return self.list_yande_tag_history(limit)

    def list_channel_cache(self, limit: int = 20) -> list[dict]:
        return self._list_payload_table(
            "channel_cache",
            "position ASC, updated_at DESC",
            limit,
        )

    def replace_channel_cache(self, channels: Iterable[dict], limit: int = 20) -> list[dict]:
        clean_channels: list[dict] = []
        seen: set[str] = set()
        for item in channels or []:
            if not isinstance(item, dict):
                continue
            channel_id = str(item.get("id", "") or "").strip()
            if not channel_id or channel_id in seen:
                continue
            seen.add(channel_id)
            clean_channels.append(dict(item))
            if len(clean_channels) >= int(limit):
                break
        self._replace_payload_table(
            "channel_cache",
            "channel_id",
            clean_channels,
            lambda item: str(item.get("id", "") or "").strip(),
        )
        return self.list_channel_cache(limit)

    def list_account_sessions(self, limit: int = 12) -> list[dict]:
        return self._list_payload_table(
            "account_sessions",
            "position ASC, updated_at DESC",
            limit,
        )

    def replace_account_sessions(self, sessions: Iterable[dict], limit: int = 12) -> list[dict]:
        clean_sessions: list[dict] = []
        seen: set[str] = set()
        for item in sessions or []:
            if not isinstance(item, dict):
                continue
            account_key = str(item.get("key", "") or "").strip()
            if not account_key or account_key in seen:
                continue
            seen.add(account_key)
            clean_sessions.append(dict(item))
            if len(clean_sessions) >= int(limit):
                break
        self._replace_payload_table(
            "account_sessions",
            "account_key",
            clean_sessions,
            lambda item: str(item.get("key", "") or "").strip(),
        )
        return self.list_account_sessions(limit)

    def get_runtime_state(self, key: str) -> dict | None:
        self.initialize()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM runtime_state WHERE key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        value = _json_loads(str(row["payload"]), None)
        return value if isinstance(value, dict) else None

    def set_runtime_state(self, key: str, value: dict | None) -> None:
        self.initialize()
        with self._connect() as conn:
            if value is None:
                conn.execute("DELETE FROM runtime_state WHERE key = ?", (key,))
                return
            conn.execute(
                """
                INSERT OR REPLACE INTO runtime_state(key, payload, updated_at)
                VALUES(?, ?, ?)
                """,
                (key, _json_dumps(dict(value)), _now()),
            )

    def _list_payload_table(self, table: str, order_by: str, limit: int) -> list[dict]:
        self.initialize()
        rows: list[dict] = []
        with self._connect() as conn:
            for row in conn.execute(
                f"SELECT payload FROM {table} ORDER BY {order_by} LIMIT ?",
                (int(limit),),
            ):
                value = _json_loads(str(row["payload"]), {})
                if isinstance(value, dict):
                    rows.append(value)
        return rows

    def _replace_payload_table(
        self,
        table: str,
        key_column: str,
        rows: list[dict],
        key_getter,
    ) -> None:
        self.initialize()
        now = _now()
        with self._connect() as conn:
            conn.execute(f"DELETE FROM {table}")
            for position, item in enumerate(rows):
                key = key_getter(item)
                if not key:
                    continue
                conn.execute(
                    f"""
                    INSERT INTO {table}({key_column}, position, payload, updated_at)
                    VALUES(?, ?, ?, ?)
                    """,
                    (key, position, _json_dumps(item), now),
                )


def _history_created_at(record: dict) -> str:
    value = str(record.get("time", "") or "").strip()
    if value:
        return value
    return _now()


class MediaIndexStore:
    """Per-save-root Telegram media index used for duplicate detection."""

    def __init__(self, save_root: Path) -> None:
        self.root = Path(save_root)
        self.path = self.root / ".tg_pic_collector_media.sqlite3"
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        if self._initialized:
            return
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA synchronous=NORMAL;

                CREATE TABLE IF NOT EXISTS media_index (
                    media_key TEXT PRIMARY KEY,
                    relative_path TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                """
            )
        self._initialized = True

    def load(self) -> tuple[set[str], dict[str, str]]:
        self.initialize()
        keys: set[str] = set()
        paths: dict[str, str] = {}
        with self._connect() as conn:
            for row in conn.execute(
                "SELECT media_key, relative_path FROM media_index"
            ):
                key = str(row["media_key"] or "")
                if not key:
                    continue
                keys.add(key)
                relative_path = str(row["relative_path"] or "")
                if relative_path:
                    paths[key] = relative_path
        return keys, paths

    def replace(self, media_keys: set[str], media_paths: dict[str, str]) -> None:
        self.initialize()
        keys = sorted({str(item) for item in media_keys if item})
        now = _now()
        with self._connect() as conn:
            conn.execute("DELETE FROM media_index")
            conn.executemany(
                """
                INSERT INTO media_index(media_key, relative_path, updated_at)
                VALUES(?, ?, ?)
                """,
                [(key, str(media_paths.get(key, "")), now) for key in keys],
            )

    def upsert(self, media_paths: dict[str, str]) -> None:
        self.initialize()
        now = _now()
        rows = [
            (str(key), str(value or ""), now)
            for key, value in media_paths.items()
            if str(key or "")
        ]
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO media_index(media_key, relative_path, updated_at)
                VALUES(?, ?, ?)
                """,
                rows,
            )

    def delete(self, media_keys: set[str]) -> None:
        self.initialize()
        keys = [(str(key),) for key in media_keys if str(key or "")]
        if not keys:
            return
        with self._connect() as conn:
            conn.executemany(
                "DELETE FROM media_index WHERE media_key = ?",
                keys,
            )

    def migrate_from_legacy_json(self, legacy_path: Path) -> None:
        if not legacy_path.exists():
            return
        existing_keys, _ = self.load()
        if existing_keys:
            return
        try:
            payload = json.loads(legacy_path.read_text(encoding="utf-8"))
            media_keys = {str(item) for item in payload.get("media_keys", []) if item}
            media_paths = payload.get("media_paths", {})
            clean_paths: dict[str, str] = {}
            if isinstance(media_paths, dict):
                clean_paths = {
                    str(key): str(value)
                    for key, value in media_paths.items()
                    if key and value
                }
                media_keys.update(clean_paths)
            self.replace(media_keys, clean_paths)
        except (OSError, ValueError, TypeError):
            return
