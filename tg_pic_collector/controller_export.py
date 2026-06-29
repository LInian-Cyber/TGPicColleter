from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .igp import (
    UnsupportedMetadataFormat,
    create_igp_package,
    default_sidecar_path,
    discover_sidecar_pairs,
    embed_metadata_file,
    image_path_from_sidecar,
    validate_sidecar_pair,
)


class ExportControllerMixin:
    @staticmethod
    def _available_export_path(path: Path) -> Path:
        if not path.exists():
            return path
        for index in range(2, 10000):
            candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
            if not candidate.exists():
                return candidate
        return path.with_name(
            f"{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix}"
        )

    def _single_export_pair(self, target: Path) -> tuple[Path, Path]:
        sidecar_image = image_path_from_sidecar(target)
        if sidecar_image is not None:
            image_path = sidecar_image
            sidecar_path = target
        else:
            image_path = target
            sidecar_path = default_sidecar_path(image_path)
        validate_sidecar_pair(image_path, sidecar_path, strict_name=True)
        return image_path, sidecar_path

    def _export_text(self, zh: str, en: str) -> str:
        return en if getattr(self.window, "_language", "zh_CN") == "en_US" else zh

    def export_images(self, params: dict) -> None:
        source_raw = str(params.get("source_path", "")).strip()
        if not source_raw:
            self.window.show_error("请先选择来源")
            return
        source_path = Path(source_raw).expanduser().resolve()
        if not source_path.exists():
            self.window.show_error("来源不存在")
            return

        mode = str(params.get("mode", "igp")).strip()
        if mode not in {"igp", "metadata"}:
            self.window.show_error("导出模式无效")
            return

        try:
            if source_path.is_dir():
                pairs, orphan_images, orphan_sidecars = discover_sidecar_pairs(
                    source_path,
                    recursive=bool(params.get("recursive", False)),
                )
            else:
                pairs = [self._single_export_pair(source_path)]
                orphan_images = 0
                orphan_sidecars = 0
        except (OSError, ValueError) as exc:
            self.window.show_error(str(exc))
            return

        skipped = orphan_images + orphan_sidecars
        if not pairs:
            summary = self._export_text(
                f"没有找到可导出的匹配文件。跳过不匹配 {skipped} 个。",
                f"No matched files found. Skipped {skipped} unmatched files.",
            )
            self.window.set_export_result(summary, [])
            self.window.show_error("没有找到可导出的匹配文件")
            return

        output_raw = str(params.get("output_path", "")).strip()
        output_dir = Path(output_raw).expanduser().resolve() if output_raw else None
        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)

        igp_options = dict(params.get("igp_options", {}) or {})
        metadata_sections = igp_options.get("metadata_sections")
        include_checksums = bool(igp_options.get("include_checksums", True))

        rows: list[dict] = []
        succeeded = 0
        failed = 0
        for image_path, sidecar_path in pairs:
            target_dir = output_dir or image_path.parent
            target_dir.mkdir(parents=True, exist_ok=True)
            try:
                if mode == "igp":
                    output_path = self._available_export_path(
                        target_dir / f"{image_path.stem}.igp"
                    )
                    result = create_igp_package(
                        image_path,
                        sidecar_path,
                        output_path,
                        metadata_sections=metadata_sections,
                        include_checksums=include_checksums,
                    )
                    mode_label = "IGP"
                else:
                    output_path = self._available_export_path(
                        target_dir / f"{image_path.stem}.igpmeta{image_path.suffix}"
                    )
                    result = embed_metadata_file(image_path, sidecar_path, output_path)
                    mode_label = self._export_text("元数据", "Metadata")
                succeeded += 1
                rows.append(
                    {
                        "file": image_path.name,
                        "mode": mode_label,
                        "status": self._export_text("成功", "Done"),
                        "output": str(result),
                        "message": "",
                    }
                )
            except (OSError, ValueError, UnsupportedMetadataFormat) as exc:
                failed += 1
                rows.append(
                    {
                        "file": image_path.name,
                        "mode": "IGP" if mode == "igp" else self._export_text("元数据", "Metadata"),
                        "status": self._export_text("失败", "Failed"),
                        "output": "",
                        "message": str(exc),
                    }
                )

        summary = self._export_text(
            f"导出完成：成功 {succeeded}，失败 {failed}，跳过不匹配 {skipped}。",
            f"Export complete: {succeeded} succeeded, {failed} failed, {skipped} unmatched skipped.",
        )
        self.window.set_export_result(summary, rows)
        if failed:
            self.window.show_info("导出完成，部分文件失败")
        else:
            self.window.show_success("导出完成")
