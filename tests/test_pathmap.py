from dataclasses import FrozenInstanceError, replace
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from fastq_sheet_audit.inventory import InventoryCategory, InventoryRecord
from fastq_sheet_audit.pathmap import ExportMode, TargetStyle, preview_paths, render_path


def record(relative="run1/A_R1.fastq.gz"):
    path = Path(relative)
    return InventoryRecord(Path("/local/scan") / path, path, None, InventoryCategory.UNPARSED)


def test_local_absolute_is_not_rewritten():
    item = replace(record(), path=Path("/local/scan/../linked/A_R1.fastq.gz"))
    assert render_path(item, ExportMode.LOCAL_ABSOLUTE) == str(item.path)


def test_relative_uses_local_representation():
    item = record()
    assert render_path(item, ExportMode.RELATIVE_TO_ROOT) == str(item.relative_path)


@pytest.mark.parametrize("style, root, expected", [
    (TargetStyle.POSIX, "/data/projects/Project17", "/data/projects/Project17/run1/A_R1.fastq.gz"),
    (TargetStyle.WINDOWS, "D:\\Sequencing\\Project17", "D:\\Sequencing\\Project17\\run1\\A_R1.fastq.gz"),
    (TargetStyle.WINDOWS, "\\\\server\\share\\Project17", "\\\\server\\share\\Project17\\run1\\A_R1.fastq.gz"),
])
def test_rebased_paths(style, root, expected):
    assert render_path(record(), ExportMode.REBASED_ROOT, target_root=root, target_style=style) == expected


@pytest.mark.parametrize("style, root, expected", [
    (TargetStyle.POSIX, "/data/项目 17", "/data/项目 17/run α/Sample β_R1.fastq.gz"),
    (TargetStyle.WINDOWS, "D:\\项目 17", "D:\\项目 17\\run α\\Sample β_R1.fastq.gz"),
])
def test_spaces_and_unicode(style, root, expected):
    item = record("run α/Sample β_R1.fastq.gz")
    assert render_path(item, ExportMode.REBASED_ROOT, target_root=root, target_style=style) == expected


@pytest.mark.parametrize("style, root", [
    (TargetStyle.POSIX, None), (TargetStyle.WINDOWS, ""),
    (None, "/data"), ("posix", "/data"),
    (TargetStyle.POSIX, "relative/root"),
    (TargetStyle.POSIX, "D:\\Sequencing"),
    (TargetStyle.WINDOWS, "/data/projects"),
    (TargetStyle.WINDOWS, "D:relative"),
    (TargetStyle.WINDOWS, "\\rooted_without_drive"),
    (TargetStyle.WINDOWS, "relative\\root"),
])
def test_invalid_missing_or_wrong_style_roots(style, root):
    with pytest.raises(ValueError):
        render_path(record(), ExportMode.REBASED_ROOT, target_root=root, target_style=style)


@pytest.mark.parametrize("relative", ["../A.fastq", "run/../A.fastq", ".", "/absolute/A.fastq"])
@pytest.mark.parametrize("mode", list(ExportMode))
def test_unsafe_relative_components_are_rejected(relative, mode):
    options = ({"target_root": "/target", "target_style": TargetStyle.POSIX}
               if mode is ExportMode.REBASED_ROOT else {})
    with pytest.raises(ValueError, match="relative path"):
        render_path(record(relative), mode, **options)


def test_windows_rebase_does_not_reinterpret_local_components():
    # These are individual POSIX components but unsafe under Windows grammar.
    for relative in (PurePosixPath("D:/A.fastq"), PurePosixPath("run\\..\\A.fastq")):
        item = replace(record(), relative_path=relative)
        with pytest.raises(ValueError, match="component"):
            render_path(item, ExportMode.REBASED_ROOT,
                        target_root="C:\\target", target_style=TargetStyle.WINDOWS)


def test_explicit_target_style_independent_of_local_path_flavor():
    for relative in (PurePosixPath("run1/A_R1.fastq.gz"), PureWindowsPath("run1/A_R1.fastq.gz")):
        item = replace(record(), relative_path=relative)
        assert render_path(item, ExportMode.REBASED_ROOT,
                           target_root="/data", target_style=TargetStyle.POSIX) == "/data/run1/A_R1.fastq.gz"
        assert render_path(item, ExportMode.REBASED_ROOT,
                           target_root="D:\\data", target_style=TargetStyle.WINDOWS) == "D:\\data\\run1\\A_R1.fastq.gz"


def test_no_filesystem_access(tmp_path, monkeypatch):
    item = record()

    def fail(*args, **kwargs):
        pytest.fail("rendering accessed filesystem")

    for method in ("stat", "resolve", "open", "exists"):
        monkeypatch.setattr(Path, method, fail)
    for mode in ExportMode:
        options = ({"target_root": "D:\\not present", "target_style": TargetStyle.WINDOWS}
                   if mode is ExportMode.REBASED_ROOT else {})
        assert render_path(item, mode, **options)


def test_preview_is_deterministic_and_preserves_records():
    first, second = record("z/B.fastq"), record("a/A.fastq")
    items = [first, second, first]
    preview = preview_paths(items, ExportMode.RELATIVE_TO_ROOT)
    assert preview_paths(reversed(items), ExportMode.RELATIVE_TO_ROOT) == preview
    assert tuple(entry.record for entry in preview.paths) == (second, first, first)
    assert preview.paths[0].record is second
    assert items == [first, second, first]


def test_preview_keeps_original_target_options():
    preview = preview_paths([record()], ExportMode.REBASED_ROOT,
                            target_root="/data/项目", target_style=TargetStyle.POSIX)
    assert preview.target_root == "/data/项目"
    assert preview.target_style is TargetStyle.POSIX
    assert preview.paths[0].rendered_path == "/data/项目/run1/A_R1.fastq.gz"


def test_empty_preview_still_validates_options():
    with pytest.raises(ValueError, match="root"):
        preview_paths([], ExportMode.REBASED_ROOT)


def test_local_path_must_already_be_absolute():
    with pytest.raises(ValueError, match="local path"):
        render_path(replace(record(), path=Path("relative.fastq")), ExportMode.LOCAL_ABSOLUTE)


def test_preview_is_immutable():
    preview = preview_paths([record()], ExportMode.LOCAL_ABSOLUTE)
    with pytest.raises(FrozenInstanceError):
        preview.paths = ()
    with pytest.raises(FrozenInstanceError):
        preview.paths[0].rendered_path = "changed"
