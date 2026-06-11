import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, PropertyMock, patch

from tg_pic_collector.config import AppConfig
from tg_pic_collector.models import PreviewRequest, ScanRequest, TelegramCredentials
from tg_pic_collector.telegram_worker import TelegramWorker, is_image_message, safe_name


class TelegramWorkerHelperTests(TestCase):
    def test_safe_name_removes_windows_reserved_characters(self) -> None:
        self.assertEqual(safe_name('cats: "summer"?'), "cats_ _summer__")

    def test_photo_and_image_document_are_recognized(self) -> None:
        photo = SimpleNamespace(photo=object(), document=None)
        image_document = SimpleNamespace(
            photo=None,
            document=SimpleNamespace(mime_type="image/png"),
        )
        video = SimpleNamespace(
            photo=None,
            document=SimpleNamespace(mime_type="video/mp4"),
        )

        self.assertTrue(is_image_message(photo))
        self.assertTrue(is_image_message(image_document))
        self.assertFalse(is_image_message(video))

    def test_channel_tag_target_directory(self) -> None:
        request = ScanRequest(
            channel="@demo",
            tag="#cats",
            save_root=Path("D:/Pictures"),
            save_mode="channel_tag",
            max_posts=100,
        )

        target = TelegramWorker._target_dir(request, "Demo Channel", 42)

        self.assertEqual(target, Path("D:/Pictures") / "Demo Channel" / "cats")

    def test_available_target_avoids_overwrite(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "photo.jpg"
            target.write_bytes(b"first")

            available = TelegramWorker._available_target(target)

            self.assertEqual(available.name, "photo_2.jpg")

    def test_original_file_name_can_be_preserved(self) -> None:
        message = SimpleNamespace(
            id=7,
            file=SimpleNamespace(name="Original Photo.PNG", mime_type="image/png"),
            date=None,
        )

        name = TelegramWorker._file_name(
            message,
            post_id=1,
            template="{date}_{id}",
            preserve_original_name=True,
        )

        self.assertEqual(name, "Original Photo.PNG")

    def test_matching_button_url_is_found_case_insensitively(self) -> None:
        message = SimpleNamespace(
            buttons=[
                [SimpleNamespace(text="查看详情", url="https://example.com/detail")],
                [SimpleNamespace(text="高清 Source", url="https://example.com/original")],
            ]
        )

        result = TelegramWorker._find_button_url(message, "source")

        self.assertEqual(result, ("高清 Source", "https://example.com/original"))

    def test_url_shortcut_is_written(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "original.url"

            TelegramWorker._write_url_shortcut(target, "https://example.com/image.jpg")

            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "[InternetShortcut]\nURL=https://example.com/image.jpg\n",
            )


class TelegramPreviewTests(IsolatedAsyncioTestCase):
    async def test_scan_emits_post_level_completion_status(self) -> None:
        post = SimpleNamespace(
            id=42,
            message="#cats",
            replies=SimpleNamespace(replies=1),
        )
        image = SimpleNamespace(
            id=99,
            photo=object(),
            document=None,
            file=SimpleNamespace(name="photo.jpg", mime_type="image/jpeg"),
            date=None,
        )

        class FakeClient:
            async def get_entity(self, _):
                return SimpleNamespace(title="Demo Channel", username="demo", id=1)

            async def download_profile_photo(self, *_args, **_kwargs):
                return b""

            def iter_messages(self, _, search=None, limit=None, reply_to=None):
                async def items():
                    yield image if reply_to else post

                return items()

            async def download_media(self, _message, file):
                return file

        with TemporaryDirectory() as directory:
            worker = TelegramWorker(
                TelegramCredentials(1, "hash", "", Path(directory) / "session")
            )
            statuses = []
            worker.post_status_changed.connect(
                lambda post_id, status: statuses.append((post_id, status))
            )
            await worker._scan(
                FakeClient(),
                ScanRequest(
                    "@demo",
                    "#cats",
                    Path(directory),
                    "tag",
                    max_posts=10,
                    file_download_interval=0,
                ),
            )

        self.assertEqual(statuses[0], (42, "正在处理"))
        self.assertTrue(statuses[-1][1].startswith("已完成 · 下载 1"))

    async def test_file_download_interval_is_applied_after_media_download(self) -> None:
        client = SimpleNamespace(download_media=AsyncMock(return_value="downloaded.jpg"))
        semaphore = asyncio.Semaphore(1)

        with patch(
            "tg_pic_collector.telegram_worker.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep:
            result = await TelegramWorker._download_media(
                client,
                SimpleNamespace(id=7),
                Path("downloaded.jpg"),
                semaphore,
                0.5,
            )

        self.assertTrue(result)
        client.download_media.assert_awaited_once()
        sleep.assert_awaited_once_with(0.5)

    async def test_preview_returns_post_summary_and_image_count(self) -> None:
        post = SimpleNamespace(
            id=42,
            message="#cats Preview post",
            date=datetime(2026, 6, 10, tzinfo=timezone.utc),
            views=120,
            replies=SimpleNamespace(replies=3),
        )
        image = SimpleNamespace(photo=object(), document=None)
        text = SimpleNamespace(photo=None, document=None)

        class FakeClient:
            async def get_entity(self, _):
                return SimpleNamespace(title="Demo Channel", username="demo")

            def iter_messages(self, _, search=None, limit=None, reply_to=None):
                async def items():
                    if reply_to is None:
                        yield post
                    else:
                        yield image
                        yield text

                return items()

            async def download_media(self, *_args, **_kwargs):
                return b"thumbnail"

        worker = TelegramWorker(
            TelegramCredentials(1, "hash", "", Path("test-session"))
        )
        rows = []
        worker.preview_finished.connect(rows.extend)

        await worker._preview(
            FakeClient(),
            PreviewRequest("@demo", "#cats", max_posts=10),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["post_id"], 42)
        self.assertEqual(rows[0]["image_count"], 1)
        self.assertEqual(rows[0]["thumbnails"], [b"thumbnail"])


class AppConfigTests(TestCase):
    def test_legacy_request_interval_is_migrated(self) -> None:
        with TemporaryDirectory() as directory:
            config_dir = Path(directory)
            (config_dir / "config.json").write_text(
                json.dumps({"request_interval": 2.5}),
                encoding="utf-8",
            )
            with patch.object(
                AppConfig,
                "config_dir",
                new_callable=PropertyMock,
                return_value=config_dir,
            ):
                config = AppConfig.load()

        self.assertEqual(config.file_download_interval, 2.5)
