import json
from pathlib import Path

from tests.support.fixtures import FixtureLoaderError, ProductFixtureSnapshotLoader

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "fixtures" / "data" / "google"


def test_fixture_loader__loads_snapshot__deterministically() -> None:
    loader = ProductFixtureSnapshotLoader(FIXTURE_ROOT)

    first = loader.load_snapshot("workspace/product_fixture_v1.json")
    second = loader.load_snapshot("workspace/product_fixture_v1.json")

    assert first == second
    assert first.manifest.snapshot_id == "product-fixture-v1"
    assert len(first.resources) >= 10


def test_fixture_loader__blocks_duplicate__resource_ids(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    (root / "a.json").write_text(
        json.dumps(
            {
                "resource_type": "gmail_thread",
                "resource_id": "dup",
                "parent_id": None,
                "related_resource_ids": [],
                "version": "1",
                "recovery_fingerprint": "rf-1",
                "payload": {"subject": "A"},
            }
        ),
        encoding="utf-8",
    )
    (root / "b.json").write_text(
        json.dumps(
            {
                "resource_type": "gmail_thread",
                "resource_id": "dup",
                "parent_id": None,
                "related_resource_ids": [],
                "version": "1",
                "recovery_fingerprint": "rf-2",
                "payload": {"subject": "B"},
            }
        ),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_id": "dup-test",
                "resources": [{"path": "a.json"}, {"path": "b.json"}],
                "faults": [],
            }
        ),
        encoding="utf-8",
    )

    loader = ProductFixtureSnapshotLoader(root)
    try:
        loader.load_snapshot("manifest.json")
    except FixtureLoaderError as error:
        assert "duplicate resource id" in str(error)
    else:
        raise AssertionError("expected duplicate resource id failure")


def test_fixture_loader__blocks_broken__relations(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    (root / "only.json").write_text(
        json.dumps(
            {
                "resource_type": "task",
                "resource_id": "task-1",
                "parent_id": "missing",
                "related_resource_ids": [],
                "version": "1",
                "recovery_fingerprint": "rf-task",
                "payload": {"title": "Task"},
            }
        ),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_id": "broken-relations",
                "resources": [{"path": "only.json"}],
                "faults": [],
            }
        ),
        encoding="utf-8",
    )

    loader = ProductFixtureSnapshotLoader(root)
    try:
        loader.load_snapshot("manifest.json")
    except FixtureLoaderError as error:
        assert "missing parent relation" in str(error)
    else:
        raise AssertionError("expected broken relation failure")


def test_fixture_loader__blocks_path__traversal(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    (root / "only.json").write_text(
        json.dumps(
            {
                "resource_type": "task",
                "resource_id": "task-1",
                "parent_id": None,
                "related_resource_ids": [],
                "version": "1",
                "recovery_fingerprint": "rf-task",
                "payload": {"title": "Task"},
            }
        ),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "snapshot_id": "path-traversal",
                "resources": [{"path": "only.json"}],
                "faults": [{"path": "../outside.json"}],
            }
        ),
        encoding="utf-8",
    )

    loader = ProductFixtureSnapshotLoader(root)
    try:
        loader.load_snapshot("manifest.json")
    except FixtureLoaderError as error:
        assert "path traversal" in str(error)
    else:
        raise AssertionError("expected path traversal failure")


def test_fixture_loader__blocks_invalid_json__and_unsupported_type(tmp_path: Path) -> None:
    root = tmp_path / "fixtures"
    root.mkdir()
    (root / "bad.json").write_text("{", encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps({"snapshot_id": "bad", "resources": [{"path": "bad.json"}], "faults": []}),
        encoding="utf-8",
    )

    loader = ProductFixtureSnapshotLoader(root)
    try:
        loader.load_snapshot("manifest.json")
    except FixtureLoaderError as error:
        assert "invalid JSON fixture" in str(error)
    else:
        raise AssertionError("expected invalid JSON failure")

    (root / "unsupported.json").write_text(
        json.dumps(
            {
                "resource_type": "unknown_type",
                "resource_id": "x",
                "parent_id": None,
                "related_resource_ids": [],
                "version": "1",
                "recovery_fingerprint": "rf-x",
                "payload": {},
            }
        ),
        encoding="utf-8",
    )
    (root / "manifest-unsupported.json").write_text(
        json.dumps(
            {
                "snapshot_id": "unsupported",
                "resources": [{"path": "unsupported.json"}],
                "faults": [],
            }
        ),
        encoding="utf-8",
    )
    try:
        loader.load_snapshot("manifest-unsupported.json")
    except FixtureLoaderError as error:
        assert "unsupported resource_type" in str(error)
    else:
        raise AssertionError("expected unsupported resource type failure")
