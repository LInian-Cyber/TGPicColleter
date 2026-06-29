from __future__ import annotations

import asyncio
import hashlib
import html
import mimetypes
import shutil
import ssl
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

from .network import urllib_proxy_map


TELEGRAPH_HOSTS = {"telegra.ph", "www.telegra.ph", "graph.org", "www.graph.org"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
USER_AGENT = "TG-Pic-Collector/2.4"


@dataclass(frozen=True)
class TelegraphDownloadResult:
    url: str
    pdf_path: Path
    image_dir: Path
    image_paths: tuple[Path, ...]
    page_count: int = 0

    @property
    def image_count(self) -> int:
        return self.page_count or len(self.image_paths)


class _TelegraphHTMLParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.image_urls: list[str] = []
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.casefold()
        attrs_map = {name.casefold(): value or "" for name, value in attrs}
        if tag_name == "meta":
            marker = (
                attrs_map.get("property", "")
                or attrs_map.get("name", "")
            ).casefold()
            if marker in {"og:image", "twitter:image", "twitter:image:src"}:
                self._add(attrs_map.get("content", ""))
        elif tag_name == "link":
            rel = {item.casefold() for item in attrs_map.get("rel", "").split()}
            if "image_src" in rel:
                self._add(attrs_map.get("href", ""))
        elif tag_name == "img":
            self._add(attrs_map.get("src", ""))
            self._add_srcset(attrs_map.get("srcset", ""))
        elif tag_name == "source":
            self._add_srcset(attrs_map.get("srcset", ""))

    def _add_srcset(self, value: str) -> None:
        for candidate in value.split(","):
            url = candidate.strip().split(" ", 1)[0]
            self._add(url)

    def _add(self, value: str) -> None:
        url = normalize_url(value)
        if not url or url.startswith("data:"):
            return
        absolute = urljoin(self.page_url, url)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            return
        absolute = urlunparse(parsed._replace(fragment=""))
        if absolute in self._seen:
            return
        self._seen.add(absolute)
        self.image_urls.append(absolute)


def normalize_url(value: str) -> str:
    url = html.unescape(str(value or "")).strip().strip("<>")
    while url and url[-1] in ".,;:!?，。；：！？)]}）】」』\"'":
        url = url[:-1].rstrip()
    if url.startswith("//"):
        url = f"https:{url}"
    if url and "://" not in url and _looks_like_telegraph_host(url):
        url = f"https://{url}"
    return url


def is_telegraph_page_url(value: str) -> bool:
    url = normalize_url(value)
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    if host not in TELEGRAPH_HOSTS:
        return False
    path = parsed.path.strip("/")
    return bool(path) and not path.casefold().startswith("file/")


def telegraph_page_key(url: str) -> str:
    normalized = normalize_url(url)
    parsed = urlparse(normalized)
    normalized = urlunparse(parsed._replace(fragment=""))
    return f"telegraph:{hashlib.sha256(normalized.encode('utf-8')).hexdigest()}"


def telegraph_slug(url: str, fallback: str = "telegraph") -> str:
    parsed = urlparse(normalize_url(url))
    slug = unquote(Path(parsed.path.rstrip("/") or fallback).name)
    return slug or fallback


def request_url(url: str) -> str:
    """Return an ASCII-safe URL for urllib while preserving existing escapes."""
    parsed = urlparse(normalize_url(url))
    return urlunparse(
        parsed._replace(
            path=quote(parsed.path, safe="/%"),
            params=quote(parsed.params, safe=";%"),
            query=quote(parsed.query, safe="=&?/:;+,%"),
            fragment="",
        )
    )


def extract_telegraph_image_urls(page_url: str, html_text: str) -> list[str]:
    parser = _TelegraphHTMLParser(normalize_url(page_url))
    parser.feed(html_text or "")
    parser.close()
    return parser.image_urls


def message_telegraph_links(message: Any) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        url = normalize_url(value)
        if not is_telegraph_page_url(url):
            return
        parsed = urlparse(url)
        url = urlunparse(parsed._replace(fragment=""))
        if url in seen:
            return
        seen.add(url)
        links.append(url)

    raw_text = str(getattr(message, "message", "") or "")
    try:
        entities_text = message.get_entities_text()
    except (AttributeError, TypeError, ValueError):
        entities_text = []
    for entity, visible_text in entities_text:
        url = str(getattr(entity, "url", "") or "").strip()
        if not url and type(entity).__name__ == "MessageEntityUrl":
            url = str(visible_text or "").strip()
        add(url)

    for url in _raw_telegraph_urls(raw_text):
        add(url)

    for row in getattr(message, "buttons", None) or []:
        buttons = row if isinstance(row, (list, tuple)) else [row]
        for button in buttons:
            add(str(getattr(button, "url", "") or ""))

    reply_markup = getattr(message, "reply_markup", None)
    for row in getattr(reply_markup, "rows", None) or []:
        for button in getattr(row, "buttons", None) or []:
            add(str(getattr(button, "url", "") or ""))

    media = getattr(message, "media", None)
    webpage = getattr(media, "webpage", None)
    add(str(getattr(webpage, "url", "") or ""))
    return links


async def download_telegraph_comic_async(
    url: str,
    pdf_path: Path,
    image_dir: Path,
    *,
    proxy_url: str = "",
    use_system_proxy: bool = True,
    timeout: float = 20.0,
    keep_images: bool = False,
) -> TelegraphDownloadResult:
    return await asyncio.to_thread(
        download_telegraph_comic,
        request_url(url),
        pdf_path,
        image_dir,
        proxy_url=proxy_url,
        use_system_proxy=use_system_proxy,
        timeout=timeout,
        keep_images=keep_images,
    )


def download_telegraph_comic(
    url: str,
    pdf_path: Path,
    image_dir: Path,
    *,
    proxy_url: str = "",
    use_system_proxy: bool = True,
    timeout: float = 20.0,
    keep_images: bool = False,
) -> TelegraphDownloadResult:
    page_url = normalize_url(url)
    if not is_telegraph_page_url(page_url):
        raise ValueError(f"不是 Telegraph 页面链接: {url}")

    opener = _build_opener(proxy_url, use_system_proxy)
    page_html = _fetch_text(opener, page_url, timeout)
    image_urls = extract_telegraph_image_urls(page_url, page_html)
    if not image_urls:
        raise ValueError("Telegraph 页面里没有发现图片")

    image_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []
    for index, image_url in enumerate(image_urls, start=1):
        image_paths.append(
            _download_image(opener, image_url, image_dir, index, timeout)
        )

    page_count = len(image_paths)
    try:
        create_pdf_from_images(image_paths, pdf_path)
    finally:
        if not keep_images:
            shutil.rmtree(image_dir, ignore_errors=True)
    return TelegraphDownloadResult(
        url=page_url,
        pdf_path=pdf_path,
        image_dir=image_dir,
        image_paths=tuple(image_paths) if keep_images else (),
        page_count=page_count,
    )


def create_pdf_from_images(image_paths: list[Path] | tuple[Path, ...], pdf_path: Path) -> None:
    if not image_paths:
        raise ValueError("没有可写入 PDF 的图片")
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise RuntimeError("缺少 Pillow，无法把 Telegraph 图片合成为 PDF") from exc

    pages = []
    try:
        for image_path in image_paths:
            with Image.open(image_path) as image:
                frame = ImageOps.exif_transpose(image)
                if frame.mode in {"RGBA", "LA"}:
                    background = Image.new("RGB", frame.size, "white")
                    alpha = frame.getchannel("A")
                    background.paste(frame.convert("RGBA"), mask=alpha)
                    frame = background
                elif frame.mode == "P":
                    frame = frame.convert("RGBA")
                    background = Image.new("RGB", frame.size, "white")
                    background.paste(frame, mask=frame.getchannel("A"))
                    frame = background
                else:
                    frame = frame.convert("RGB")
                pages.append(frame.copy())

        pdf_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = pdf_path.with_name(f"{pdf_path.name}.part")
        tmp_path.unlink(missing_ok=True)
        pages[0].save(
            tmp_path,
            "PDF",
            save_all=True,
            append_images=pages[1:],
            resolution=100.0,
        )
        tmp_path.replace(pdf_path)
    finally:
        for page in pages:
            page.close()


def _looks_like_telegraph_host(value: str) -> bool:
    head = value.split("/", 1)[0].casefold()
    return head in TELEGRAPH_HOSTS


def _raw_telegraph_urls(text: str) -> list[str]:
    import re

    pattern = re.compile(
        r"(?:https?://)?(?:www\.)?(?:telegra\.ph|graph\.org)/[^\s<>\"]+",
        flags=re.IGNORECASE,
    )
    return [match.group(0) for match in pattern.finditer(text or "")]


def _build_opener(proxy_url: str, use_system_proxy: bool):
    handlers = [HTTPSHandler(context=ssl.create_default_context())]
    proxy_map = urllib_proxy_map(proxy_url, use_system_proxy)
    if proxy_map:
        handlers.insert(0, ProxyHandler(proxy_map))
    return build_opener(*handlers)


def _fetch_text(opener: Any, url: str, timeout: float) -> str:
    request = Request(
        request_url(url),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    with opener.open(request, timeout=timeout) as response:
        data = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return data.decode(charset, errors="replace")


def _download_image(
    opener: Any,
    url: str,
    image_dir: Path,
    index: int,
    timeout: float,
) -> Path:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    with opener.open(request, timeout=timeout) as response:
        data = response.read()
        content_type = response.headers.get_content_type()

    suffix = _image_suffix(url, content_type)
    target = image_dir / f"{index:03d}{suffix}"
    if target.exists() and target.stat().st_size > 0:
        return target
    tmp_path = target.with_name(f"{target.name}.part")
    tmp_path.write_bytes(data)
    tmp_path.replace(target)
    return target


def _image_suffix(url: str, content_type: str) -> str:
    suffix = Path(urlparse(url).path).suffix.casefold()
    if suffix in IMAGE_SUFFIXES:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension(content_type or "")
    if guessed and guessed.casefold() in IMAGE_SUFFIXES:
        return ".jpg" if guessed.casefold() == ".jpeg" else guessed.casefold()
    return ".jpg"
