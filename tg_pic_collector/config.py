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
    request_interval: float = 1.0
    filename_limit: int = 100
    empty_tag_action: str = "uncategorized"
    restore_on_launch: bool = True
    use_last_mode: bool = True
    auto_fill_tag: bool = True
    enable_animations: bool = True
    enable_rounded_corners: bool = True
    use_dpapi_encryption: bool = True
    last_task_state: dict | None = None

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

    @classmethod
    def load(cls) -> "AppConfig":
        probe = cls()
        path = probe.config_dir / "config.json"
        if not path.exists():
            return probe
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            valid = {key: value for key, value in payload.items() if key in cls.__dataclass_fields__}
            return cls(**valid)
        except (OSError, ValueError, TypeError):
            return probe
