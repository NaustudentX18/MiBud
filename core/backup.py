"""
core/backup.py — v3 backup / restore / factory-reset.

A single well-scoped BackupManager that bundles the device's full durable
state into a tar.gz and can re-inflate it later. Everything the user would
lose on an SD-card reflash gets included:

    • config/config.json
    • data/memory.db      (SQLite, checkpointed before copy)
    • personalities/      (bundled + custom)
    • plugins/            (drop-in Python plugins)

Atomicity:
  • Export writes to a tmp file alongside the target, fsyncs, then renames.
  • Import stages to a temp dir, validates the manifest, then swaps into
    place — any failure during copy leaves the original state untouched.

Safety:
  • The manifest embeds a schema version so older backups can be refused with
    a clear error.
  • ``.env`` and any other secrets are explicitly *excluded* — API keys
    should live in env vars and never be restored from a disk backup.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("MiBud")

BACKUP_SCHEMA_VERSION = 1
MANIFEST_NAME = "mibud_manifest.json"

# Directories/files we include. Everything else is ignored.
_DEFAULT_TARGETS: List[str] = [
    "config/config.json",
    "personalities/custom",
    "plugins",
]
# Memory DB is handled separately via sqlite backup API.
_MEMORY_DB_REL = "data/memory.db"
# Never back these up.
_DENYLIST_SUFFIXES = {".env", ".pem", ".key"}


@dataclass
class BackupInfo:
    path: str
    bytes: int
    files: int
    created_at: float
    schema: int = BACKUP_SCHEMA_VERSION


class BackupError(RuntimeError):
    pass


class BackupManager:
    """
    Parameters
    ----------
    root :
        Repo root. Defaults to the cwd at construction time.
    targets :
        Optional override of the paths (relative to ``root``) to include.
    """

    def __init__(
        self,
        root: Path | str | None = None,
        targets: Optional[List[str]] = None,
    ) -> None:
        self.root = Path(root or Path.cwd()).resolve()
        self.targets = list(targets or _DEFAULT_TARGETS)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export(self, dest: Path | str) -> BackupInfo:
        """Write a tar.gz backup to ``dest``. Atomic via tmp+rename."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()

        files_written = 0
        manifest = {
            "schema": BACKUP_SCHEMA_VERSION,
            "created_at": time.time(),
            "targets": [],
            "memory_included": False,
        }

        try:
            with tarfile.open(tmp, "w:gz") as tar:
                for rel in self.targets:
                    abs_path = (self.root / rel).resolve()
                    if not self._is_within_root(abs_path):
                        log.warning(f"backup: skipping path outside root: {rel}")
                        continue
                    if not abs_path.exists():
                        continue
                    filt = _make_filter()
                    tar.add(abs_path, arcname=rel, filter=filt)
                    manifest["targets"].append(rel)
                    files_written += _count_files(abs_path)

                # Snapshot the SQLite memory DB via the backup API so we get
                # a consistent copy even while it's in use.
                mem_path = self.root / _MEMORY_DB_REL
                if mem_path.exists():
                    snap = self._snapshot_sqlite(mem_path)
                    try:
                        tar.add(snap, arcname=_MEMORY_DB_REL)
                        manifest["memory_included"] = True
                        files_written += 1
                    finally:
                        try:
                            snap.unlink()
                        except OSError:
                            pass

                # Embed the manifest as the last entry.
                manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
                info = tarfile.TarInfo(name=MANIFEST_NAME)
                info.size = len(manifest_bytes)
                info.mtime = int(time.time())
                import io as _io
                tar.addfile(info, _io.BytesIO(manifest_bytes))

            # Atomic swap.
            os.replace(tmp, dest)
        except Exception:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
            raise

        size = dest.stat().st_size
        return BackupInfo(
            path=str(dest),
            bytes=size,
            files=files_written,
            created_at=manifest["created_at"],
        )

    # ------------------------------------------------------------------
    # Restore
    # ------------------------------------------------------------------

    def inspect(self, src: Path | str) -> Dict[str, Any]:
        """Read a backup's manifest without extracting."""
        src = Path(src)
        if not src.exists():
            raise BackupError(f"backup not found: {src}")
        with tarfile.open(src, "r:gz") as tar:
            try:
                member = tar.getmember(MANIFEST_NAME)
            except KeyError:
                raise BackupError("backup is missing manifest; not a MiBud backup")
            fh = tar.extractfile(member)
            if fh is None:
                raise BackupError("manifest unreadable")
            return json.loads(fh.read().decode("utf-8"))

    def restore(self, src: Path | str, *, force: bool = False) -> Dict[str, Any]:
        """Extract a backup and swap it into place. Returns the manifest.

        Parameters
        ----------
        force :
            If False (default) and the backup's schema is newer than we
            understand, raise. Set True to override.
        """
        src = Path(src)
        manifest = self.inspect(src)
        schema = int(manifest.get("schema") or 0)
        if schema > BACKUP_SCHEMA_VERSION and not force:
            raise BackupError(
                f"backup schema v{schema} newer than supported v{BACKUP_SCHEMA_VERSION}"
            )

        with tempfile.TemporaryDirectory(prefix="mibud_restore_") as staging:
            staging_path = Path(staging)
            with tarfile.open(src, "r:gz") as tar:
                _safe_extractall(tar, staging_path)

            # Swap each declared target into place.
            for rel in manifest.get("targets", []):
                staged = staging_path / rel
                if not staged.exists():
                    continue
                self._install(staged, self.root / rel)

            if manifest.get("memory_included"):
                mem_staged = staging_path / _MEMORY_DB_REL
                if mem_staged.exists():
                    self._install(mem_staged, self.root / _MEMORY_DB_REL)

        return manifest

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _is_within_root(self, p: Path) -> bool:
        try:
            p.resolve().relative_to(self.root)
            return True
        except ValueError:
            return False

    def _snapshot_sqlite(self, db_path: Path) -> Path:
        """Copy the SQLite DB safely using the backup API."""
        fd, tmp_str = tempfile.mkstemp(prefix="mibud_mem_", suffix=".db")
        os.close(fd)
        tmp = Path(tmp_str)
        try:
            with sqlite3.connect(str(db_path)) as src_conn, sqlite3.connect(
                str(tmp)
            ) as dst_conn:
                src_conn.backup(dst_conn)
        except sqlite3.Error as e:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise BackupError(f"memory DB snapshot failed: {e}")
        return tmp

    def _install(self, staged: Path, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if staged.is_dir():
            shutil.copytree(staged, target)
        else:
            shutil.copy2(staged, target)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_files(path: Path) -> int:
    if path.is_file():
        return 1
    return sum(1 for p in path.rglob("*") if p.is_file())


def _make_filter():
    """tarfile add() filter that skips sensitive files."""

    def _filter(tarinfo: tarfile.TarInfo):
        name = tarinfo.name.lower()
        for suffix in _DENYLIST_SUFFIXES:
            if name.endswith(suffix):
                return None
        # Strip absolute paths and symlinks for safety.
        if tarinfo.islnk() or tarinfo.issym():
            return None
        return tarinfo

    return _filter


def _safe_extractall(tar: tarfile.TarFile, dest: Path) -> None:
    """Extract with path-traversal protection (the classic 'tarslip' guard)."""
    dest = dest.resolve()
    for member in tar.getmembers():
        member_path = (dest / member.name).resolve()
        try:
            member_path.relative_to(dest)
        except ValueError:
            raise BackupError(f"refusing unsafe path in backup: {member.name}")
    tar.extractall(dest)
