"""Tests for daemon capabilities."""

import os
import tempfile
from pathlib import Path

import pytest

from alfred.common.models import TaskStatus
from alfred.daemon.capabilities import FilesCapability, ShellCapability


@pytest.fixture
def work_dir():
    """Create a temporary working directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def shell_cap(work_dir):
    """Create a shell capability instance."""
    return ShellCapability(work_dir)


@pytest.fixture
def files_cap(work_dir):
    """Create a files capability instance."""
    return FilesCapability(work_dir)


class TestShellCapability:
    """Tests for ShellCapability."""

    async def test_run_simple_command(self, shell_cap):
        """Test running a simple command."""
        result = await shell_cap.execute(
            "run",
            {"command": "echo hello"},
            "test-1",
        )

        assert result.status == TaskStatus.COMPLETED
        assert result.output.strip() == "hello"
        assert result.exit_code == 0

    async def test_run_command_with_cwd(self, shell_cap, work_dir):
        """Test running a command with custom working directory."""
        result = await shell_cap.execute(
            "run",
            {"command": "pwd", "cwd": work_dir},
            "test-2",
        )

        assert result.status == TaskStatus.COMPLETED
        assert work_dir in result.output

    async def test_run_failing_command(self, shell_cap):
        """Test running a command that fails."""
        result = await shell_cap.execute(
            "run",
            {"command": "exit 1"},
            "test-3",
        )

        assert result.status == TaskStatus.FAILED
        assert result.exit_code == 1

    async def test_run_missing_command(self, shell_cap):
        """Test running without a command."""
        result = await shell_cap.execute(
            "run",
            {},
            "test-4",
        )

        assert result.status == TaskStatus.FAILED
        assert "command" in result.error.lower()

    async def test_run_with_timeout(self, shell_cap):
        """Test command timeout."""
        result = await shell_cap.execute(
            "run",
            {"command": "sleep 5", "timeout": 1},
            "test-5",
        )

        assert result.status == TaskStatus.FAILED
        assert "timeout" in result.error.lower()

    async def test_list_processes_empty(self, shell_cap):
        """Test listing processes when none are running."""
        result = await shell_cap.execute(
            "list_processes",
            {},
            "test-6",
        )

        assert result.status == TaskStatus.COMPLETED
        assert result.data["processes"] == []


class TestFilesCapability:
    """Tests for FilesCapability."""

    async def test_write_and_read_file(self, files_cap, work_dir):
        """Test writing and reading a file."""
        test_path = os.path.join(work_dir, "test.txt")
        content = "Hello, Alfred!"

        # Write
        write_result = await files_cap.execute(
            "write",
            {"path": test_path, "content": content},
            "test-w1",
        )
        assert write_result.status == TaskStatus.COMPLETED

        # Read
        read_result = await files_cap.execute(
            "read",
            {"path": test_path},
            "test-r1",
        )
        assert read_result.status == TaskStatus.COMPLETED
        assert read_result.output == content

    async def test_read_nonexistent_file(self, files_cap):
        """Test reading a file that doesn't exist."""
        result = await files_cap.execute(
            "read",
            {"path": "/nonexistent/file.txt"},
            "test-r2",
        )

        assert result.status == TaskStatus.FAILED
        assert "not found" in result.error.lower()

    async def test_list_directory(self, files_cap, work_dir):
        """Test listing directory contents."""
        # Create some files
        Path(work_dir, "file1.txt").touch()
        Path(work_dir, "file2.txt").touch()
        Path(work_dir, "subdir").mkdir()

        result = await files_cap.execute(
            "list",
            {"path": work_dir},
            "test-l1",
        )

        assert result.status == TaskStatus.COMPLETED
        assert "file1.txt" in result.output
        assert "file2.txt" in result.output
        assert "subdir" in result.output
        assert len(result.data["entries"]) == 3

    async def test_file_exists(self, files_cap, work_dir):
        """Test checking if a file exists."""
        test_path = os.path.join(work_dir, "exists.txt")
        Path(test_path).touch()

        # File exists
        result = await files_cap.execute(
            "exists",
            {"path": test_path},
            "test-e1",
        )
        assert result.status == TaskStatus.COMPLETED
        assert result.data["exists"] is True

        # File doesn't exist
        result = await files_cap.execute(
            "exists",
            {"path": os.path.join(work_dir, "nope.txt")},
            "test-e2",
        )
        assert result.status == TaskStatus.COMPLETED
        assert result.data["exists"] is False

    async def test_copy_file(self, files_cap, work_dir):
        """Test copying a file."""
        source = os.path.join(work_dir, "source.txt")
        dest = os.path.join(work_dir, "dest.txt")

        Path(source).write_text("copy me")

        result = await files_cap.execute(
            "copy",
            {"source": source, "destination": dest},
            "test-c1",
        )

        assert result.status == TaskStatus.COMPLETED
        assert Path(dest).read_text() == "copy me"

    async def test_move_file(self, files_cap, work_dir):
        """Test moving a file."""
        source = os.path.join(work_dir, "move_source.txt")
        dest = os.path.join(work_dir, "move_dest.txt")

        Path(source).write_text("move me")

        result = await files_cap.execute(
            "move",
            {"source": source, "destination": dest},
            "test-m1",
        )

        assert result.status == TaskStatus.COMPLETED
        assert not Path(source).exists()
        assert Path(dest).read_text() == "move me"

    async def test_delete_file(self, files_cap, work_dir):
        """Test deleting a file."""
        test_path = os.path.join(work_dir, "delete_me.txt")
        Path(test_path).touch()

        result = await files_cap.execute(
            "delete",
            {"path": test_path},
            "test-d1",
        )

        assert result.status == TaskStatus.COMPLETED
        assert not Path(test_path).exists()

    async def test_mkdir(self, files_cap, work_dir):
        """Test creating a directory."""
        new_dir = os.path.join(work_dir, "new", "nested", "dir")

        result = await files_cap.execute(
            "mkdir",
            {"path": new_dir},
            "test-md1",
        )

        assert result.status == TaskStatus.COMPLETED
        assert Path(new_dir).is_dir()

    async def test_file_info(self, files_cap, work_dir):
        """Test getting file information."""
        test_path = os.path.join(work_dir, "info.txt")
        Path(test_path).write_text("info content")

        result = await files_cap.execute(
            "info",
            {"path": test_path},
            "test-i1",
        )

        assert result.status == TaskStatus.COMPLETED
        assert result.data["type"] == "file"
        assert result.data["size"] == 12
        assert "info.txt" in result.data["name"]
