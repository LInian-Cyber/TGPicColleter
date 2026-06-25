from __future__ import annotations

import json
import mimetypes
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
import hashlib
import zipfile


FORMAT_NAME = "Image Gallery Package"
FORMAT_VERSION = 1
SIDECAR_SUFFIX = ".igp.json"
IMAGE_SUFFIXES = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".bmp",
    ".tif",
    ".tiff",
    ".avif",
}
BASE_METADATA_KEYS = {"format", "format_name", "version", "created_at", "updated_at"}
KNOWN_METADATA_SECTIONS = {
    "image",
    "tags",
    "telegram",
    "text",
    "download",
    "thumbnails",
    "embeddings",
    "annotations",
}


class UnsupportedMetadataFormat(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def default_sidecar_path(image_path: Path) -> Path:
    return image_path.with_name(f"{image_path.name}{SIDECAR_SUFFIX}")


def image_path_from_sidecar(sidecar_path: Path) -> Path | None:
    name = sidecar_path.name
    if not name.endswith(SIDECAR_SUFFIX):
        return None
    image_name = name[: -len(SIDECAR_SUFFIX)]
    if not image_name:
        return None
    return sidecar_path.with_name(image_name)


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_SUFFIXES


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def guess_mime(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def image_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        with path.open("rb") as fh:
            header = fh.read(32)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and header[12:16] == b"IHDR":
                return struct.unpack(">II", header[16:24])
            if header.startswith(b"\xff\xd8"):
                fh.seek(2)
                return _jpeg_dimensions(fh)
    except OSError:
        return None, None
    return None, None


def _jpeg_dimensions(fh: Any) -> tuple[int | None, int | None]:
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while True:
        marker_prefix = fh.read(1)
        if not marker_prefix:
            return None, None
        if marker_prefix != b"\xff":
            continue
        marker = fh.read(1)
        while marker == b"\xff":
            marker = fh.read(1)
        if not marker:
            return None, None
        marker_value = marker[0]
        if marker_value in {0xD8, 0xD9}:
            continue
        length_bytes = fh.read(2)
        if len(length_bytes) != 2:
            return None, None
        segment_length = struct.unpack(">H", length_bytes)[0]
        if segment_length < 2:
            return None, None
        if marker_value in sof_markers:
            data = fh.read(5)
            if len(data) != 5:
                return None, None
            height, width = struct.unpack(">HH", data[1:5])
            return width, height
        fh.seek(segment_length - 2, 1)


def image_file_info(path: Path) -> dict[str, Any]:
    width, height = image_dimensions(path)
    info: dict[str, Any] = {
        "filename": path.name,
        "mime": guess_mime(path),
        "size": path.stat().st_size if path.exists() else 0,
        "sha256": sha256_file(path) if path.exists() else "",
    }
    if width is not None:
        info["width"] = width
    if height is not None:
        info["height"] = height
    return info


def write_sidecar(image_path: Path, metadata: dict[str, Any]) -> Path:
    sidecar_path = default_sidecar_path(image_path)
    payload = dict(metadata)
    payload.setdefault("format", "igp-sidecar")
    payload.setdefault("format_name", FORMAT_NAME)
    payload.setdefault("version", FORMAT_VERSION)
    payload.setdefault("created_at", utc_now())
    if image_path.exists():
        image_info = dict(payload.get("image", {}) or {})
        image_info.update(image_file_info(image_path))
        image_info.setdefault("path", image_path.name)
        payload["image"] = image_info
    sidecar_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return sidecar_path


def read_sidecar(sidecar_path: Path) -> dict[str, Any]:
    payload = json.loads(sidecar_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Metadata sidecar must contain a JSON object: {sidecar_path}")
    return payload


def sidecar_metadata_matches(image_path: Path, sidecar_path: Path) -> bool:
    try:
        payload = read_sidecar(sidecar_path)
    except (OSError, ValueError, TypeError):
        return False
    image_meta = payload.get("image", {})
    if not isinstance(image_meta, dict):
        return True
    metadata_path = str(image_meta.get("path", "") or "").strip()
    metadata_filename = str(image_meta.get("filename", "") or "").strip()
    names = {Path(value).name for value in (metadata_path, metadata_filename) if value}
    return not names or image_path.name in names


def validate_sidecar_pair(
    image_path: Path,
    sidecar_path: Path,
    strict_name: bool = True,
) -> None:
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")
    if not image_path.is_file() or not is_image_path(image_path):
        raise ValueError(f"Input is not a supported image file: {image_path}")
    if not sidecar_path.exists():
        raise FileNotFoundError(f"Sidecar not found: {sidecar_path}")
    if not sidecar_path.is_file() or not sidecar_path.name.endswith(SIDECAR_SUFFIX):
        raise ValueError(f"Input is not an IGP sidecar: {sidecar_path}")
    if strict_name and default_sidecar_path(image_path).resolve() != sidecar_path.resolve():
        raise ValueError(
            f"Sidecar does not exactly match image name: {image_path.name} + {sidecar_path.name}"
        )
    if not sidecar_metadata_matches(image_path, sidecar_path):
        raise ValueError(f"Sidecar metadata does not match image: {sidecar_path}")


def discover_sidecar_pairs(
    root: Path,
    recursive: bool = False,
) -> tuple[list[tuple[Path, Path]], int, int]:
    pattern = "**/*" if recursive else "*"
    sidecars = sorted(
        path for path in root.glob(pattern)
        if path.is_file() and path.name.endswith(SIDECAR_SUFFIX)
    )
    pairs: list[tuple[Path, Path]] = []
    orphan_sidecars = 0
    for sidecar_path in sidecars:
        image_path = image_path_from_sidecar(sidecar_path)
        if (
            image_path is None
            or not image_path.exists()
            or not image_path.is_file()
            or not is_image_path(image_path)
            or not sidecar_metadata_matches(image_path, sidecar_path)
        ):
            orphan_sidecars += 1
            continue
        pairs.append((image_path, sidecar_path))
    paired_images = {image.resolve() for image, _sidecar in pairs}
    orphan_images = sum(
        1
        for path in root.glob(pattern)
        if path.is_file()
        and is_image_path(path)
        and path.resolve() not in paired_images
        and not default_sidecar_path(path).exists()
    )
    return pairs, orphan_images, orphan_sidecars


def filter_metadata(
    metadata: dict[str, Any],
    sections: list[str] | tuple[str, ...] | set[str] | None = None,
) -> dict[str, Any]:
    if sections is None:
        return dict(metadata)
    allowed = {str(section) for section in sections if str(section)}
    include_unknown = "*" in allowed
    filtered: dict[str, Any] = {}
    for key, value in metadata.items():
        if key in BASE_METADATA_KEYS or key in allowed:
            filtered[key] = value
        elif include_unknown and key not in KNOWN_METADATA_SECTIONS:
            filtered[key] = value
    return filtered


def create_igp_package(
    image_path: Path,
    sidecar_path: Path | None = None,
    output_path: Path | None = None,
    metadata_sections: list[str] | tuple[str, ...] | set[str] | None = None,
    include_checksums: bool = True,
) -> Path:
    image_path = image_path.expanduser().resolve()
    sidecar_path = (sidecar_path or default_sidecar_path(image_path)).expanduser().resolve()
    output_path = (output_path or image_path.with_suffix(".igp")).expanduser().resolve()
    validate_sidecar_pair(image_path, sidecar_path, strict_name=False)
    metadata = filter_metadata(read_sidecar(sidecar_path), metadata_sections)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    image_entry = f"image/original{image_path.suffix.lower() or '.bin'}"
    metadata_entry = "metadata/igp.json"
    tags_entry = "metadata/tags.json"
    image_info = image_file_info(image_path)
    manifest = {
        "format": "igp",
        "format_name": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "package_type": "single_image",
        "created_at": utc_now(),
        "image": {
            **image_info,
            "path": image_entry,
            "original_filename": image_path.name,
        },
        "metadata": {
            "path": metadata_entry,
            "included_sections": sorted(
                key for key in metadata.keys() if key not in BASE_METADATA_KEYS
            ),
        },
    }
    if "tags" in metadata:
        manifest["metadata"]["tags"] = tags_entry
    tags_payload = {
        "tags": metadata.get("tags", []),
    }

    with zipfile.ZipFile(output_path, "w") as zf:
        zf.writestr(
            "mimetype",
            "application/vnd.image-gallery-package",
            compress_type=zipfile.ZIP_STORED,
        )
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        zf.write(image_path, image_entry, compress_type=zipfile.ZIP_DEFLATED)
        zf.writestr(
            metadata_entry,
            json.dumps(metadata, ensure_ascii=False, indent=2),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        if "tags" in metadata:
            zf.writestr(
                tags_entry,
                json.dumps(tags_payload, ensure_ascii=False, indent=2),
                compress_type=zipfile.ZIP_DEFLATED,
            )
        if include_checksums:
            checksums = {
                image_entry: image_info.get("sha256", ""),
                metadata_entry: hashlib.sha256(
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest(),
            }
            zf.writestr(
                "checksums.json",
                json.dumps(checksums, ensure_ascii=False, indent=2),
                compress_type=zipfile.ZIP_DEFLATED,
            )
    return output_path


def embed_metadata_file(
    image_path: Path,
    sidecar_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    image_path = image_path.expanduser().resolve()
    sidecar_path = (sidecar_path or default_sidecar_path(image_path)).expanduser().resolve()
    output_path = (
        output_path
        or image_path.with_name(f"{image_path.stem}.igpmeta{image_path.suffix}")
    ).expanduser().resolve()
    validate_sidecar_pair(image_path, sidecar_path, strict_name=False)
    metadata = read_sidecar(sidecar_path)
    payload = {
        "format": "igp-embedded-metadata",
        "format_name": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "embedded_at": utc_now(),
        "metadata": metadata,
    }
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = image_path.read_bytes()
    suffix = image_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        output = _embed_jpeg_xmp(data, text)
    elif suffix == ".png":
        output = _embed_png_itxt(data, text)
    else:
        raise UnsupportedMetadataFormat(
            "Metadata embedding currently supports JPEG and PNG. "
            f"Use IGP package mode for {image_path.suffix or 'this file'}."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output)
    return output_path


def _embed_jpeg_xmp(data: bytes, json_text: str) -> bytes:
    if not data.startswith(b"\xff\xd8"):
        raise UnsupportedMetadataFormat("Not a JPEG file.")
    xmp_packet = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description xmlns:igp="https://igp.local/ns/1.0/" igp:format="igp">'
        f"<igp:metadata>{escape(json_text)}</igp:metadata>"
        "</rdf:Description>"
        "</rdf:RDF>"
        "</x:xmpmeta>"
    )
    payload = b"http://ns.adobe.com/xap/1.0/\x00" + xmp_packet.encode("utf-8")
    if len(payload) + 2 > 0xFFFF:
        raise ValueError("Metadata is too large for a single JPEG XMP segment.")
    segment = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    insert_at = _jpeg_metadata_insert_pos(data)
    return data[:insert_at] + segment + data[insert_at:]


def _jpeg_metadata_insert_pos(data: bytes) -> int:
    pos = 2
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if marker in {0xDA, 0xD9}:
            break
        if marker == 0xD8:
            pos += 2
            continue
        if marker == 0xFE or 0xE0 <= marker <= 0xEF:
            segment_length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
            if segment_length < 2:
                break
            pos += 2 + segment_length
            continue
        break
    return pos


def _embed_png_itxt(data: bytes, json_text: str) -> bytes:
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        raise UnsupportedMetadataFormat("Not a PNG file.")
    iend_at = data.rfind(b"IEND")
    if iend_at < 4:
        raise ValueError("PNG IEND chunk not found.")
    chunk_start = iend_at - 4
    text_data = b"IGP\x00\x00\x00\x00\x00" + json_text.encode("utf-8")
    chunk_type = b"iTXt"
    crc = zlib.crc32(chunk_type + text_data) & 0xFFFFFFFF
    chunk = (
        struct.pack(">I", len(text_data))
        + chunk_type
        + text_data
        + struct.pack(">I", crc)
    )
    return data[:chunk_start] + chunk + data[chunk_start:]
