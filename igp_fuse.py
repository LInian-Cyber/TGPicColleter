from __future__ import annotations

import argparse
from pathlib import Path
import sys

from tg_pic_collector.igp import (
    UnsupportedMetadataFormat,
    create_igp_package,
    default_sidecar_path,
    discover_sidecar_pairs,
    embed_metadata_file,
    image_path_from_sidecar,
    validate_sidecar_pair,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fuse a downloaded image and its .igp.json sidecar into embedded metadata or an .igp package.",
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Image file or directory containing images with .igp.json sidecars.",
    )
    parser.add_argument(
        "--mode",
        choices=("igp", "embed", "metadata"),
        default="igp",
        help="Output format: igp creates a .igp package; embed/metadata writes metadata into JPEG/PNG.",
    )
    parser.add_argument(
        "--sidecar",
        type=Path,
        help="Metadata sidecar path for single-file mode. Defaults to <image>.igp.json.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for single-file mode. Defaults to <image>.igp or <image>.igpmeta<ext>.",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="When input is a directory, scan subdirectories too.",
    )
    return parser.parse_args()


def fuse_one(
    image_path: Path,
    mode: str,
    sidecar_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    sidecar = sidecar_path or default_sidecar_path(image_path)
    validate_sidecar_pair(image_path, sidecar, strict_name=sidecar_path is None)
    if mode == "igp":
        return create_igp_package(image_path, sidecar, output_path)
    return embed_metadata_file(image_path, sidecar, output_path)


def resolve_single_input(target: Path) -> tuple[Path, Path | None]:
    if image_path_from_sidecar(target) is not None:
        image_path = image_path_from_sidecar(target)
        if image_path is None:
            raise ValueError(f"Invalid sidecar name: {target}")
        return image_path, target
    return target, None


def main() -> int:
    args = parse_args()
    mode = "embed" if args.mode == "metadata" else args.mode
    target = args.input.expanduser()

    if target.is_dir():
        if args.sidecar or args.output:
            print("--sidecar and --output are only available for single-file mode.", file=sys.stderr)
            return 2
        pairs, orphan_images, orphan_sidecars = discover_sidecar_pairs(target, args.recursive)
        if orphan_images or orphan_sidecars:
            print(
                f"Skipped unmatched files: {orphan_images} images without sidecars, "
                f"{orphan_sidecars} sidecars without matching images.",
                file=sys.stderr,
            )
        if not pairs:
            print("No images with .igp.json sidecars found.", file=sys.stderr)
            return 1
        failed = 0
        for image_path, sidecar_path in pairs:
            try:
                output = fuse_one(image_path, mode, sidecar_path)
                print(output)
            except (OSError, ValueError, UnsupportedMetadataFormat) as exc:
                failed += 1
                print(f"FAILED {image_path}: {exc}", file=sys.stderr)
        return 1 if failed else 0

    if not target.exists():
        print(f"Input not found: {target}", file=sys.stderr)
        return 2
    try:
        image_path, inferred_sidecar = resolve_single_input(target)
        sidecar_path = args.sidecar or inferred_sidecar
        output = fuse_one(image_path, mode, sidecar_path, args.output)
    except (OSError, ValueError, UnsupportedMetadataFormat) as exc:
        print(f"FAILED {target}: {exc}", file=sys.stderr)
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
