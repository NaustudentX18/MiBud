"""Tests for core.backup — BackupManager export/restore."""
from __future__ import annotations

import json
import sqlite3
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.backup import (
    BACKUP_SCHEMA_VERSION,
    MANIFEST_NAME,
    BackupError,
    BackupManager,
)


def _populate_root(root: Path) -> None:
    (root / "config").mkdir()
    (root / "config" / "config.json").write_text(json.dumps({"foo": "bar"}))
    (root / "personalities" / "custom").mkdir(parents=True)
    (root / "personalities" / "custom" / "mine.json").write_text('{"name": "mine"}')
    (root / "plugins").mkdir()
    (root / "plugins" / "hello.py").write_text("print('hi')\n")
    (root / "data").mkdir()
    db = root / "data" / "memory.db"
    with sqlite3.connect(str(db)) as c:
        c.execute("CREATE TABLE t (x TEXT)")
        c.execute("INSERT INTO t VALUES ('hello')")


def test_export_creates_tarball_with_manifest(tmp_path):
    _populate_root(tmp_path)
    bm = BackupManager(root=tmp_path)
    dest = tmp_path / "backups" / "b.tar.gz"
    info = bm.export(dest)
    assert dest.exists()
    assert info.bytes > 0
    with tarfile.open(dest, "r:gz") as tar:
        names = tar.getnames()
        assert MANIFEST_NAME in names
        assert "config/config.json" in names
        assert "data/memory.db" in names
        member = tar.getmember(MANIFEST_NAME)
        fh = tar.extractfile(member)
        assert fh is not None
        manifest = json.loads(fh.read().decode("utf-8"))
        assert manifest["schema"] == BACKUP_SCHEMA_VERSION
        assert manifest["memory_included"] is True


def test_export_excludes_env_files(tmp_path):
    _populate_root(tmp_path)
    (tmp_path / ".env").write_text("SECRET=1")
    (tmp_path / "config" / ".env").write_text("SECRET=2")
    bm = BackupManager(
        root=tmp_path,
        targets=["config/config.json", "config/.env", ".env"],
    )
    dest = tmp_path / "b.tar.gz"
    bm.export(dest)
    with tarfile.open(dest, "r:gz") as tar:
        names = tar.getnames()
    assert not any(n.endswith(".env") for n in names)


def test_inspect_returns_manifest(tmp_path):
    _populate_root(tmp_path)
    bm = BackupManager(root=tmp_path)
    dest = tmp_path / "b.tar.gz"
    bm.export(dest)
    manifest = bm.inspect(dest)
    assert manifest["schema"] == BACKUP_SCHEMA_VERSION
    assert "config/config.json" in manifest["targets"]


def test_restore_replaces_config_and_memory(tmp_path):
    _populate_root(tmp_path)
    bm = BackupManager(root=tmp_path)
    dest = tmp_path / "b.tar.gz"
    bm.export(dest)

    # Mutate local state after backup.
    (tmp_path / "config" / "config.json").write_text(json.dumps({"foo": "changed"}))
    db = tmp_path / "data" / "memory.db"
    with sqlite3.connect(str(db)) as c:
        c.execute("INSERT INTO t VALUES ('world')")

    bm.restore(dest)

    restored = json.loads((tmp_path / "config" / "config.json").read_text())
    assert restored == {"foo": "bar"}
    with sqlite3.connect(str(tmp_path / "data" / "memory.db")) as c:
        rows = [r[0] for r in c.execute("SELECT x FROM t")]
    assert rows == ["hello"]


def test_restore_refuses_newer_schema_without_force(tmp_path):
    _populate_root(tmp_path)
    bm = BackupManager(root=tmp_path)
    dest = tmp_path / "b.tar.gz"
    bm.export(dest)
    # Hand-craft a backup with bumped schema.
    fake = tmp_path / "fake.tar.gz"
    import io
    with tarfile.open(fake, "w:gz") as tar:
        manifest = {"schema": BACKUP_SCHEMA_VERSION + 99, "targets": []}
        data = json.dumps(manifest).encode()
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(BackupError):
        bm.restore(fake)
    # With force=True, succeeds.
    manifest = bm.restore(fake, force=True)
    assert manifest["schema"] == BACKUP_SCHEMA_VERSION + 99


def test_export_is_atomic_on_failure(tmp_path, monkeypatch):
    _populate_root(tmp_path)
    bm = BackupManager(root=tmp_path)
    dest = tmp_path / "b.tar.gz"

    # Simulate a failure mid-way through export.
    orig_snap = BackupManager._snapshot_sqlite

    def _boom(self, db_path):
        raise OSError("disk full")

    monkeypatch.setattr(BackupManager, "_snapshot_sqlite", _boom)
    with pytest.raises(Exception):
        bm.export(dest)
    assert not dest.exists()
    # Tmp file is also cleaned up.
    assert not dest.with_suffix(".gz.tmp").exists()
    monkeypatch.setattr(BackupManager, "_snapshot_sqlite", orig_snap)


def test_inspect_rejects_non_mibud_tarball(tmp_path):
    other = tmp_path / "random.tar.gz"
    with tarfile.open(other, "w:gz") as tar:
        data = b"hello"
        info = tarfile.TarInfo("README.txt")
        info.size = len(data)
        import io
        tar.addfile(info, io.BytesIO(data))
    bm = BackupManager(root=tmp_path)
    with pytest.raises(BackupError):
        bm.inspect(other)


def test_restore_blocks_path_traversal(tmp_path):
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        import io
        # Manifest
        manifest = {"schema": 1, "targets": ["../outside"]}
        md = json.dumps(manifest).encode()
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(md)
        tar.addfile(info, io.BytesIO(md))
        # Path-traversal member
        data = b"gotcha"
        info = tarfile.TarInfo("../outside")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    bm = BackupManager(root=tmp_path)
    with pytest.raises(BackupError):
        bm.restore(evil)
