"""Tests for the task executor."""

import pytest

from alfred.common.models import TaskStatus
from alfred.daemon.capabilities import FilesCapability, ShellCapability
from alfred.daemon.executor import TaskExecutor


@pytest.fixture
def executor(tmp_path):
    """Create a task executor with capabilities."""
    exec = TaskExecutor()
    exec.register_capability(ShellCapability(str(tmp_path)))
    exec.register_capability(FilesCapability(str(tmp_path)))
    return exec


class TestTaskExecutor:
    """Tests for TaskExecutor."""

    def test_register_capability(self, tmp_path):
        """Test registering capabilities."""
        exec = TaskExecutor()

        assert exec.get_capabilities() == []
        assert exec.get_actions() == []

        exec.register_capability(ShellCapability(str(tmp_path)))

        assert "shell" in exec.get_capabilities()
        assert "run" in exec.get_actions()
        assert "run_background" in exec.get_actions()

    def test_get_capabilities(self, executor):
        """Test getting registered capabilities."""
        caps = executor.get_capabilities()
        assert "shell" in caps
        assert "files" in caps

    def test_get_actions(self, executor):
        """Test getting available actions."""
        actions = executor.get_actions()
        assert "run" in actions
        assert "read" in actions
        assert "write" in actions

    async def test_execute_shell_action(self, executor):
        """Test executing a shell action."""
        result = await executor.execute(
            task_id="test-1",
            action="run",
            params={"command": "echo test"},
        )

        assert result.task_id == "test-1"
        assert result.status == TaskStatus.COMPLETED
        assert "test" in result.output

    async def test_execute_files_action(self, executor, tmp_path):
        """Test executing a files action."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello")

        result = await executor.execute(
            task_id="test-2",
            action="read",
            params={"path": str(test_file)},
        )

        assert result.status == TaskStatus.COMPLETED
        assert result.output == "hello"

    async def test_execute_unknown_action(self, executor):
        """Test executing an unknown action."""
        result = await executor.execute(
            task_id="test-3",
            action="unknown_action",
            params={},
        )

        assert result.status == TaskStatus.FAILED
        assert "unknown" in result.error.lower()
