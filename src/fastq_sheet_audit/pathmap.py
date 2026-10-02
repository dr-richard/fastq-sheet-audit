"""Deterministic export path rendering without target filesystem access."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from typing import Iterable

from .inventory import InventoryRecord


class ExportMode(Enum):
    LOCAL_ABSOLUTE = "local_absolute"
    RELATIVE_TO_ROOT = "relative_to_root"
    REBASED_ROOT = "rebased_root"


class TargetStyle(Enum):
    POSIX = "posix"
    WINDOWS = "windows"


@dataclass(frozen=True)
class PathPreview:
    record: InventoryRecord
    rendered_path: str


@dataclass(frozen=True)
class ExportPreview:
    mode: ExportMode
    target_style: TargetStyle | None
    target_root: str | None
    paths: tuple[PathPreview, ...]


def _validate_options(
    mode: ExportMode, target_root: str | None, target_style: TargetStyle | None,
) -> PurePath | None:
    if not isinstance(mode, ExportMode):
        raise ValueError("mode must be an ExportMode")
    if mode is not ExportMode.REBASED_ROOT:
        if target_root is not None or target_style is not None:
            raise ValueError("target root/style apply only to REBASED_ROOT")
        return None
    if not isinstance(target_root, str) or not target_root:
        raise ValueError("REBASED_ROOT requires a target root")
    if not isinstance(target_style, TargetStyle):
        raise ValueError("REBASED_ROOT requires an explicit target style")
    root = (PurePosixPath(target_root) if target_style is TargetStyle.POSIX
            else PureWindowsPath(target_root))
    if not root.is_absolute():
        raise ValueError(f"target root must be absolute for {target_style.name} style")
    return root


def _render(record: InventoryRecord, mode: ExportMode, root: PurePath | None) -> str:
    relative = record.relative_path
    # Path objects already remove '.' when constructed; reject any unsafe
    # components still represented in the supplied inventory path, plus an
    # empty/dot-only path. Never resolve a path to eliminate '..'.
    if relative.anchor or not relative.parts or any(part in (".", "..") for part in relative.parts):
        raise ValueError("inventory relative path must be nonempty and contain no '.' or '..' components")
    if mode is ExportMode.LOCAL_ABSOLUTE:
        if not record.path.is_absolute():
            raise ValueError("inventory local path must be absolute")
        return str(record.path)
    if mode is ExportMode.RELATIVE_TO_ROOT:
        return str(relative)

    # Validate each component under the explicit target grammar before joining.
    # A POSIX filename containing a Windows separator/drive must not silently
    # become a different Windows path or replace the supplied root.
    path_type = type(root)
    for part in relative.parts:
        component = path_type(part)
        if component.anchor or component.parts != (part,):
            raise ValueError(f"relative component cannot be preserved in target style: {part!r}")
    return str(root.joinpath(*relative.parts))


def render_path(
    record: InventoryRecord, mode: ExportMode, *,
    target_root: str | None = None, target_style: TargetStyle | None = None,
) -> str:
    """Render one path; target style is explicit and never inferred from OS."""
    return _render(record, mode, _validate_options(mode, target_root, target_style))


def preview_paths(
    records: Iterable[InventoryRecord], mode: ExportMode, *,
    target_root: str | None = None, target_style: TargetStyle | None = None,
) -> ExportPreview:
    """Return immutable previews sorted by original relative/local paths.

    Original inventory objects and duplicate entries are retained. Local paths
    are not resolved, expanded, or rewritten. Rebasing uses pure target paths
    and never probes either filesystem. Options are validated even if empty.
    """
    root = _validate_options(mode, target_root, target_style)
    ordered = sorted(records, key=lambda record: (
        record.relative_path.as_posix(), record.path.as_posix(),
        record.category.value, repr(record.parsed_name),
    ))
    return ExportPreview(mode, target_style, target_root, tuple(
        PathPreview(record, _render(record, mode, root)) for record in ordered
    ))
