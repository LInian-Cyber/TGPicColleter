from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .store import MediaIndexStore


class DownloadedMediaIndex:
    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.paths: dict[str, str] = {}
        self.index_path: Path | None = None
        self._store: MediaIndexStore | None = None
        self._dirty = False
        self._dirty_count = 0
        self._dirty_keys: set[str] = set()
        self._deleted_keys: set[str] = set()
        self._last_save_at = 0.0

    def load(self, save_root: Path) -> None:
        legacy_path = save_root / ".tg_pic_collector_media.json"
        self.index_path = save_root / ".tg_pic_collector_media.sqlite3"
        self._store = MediaIndexStore(save_root)
        self.keys = set()
        self.paths = {}
        self._dirty = False
        self._dirty_count = 0
        self._dirty_keys = set()
        self._deleted_keys = set()
        self._last_save_at = time.monotonic()
        try:
            self._store.migrate_from_legacy_json(legacy_path)
            self.keys, self.paths = self._store.load()
        except (OSError, ValueError, TypeError):
            self.keys = set()
            self.paths = {}

    def save(self) -> None:
        if not self._store:
            return
        try:
            if self._deleted_keys:
                self._store.delete(self._deleted_keys)
            dirty_paths = {
                key: self.paths.get(key, "")
                for key in self._dirty_keys
                if key in self.keys
            }
            if dirty_paths:
                self._store.upsert(dirty_paths)
            self._dirty = False
            self._dirty_count = 0
            self._dirty_keys = set()
            self._deleted_keys = set()
            self._last_save_at = time.monotonic()
        except OSError:
            pass

    def save_if_needed(self, *, force: bool = False) -> None:
        if not self._dirty:
            return
        if not force:
            elapsed = time.monotonic() - self._last_save_at
            if self._dirty_count < 25 and elapsed < 2.0:
                return
        self.save()

    def indexed_path(self, media_key: str, fallback_target: Path | None = None) -> Path | None:
        if not media_key:
            return None
        root = self.index_path.parent if self.index_path else None
        raw_path = self.paths.get(media_key, "")
        if raw_path and root:
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = root / candidate
            if candidate.exists():
                return candidate
            self.paths.pop(media_key, None)
            self.keys.discard(media_key)
            self._mark_deleted(media_key)
            self.save_if_needed(force=True)
        if fallback_target and media_key in self.keys:
            if fallback_target.exists():
                return fallback_target
            self.keys.discard(media_key)
            self._mark_deleted(media_key)
            self.save_if_needed(force=True)
        return None

    def remember(self, media_key: str, target: Path) -> None:
        if not media_key or not target.exists():
            return
        self.keys.add(media_key)
        root = self.index_path.parent if self.index_path else None
        stored_path = str(target)
        if root:
            try:
                stored_path = str(target.resolve().relative_to(root.resolve()))
            except (OSError, ValueError):
                stored_path = str(target.resolve())
        self.paths[media_key] = stored_path
        self._mark_dirty(media_key)
        self.save_if_needed()

    def _mark_dirty(self, media_key: str) -> None:
        self._dirty = True
        self._dirty_count += 1
        self._dirty_keys.add(media_key)
        self._deleted_keys.discard(media_key)

    def _mark_deleted(self, media_key: str) -> None:
        self._dirty = True
        self._dirty_count += 1
        self._dirty_keys.discard(media_key)
        self._deleted_keys.add(media_key)


def media_key(message: Any) -> str:
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
