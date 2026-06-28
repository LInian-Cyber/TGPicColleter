import asyncio
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, PropertyMock, patch

from tg_pic_collector.config import AppConfig
from tg_pic_collector.controller import AppController
from tg_pic_collector.igp import (
    create_igp_package,
    default_sidecar_path,
    embed_metadata_file,
    write_sidecar,
)
from tg_pic_collector.models import PreviewRequest, ScanRequest, TelegramCredentials
from tg_pic_collector.network import (
    effective_proxy_url,
    parse_proxy_url,
    urllib_proxy_map,
    yande_proxy_warning,
)
from tg_pic_collector.telegram_worker import TelegramWorker, is_image_message, safe_name
from tg_pic_collector.yande_worker import _post_id_from_text, _safe_filename


def fake_image_message(
    message_id: int = 7,
    *,
    name: str = "photo.jpg",
    mime_type: str = "image/jpeg",
    size: int = 1024,
    message: str = "",
    date=None,
):
    document = SimpleNamespace(id=message_id, mime_type=mime_type, size=size)
    return SimpleNamespace(
        id=message_id,
        message=message,
        photo=None,
        document=document,
        file=SimpleNamespace(name=name, mime_type=mime_type, size=size),
        date=date,
        buttons=None,
    )


class TelegramWorkerHelperTests(TestCase):
    def test_safe_name_removes_windows_reserved_characters(self) -> None:
        self.assertEqual(safe_name('cats: "summer"?'), "cats_ _summer__")

    def test_safe_name_avoids_windows_reserved_device_names(self) -> None:
        self.assertEqual(safe_name("CON"), "_CON")
        self.assertEqual(safe_name("LPT1"), "_LPT1")

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

    def test_original_file_name_avoids_windows_reserved_device_name(self) -> None:
        message = SimpleNamespace(
            id=7,
            file=SimpleNamespace(name="CON.PNG", mime_type="image/png"),
            date=None,
        )

        name = TelegramWorker._file_name(
            message,
            post_id=1,
            preserve_original_name=True,
        )

        self.assertEqual(name, "_CON.PNG")

    def test_yande_safe_filename_avoids_windows_reserved_device_name(self) -> None:
        self.assertEqual(_safe_filename("NUL.jpg", "fallback.jpg"), "_NUL.jpg")

    def test_yande_post_id_can_be_read_from_unencoded_tags_url(self) -> None:
        self.assertEqual(_post_id_from_text("https://yande.re/post?tags=id:12345"), 12345)


    def test_matching_button_url_is_found_case_insensitively(self) -> None:
        message = SimpleNamespace(
            buttons=[
                [SimpleNamespace(text="查看详情", url="https://example.com/detail")],
                [SimpleNamespace(text="高清 Source", url="https://example.com/original")],
            ]
        )

        result = TelegramWorker._find_button_url(message, "source")

        self.assertEqual(result, ("高清 Source", "https://example.com/original"))

    def test_original_link_can_be_found_in_button_url(self) -> None:
        message = SimpleNamespace(
            buttons=[
                [SimpleNamespace(text="查看原图", url="https://t.me/demo/42")],
            ],
            message="",
        )

        result = TelegramWorker._find_original_link(message, "原图")

        self.assertEqual(result, ("查看原图", "https://t.me/demo/42"))

    def test_link_shortcut_is_written(self) -> None:
        with TemporaryDirectory() as directory:
            target = Path(directory) / "original.url"

            TelegramWorker._write_link_shortcut(target, "https://example.com/image.jpg")

            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "[InternetShortcut]\nURL=https://example.com/image.jpg\n",
            )

    def test_igp_package_contains_original_image_and_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            image = Path(directory) / "photo.jpg"
            image.write_bytes(b"\xff\xd8\xff\xd9")
            sidecar = write_sidecar(
                image,
                {
                    "tags": [{"name": "cats", "source": "task", "confidence": 1.0}],
                    "telegram": {"post_id": 42},
                },
            )

            package = create_igp_package(image, sidecar)

            with zipfile.ZipFile(package) as zf:
                self.assertIn("manifest.json", zf.namelist())
                self.assertIn("image/original.jpg", zf.namelist())
                self.assertIn("metadata/igp.json", zf.namelist())
                metadata = json.loads(zf.read("metadata/igp.json").decode("utf-8"))
        self.assertEqual(metadata["telegram"]["post_id"], 42)

    def test_png_metadata_embedding_adds_igp_itxt_chunk(self) -> None:
        with TemporaryDirectory() as directory:
            image = Path(directory) / "photo.png"
            image.write_bytes(
                b"\x89PNG\r\n\x1a\n"
                b"\x00\x00\x00\rIHDR"
                b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
                b"\x00\x00\x00\x00"
                b"\x00\x00\x00\x00IEND\xaeB`\x82"
            )
            write_sidecar(image, {"tags": [{"name": "cats"}]})

            embedded = embed_metadata_file(image)
            embedded_bytes = embedded.read_bytes()

        self.assertIn(b"iTXt", embedded_bytes)
        self.assertIn(b"IGP", embedded_bytes)


class NetworkProxyTests(TestCase):
    def test_custom_proxy_without_scheme_defaults_to_http(self) -> None:
        proxy = parse_proxy_url("127.0.0.1:7890", use_system_proxy=False)

        self.assertIsNotNone(proxy)
        self.assertEqual(proxy.scheme, "http")
        self.assertEqual(proxy.host, "127.0.0.1")
        self.assertEqual(proxy.port, 7890)

    def test_telegram_prefers_socks_system_proxy(self) -> None:
        with patch(
            "tg_pic_collector.network.getproxies",
            return_value={"http": "http://127.0.0.1:7890", "socks": "socks5://127.0.0.1:7891"},
        ):
            self.assertEqual(
                effective_proxy_url(use_system_proxy=True, purpose="telegram"),
                "socks5://127.0.0.1:7891",
            )

    def test_yande_prefers_http_system_proxy(self) -> None:
        with patch(
            "tg_pic_collector.network.getproxies",
            return_value={"http": "http://127.0.0.1:7890", "socks": "socks5://127.0.0.1:7891"},
        ):
            self.assertEqual(
                effective_proxy_url(use_system_proxy=True, purpose="http"),
                "http://127.0.0.1:7890",
            )
            self.assertEqual(
                urllib_proxy_map(use_system_proxy=True),
                {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"},
            )

    def test_yande_warns_for_socks_proxy(self) -> None:
        self.assertIn(
            "SOCKS",
            yande_proxy_warning("socks5://127.0.0.1:7890", use_system_proxy=False),
        )


class TelegramPreviewTests(IsolatedAsyncioTestCase):
    async def test_scan_emits_post_level_completion_status(self) -> None:
        post = SimpleNamespace(
            id=42,
            message="#cats",
            replies=SimpleNamespace(replies=1),
        )
        image = fake_image_message(99)

        class FakeClient:
            async def get_entity(self, _):
                return SimpleNamespace(title="Demo Channel", username="demo", id=1)

            async def download_profile_photo(self, *_args, **_kwargs):
                return b""

            def iter_messages(self, _, search=None, limit=None, reply_to=None, **_kwargs):
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

    async def test_scan_skips_immediately_when_empty_tag_action_is_skip(self) -> None:
        class FakeClient:
            async def get_entity(self, _):
                raise AssertionError("empty tag skip should not resolve a channel")

        with TemporaryDirectory() as directory:
            worker = TelegramWorker(
                TelegramCredentials(1, "hash", "", Path(directory) / "session")
            )
            statuses = []
            finished = []
            worker.status_changed.connect(statuses.append)
            worker.scan_finished.connect(
                lambda posts, downloaded, skipped: finished.append(
                    (posts, downloaded, skipped)
                )
            )
            await worker._scan(
                FakeClient(),
                ScanRequest(
                    "@demo",
                    "",
                    Path(directory),
                    "tag",
                    max_posts=10,
                    empty_tag_action="skip",
                ),
            )

        self.assertEqual(finished, [(0, 0, 0)])
        self.assertIn("Tag 为空", statuses[-1])

    async def test_file_download_interval_is_applied_after_media_download(self) -> None:
        client = SimpleNamespace(download_media=AsyncMock(return_value="downloaded.jpg"))
        semaphore = asyncio.Semaphore(1)

        with patch(
            "tg_pic_collector.telegram_worker.asyncio.sleep",
            new=AsyncMock(),
        ) as sleep:
            result = await TelegramWorker._download_media(
                client,
                fake_image_message(7),
                Path("downloaded.jpg"),
                semaphore,
                0.5,
            )

        self.assertTrue(result)
        client.download_media.assert_awaited_once()
        sleep.assert_awaited_once_with(0.5)

    async def test_file_cooldown_does_not_hold_download_slot(self) -> None:
        cooldown_started = asyncio.Event()
        release_cooldown = asyncio.Event()
        second_download_started = asyncio.Event()
        download_calls = 0

        async def download_media(_message, file):
            nonlocal download_calls
            download_calls += 1
            if download_calls == 2:
                second_download_started.set()
            return file

        async def wait_for_cooldown(_delay):
            cooldown_started.set()
            await release_cooldown.wait()

        client = SimpleNamespace(download_media=download_media)
        semaphore = asyncio.Semaphore(1)
        with patch(
            "tg_pic_collector.telegram_worker.asyncio.sleep",
            new=wait_for_cooldown,
        ):
            first = asyncio.create_task(
                TelegramWorker._download_media(
                    client, fake_image_message(1), Path("one.jpg"), semaphore, 0.5
                )
            )
            await cooldown_started.wait()
            second = asyncio.create_task(
                TelegramWorker._download_media(
                    client, fake_image_message(2), Path("two.jpg"), semaphore, 0.5
                )
            )
            await asyncio.wait_for(second_download_started.wait(), timeout=0.5)
            release_cooldown.set()
            await asyncio.gather(first, second)

        self.assertEqual(download_calls, 2)

    async def test_chunked_download_limits_iter_download_by_chunk_count(self) -> None:
        file_size = 1_300_000
        calls = []

        class FakeClient:
            async def download_media(self, *_args, **_kwargs):
                raise AssertionError("chunked download should not fall back")

            def iter_download(self, _message, **kwargs):
                calls.append(kwargs)

                async def items():
                    for _ in range(kwargs["limit"]):
                        yield b"x" * kwargs["request_size"]

                return items()

        with TemporaryDirectory() as directory:
            target = Path(directory) / "chunked.jpg"
            result = await TelegramWorker._download_media(
                FakeClient(),
                fake_image_message(7, size=file_size),
                target,
                asyncio.Semaphore(2),
                0,
                chunk_concurrency=2,
            )

            self.assertTrue(result)
            self.assertEqual(target.stat().st_size, file_size)
            self.assertFalse(any(Path(directory).glob("chunked.jpg.part*")))

        self.assertTrue(calls)
        self.assertTrue(all(call["limit"] <= 2 for call in calls))

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

            def iter_messages(self, _, search=None, limit=None, reply_to=None, **_kwargs):
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
        preview_counts = []
        worker.preview_finished.connect(
            lambda preview_rows, total, limit: (
                rows.extend(preview_rows),
                preview_counts.append((total, limit)),
            )
        )

        await worker._preview(
            FakeClient(),
            PreviewRequest("@demo", "#cats", max_posts=10),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["post_id"], 42)
        self.assertEqual(rows[0]["image_count"], 1)
        self.assertEqual(rows[0]["thumbnails"], [b"thumbnail"])
        self.assertEqual(preview_counts, [(1, 50)])
        cached = worker._preview_cache[("@demo", "#cats", "", "")][0]
        self.assertIs(cached["_post"], post)
        self.assertEqual(cached["_media_messages"], [image])
        self.assertNotIn("_post", rows[0])
        self.assertNotIn("_media_messages", rows[0])

    async def test_scan_uses_preview_media_cache_without_rescanning_comments(self) -> None:
        post = SimpleNamespace(
            id=42,
            message="#cats",
            replies=SimpleNamespace(replies=1),
            buttons=None,
        )
        image = fake_image_message(99)

        class FakeClient:
            async def get_entity(self, _):
                return SimpleNamespace(title="Demo Channel", username="demo", id=1)

            async def download_profile_photo(self, *_args, **_kwargs):
                return b""

            def iter_messages(self, *_args, **_kwargs):
                raise AssertionError("cached scan must not iterate messages")

            async def get_messages(self, *_args, **_kwargs):
                raise AssertionError("cached scan must not refetch the post")

            async def download_media(self, _message, file):
                return file

        with TemporaryDirectory() as directory:
            worker = TelegramWorker(
                TelegramCredentials(1, "hash", "", Path(directory) / "session")
            )
            cache_key = ("@demo", "#cats", "", "")
            worker._preview_cache[cache_key] = [
                {
                    "post_id": 42,
                    "image_count": 1,
                    "_post": post,
                    "_comments": [image],
                    "_media_messages": [image],
                }
            ]
            worker._preview_cache_limits[cache_key] = 10
            plans = []
            progress = []
            worker.scan_plan_ready.connect(lambda posts, total: plans.append((posts, total)))
            worker.scan_progress.connect(
                lambda downloaded, skipped, location: progress.append(
                    (downloaded, skipped, location)
                )
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

        self.assertEqual(plans, [(1, 1)])
        self.assertEqual(progress[-1][:2], (1, 0))

    async def test_scan_skips_duplicate_media_indexed_in_another_folder(self) -> None:
        post = SimpleNamespace(
            id=42,
            message="#cats",
            replies=SimpleNamespace(replies=1),
        )
        image = fake_image_message(99, name="new-target.jpg")

        class FakeClient:
            async def get_entity(self, _):
                return SimpleNamespace(title="Demo Channel", username="demo", id=1)

            async def download_profile_photo(self, *_args, **_kwargs):
                return b""

            def iter_messages(self, _, search=None, limit=None, reply_to=None, **_kwargs):
                async def items():
                    yield image if reply_to else post

                return items()

            async def download_media(self, *_args, **_kwargs):
                raise AssertionError("indexed duplicate media should not download again")

        with TemporaryDirectory() as directory:
            root = Path(directory)
            indexed_file = root / "already" / "original.jpg"
            indexed_file.parent.mkdir()
            indexed_file.write_bytes(b"existing")
            (root / ".tg_pic_collector_media.json").write_text(
                json.dumps(
                    {
                        "version": 2,
                        "media_keys": ["doc:99"],
                        "media_paths": {"doc:99": "already/original.jpg"},
                    }
                ),
                encoding="utf-8",
            )
            worker = TelegramWorker(
                TelegramCredentials(1, "hash", "", root / "session")
            )
            finished = []
            worker.scan_finished.connect(
                lambda posts, downloaded, skipped: finished.append(
                    (posts, downloaded, skipped)
                )
            )

            await worker._scan(
                FakeClient(),
                ScanRequest(
                    "@demo",
                    "#cats",
                    root,
                    "tag",
                    max_posts=10,
                    file_download_interval=0,
                ),
            )

        self.assertEqual(finished, [(1, 0, 1)])

    async def test_scan_downloads_same_media_only_once_per_task(self) -> None:
        posts = [
            SimpleNamespace(id=42, message="#cats first", replies=SimpleNamespace(replies=1)),
            SimpleNamespace(id=43, message="#cats second", replies=SimpleNamespace(replies=1)),
        ]
        images = {
            42: fake_image_message(99, name="first.jpg"),
            43: fake_image_message(99, name="second.jpg"),
        }
        download_calls = 0

        class FakeClient:
            async def get_entity(self, _):
                return SimpleNamespace(title="Demo Channel", username="demo", id=1)

            async def download_profile_photo(self, *_args, **_kwargs):
                return b""

            def iter_messages(self, _, search=None, limit=None, reply_to=None, **_kwargs):
                async def items():
                    if reply_to is None:
                        for post in posts:
                            yield post
                    else:
                        yield images[int(reply_to)]

                return items()

            async def download_media(self, _message, file):
                nonlocal download_calls
                download_calls += 1
                Path(file).write_bytes(b"\xff\xd8\xff\xd9")
                return file

        with TemporaryDirectory() as directory:
            root = Path(directory)
            worker = TelegramWorker(
                TelegramCredentials(1, "hash", "", root / "session")
            )
            finished = []
            worker.scan_finished.connect(
                lambda posts, downloaded, skipped: finished.append(
                    (posts, downloaded, skipped)
                )
            )

            await worker._scan(
                FakeClient(),
                ScanRequest(
                    "@demo",
                    "#cats",
                    root,
                    "tag",
                    max_posts=10,
                    concurrency=1,
                    file_download_interval=0,
                ),
            )

        self.assertEqual(download_calls, 1)
        self.assertEqual(finished, [(2, 1, 1)])

    async def test_scan_writes_extended_info_sidecar(self) -> None:
        post = SimpleNamespace(
            id=42,
            message="#cats source post",
            replies=SimpleNamespace(replies=1),
        )
        image = fake_image_message(
            99,
            message="#cute",
            date=datetime(2026, 6, 10, tzinfo=timezone.utc),
        )

        class FakeClient:
            async def get_entity(self, _):
                return SimpleNamespace(title="Demo Channel", username="demo", id=1)

            async def download_profile_photo(self, *_args, **_kwargs):
                return b""

            def iter_messages(self, _, search=None, limit=None, reply_to=None, **_kwargs):
                async def items():
                    yield image if reply_to else post

                return items()

            async def download_media(self, _message, file):
                Path(file).write_bytes(b"\xff\xd8\xff\xd9")
                return file

        with TemporaryDirectory() as directory:
            worker = TelegramWorker(
                TelegramCredentials(1, "hash", "", Path(directory) / "session")
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
                    save_extended_info=True,
                ),
            )
            image_path = Path(directory) / "cats" / "photo.jpg"
            sidecar = default_sidecar_path(image_path)
            payload = json.loads(sidecar.read_text(encoding="utf-8"))

        self.assertEqual(payload["format"], "igp-sidecar")
        self.assertEqual(payload["telegram"]["post_id"], 42)
        self.assertEqual(payload["telegram"]["message_id"], 99)
        self.assertEqual(payload["image"]["sha256"], "32461d5bd1773012acef0ba15636752949bd7c2ce50f9172159d9f56cf0dd9af")
        self.assertEqual([item["name"] for item in payload["tags"]], ["cats", "cute"])


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

    def test_save_writes_config_via_temp_file_then_replaces(self) -> None:
        with TemporaryDirectory() as directory:
            config_dir = Path(directory)
            with patch.object(
                AppConfig,
                "config_dir",
                new_callable=PropertyMock,
                return_value=config_dir,
            ):
                config = AppConfig(api_id="123", chunk_concurrency=3)
                config.save()

            payload = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["api_id"], "123")
        self.assertEqual(payload["chunk_concurrency"], 3)
        self.assertFalse((config_dir / "config.json.tmp").exists())

    def test_session_path_avoids_windows_reserved_device_name(self) -> None:
        with TemporaryDirectory() as directory:
            config_dir = Path(directory)
            with patch.object(
                AppConfig,
                "config_dir",
                new_callable=PropertyMock,
                return_value=config_dir,
            ):
                config = AppConfig(session_name="CON")

                session_path = config.session_path

        self.assertEqual(session_path.name, "_CON")

    def test_channel_history_update_keeps_recent_limit(self) -> None:
        with TemporaryDirectory() as directory:
            config_dir = Path(directory)
            with patch.object(
                AppConfig,
                "config_dir",
                new_callable=PropertyMock,
                return_value=config_dir,
            ):
                config = AppConfig()
                config.channel_history = [
                    {"id": f"@channel{i}", "name": f"Channel {i}"}
                    for i in range(25)
                ]
                config.add_channel_to_history("@channel24", "Updated")

        self.assertEqual(len(config.channel_history or []), 20)
        self.assertEqual((config.channel_history or [])[0]["id"], "@channel24")
        self.assertEqual((config.channel_history or [])[0]["name"], "Updated")


class ControllerResumeStateTests(TestCase):
    def test_resumable_post_ids_exclude_completed_posts(self) -> None:
        state = {
            "post_ids": [101, 102, 103],
            "post_statuses": {
                "101": "已完成 · 下载 1 · 跳过 0",
                "102": "未完成 · 任务已取消",
                "103": "正在处理",
            },
        }

        self.assertEqual(AppController._resumable_post_ids(state), [102, 103])

    def test_resumable_post_ids_keep_legacy_post_ids_without_statuses(self) -> None:
        self.assertEqual(
            AppController._resumable_post_ids({"post_ids": ["42", "bad", 43]}),
            [42, 43],
        )
