"""Files capability - read, write, and manage files."""

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from alfred.common import get_logger
from alfred.common.models import TaskResult, TaskStatus
from alfred.daemon.capabilities.base import BaseCapability

logger = get_logger(__name__)

# Maximum file size to read (10MB)
MAX_READ_SIZE = 10 * 1024 * 1024


class FilesCapability(BaseCapability):
    """Read, write, and manage files."""

    def __init__(self, work_dir: str = "/tmp/alfred"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "files"

    @property
    def actions(self) -> list[str]:
        return [
            "read",
            "write",
            "append",
            "delete",
            "move",
            "copy",
            "list",
            "exists",
            "info",
            "mkdir",
        ]

    async def execute(
        self, action: str, params: dict[str, Any], task_id: str
    ) -> TaskResult:
        """Execute a file action."""
        started_at = datetime.utcnow()

        try:
            handler = {
                "read": self._read_file,
                "write": self._write_file,
                "append": self._append_file,
                "delete": self._delete_file,
                "move": self._move_file,
                "copy": self._copy_file,
                "list": self._list_dir,
                "exists": self._exists,
                "info": self._file_info,
                "mkdir": self._mkdir,
            }.get(action)

            if not handler:
                return TaskResult(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error=f"Unknown action: {action}",
                    started_at=started_at,
                    completed_at=datetime.utcnow(),
                )

            return await handler(task_id, params, started_at)

        except Exception as e:
            logger.exception("files_action_failed", action=action, task_id=task_id)
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=str(e),
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

    async def _read_file(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Read contents of a file."""
        path = params.get("path")
        if not path:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'path' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        file_path = Path(path).expanduser()
        if not file_path.exists():
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=f"File not found: {path}",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        if file_path.stat().st_size > MAX_READ_SIZE:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=f"File too large (>{MAX_READ_SIZE} bytes)",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        encoding = params.get("encoding", "utf-8")
        try:
            content = file_path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            content = file_path.read_bytes().decode("utf-8", errors="replace")

        logger.info("file_read", path=str(file_path), size=len(content), task_id=task_id)

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=content,
            data={"path": str(file_path), "size": len(content)},
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

    async def _write_file(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Write content to a file."""
        path = params.get("path")
        content = params.get("content")

        if not path:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'path' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        if content is None:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'content' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        file_path = Path(path).expanduser()
        file_path.parent.mkdir(parents=True, exist_ok=True)

        encoding = params.get("encoding", "utf-8")
        file_path.write_text(content, encoding=encoding)

        logger.info("file_written", path=str(file_path), size=len(content), task_id=task_id)

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=f"Written {len(content)} bytes to {path}",
            data={"path": str(file_path), "size": len(content)},
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

    async def _append_file(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Append content to a file."""
        path = params.get("path")
        content = params.get("content")

        if not path or content is None:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'path' or 'content' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        file_path = Path(path).expanduser()
        file_path.parent.mkdir(parents=True, exist_ok=True)

        encoding = params.get("encoding", "utf-8")
        with file_path.open("a", encoding=encoding) as f:
            f.write(content)

        logger.info("file_appended", path=str(file_path), size=len(content), task_id=task_id)

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=f"Appended {len(content)} bytes to {path}",
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

    async def _delete_file(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Delete a file or directory."""
        path = params.get("path")
        if not path:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'path' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        file_path = Path(path).expanduser()
        if not file_path.exists():
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.COMPLETED,
                output=f"Path does not exist: {path}",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        if file_path.is_dir():
            recursive = params.get("recursive", False)
            if recursive:
                shutil.rmtree(file_path)
            else:
                file_path.rmdir()
        else:
            file_path.unlink()

        logger.info("file_deleted", path=str(file_path), task_id=task_id)

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=f"Deleted: {path}",
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

    async def _move_file(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Move a file or directory."""
        source = params.get("source")
        destination = params.get("destination")

        if not source or not destination:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'source' or 'destination' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        src_path = Path(source).expanduser()
        dst_path = Path(destination).expanduser()

        if not src_path.exists():
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=f"Source not found: {source}",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))

        logger.info("file_moved", source=str(src_path), destination=str(dst_path), task_id=task_id)

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=f"Moved {source} to {destination}",
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

    async def _copy_file(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Copy a file or directory."""
        source = params.get("source")
        destination = params.get("destination")

        if not source or not destination:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'source' or 'destination' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        src_path = Path(source).expanduser()
        dst_path = Path(destination).expanduser()

        if not src_path.exists():
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=f"Source not found: {source}",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if src_path.is_dir():
            shutil.copytree(str(src_path), str(dst_path))
        else:
            shutil.copy2(str(src_path), str(dst_path))

        logger.info("file_copied", source=str(src_path), destination=str(dst_path), task_id=task_id)

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=f"Copied {source} to {destination}",
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

    async def _list_dir(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """List contents of a directory."""
        path = params.get("path", ".")
        dir_path = Path(path).expanduser()

        if not dir_path.exists():
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=f"Directory not found: {path}",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        if not dir_path.is_dir():
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=f"Not a directory: {path}",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        entries = []
        for entry in sorted(dir_path.iterdir()):
            stat = entry.stat()
            entries.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "size": stat.st_size if entry.is_file() else None,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })

        output = "\n".join(
            f"{'[D]' if e['type'] == 'directory' else '[F]'} {e['name']}"
            for e in entries
        )

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=output or "(empty directory)",
            data={"path": str(dir_path), "entries": entries},
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

    async def _exists(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Check if a path exists."""
        path = params.get("path")
        if not path:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'path' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        file_path = Path(path).expanduser()
        exists = file_path.exists()

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=f"{'Exists' if exists else 'Does not exist'}: {path}",
            data={"exists": exists, "path": str(file_path)},
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

    async def _file_info(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Get detailed information about a file."""
        path = params.get("path")
        if not path:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'path' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        file_path = Path(path).expanduser()
        if not file_path.exists():
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error=f"Path not found: {path}",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        stat = file_path.stat()
        info = {
            "path": str(file_path.absolute()),
            "name": file_path.name,
            "type": "directory" if file_path.is_dir() else "file",
            "size": stat.st_size,
            "mode": oct(stat.st_mode),
            "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "accessed": datetime.fromtimestamp(stat.st_atime).isoformat(),
        }

        output = "\n".join(f"{k}: {v}" for k, v in info.items())

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=output,
            data=info,
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )

    async def _mkdir(
        self, task_id: str, params: dict[str, Any], started_at: datetime
    ) -> TaskResult:
        """Create a directory."""
        path = params.get("path")
        if not path:
            return TaskResult(
                task_id=task_id,
                status=TaskStatus.FAILED,
                error="Missing 'path' parameter",
                started_at=started_at,
                completed_at=datetime.utcnow(),
            )

        dir_path = Path(path).expanduser()
        parents = params.get("parents", True)

        dir_path.mkdir(parents=parents, exist_ok=True)

        logger.info("directory_created", path=str(dir_path), task_id=task_id)

        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            output=f"Created directory: {path}",
            started_at=started_at,
            completed_at=datetime.utcnow(),
        )
