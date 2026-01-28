"""Tests for the task router."""

from datetime import datetime

import pytest

from alfred.common.models import Capability, DaemonInfo
from alfred.prime.router import TaskRouter


@pytest.fixture
def router():
    """Create a task router."""
    return TaskRouter(secret_key="test-secret")


@pytest.fixture
def sample_daemon():
    """Create a sample daemon info."""
    return DaemonInfo(
        name="test-daemon",
        machine_type="server",
        capabilities=[Capability.SHELL, Capability.FILES],
        hostname="localhost",
        ip_address="127.0.0.1",
        port=8001,
        online=True,
        last_seen=datetime.utcnow(),
    )


class TestTaskRouter:
    """Tests for TaskRouter."""

    def test_register_daemon(self, router, sample_daemon):
        """Test registering a daemon."""
        router.register_daemon(sample_daemon)

        daemon = router.get_daemon("test-daemon")
        assert daemon is not None
        assert daemon.name == "test-daemon"

    def test_unregister_daemon(self, router, sample_daemon):
        """Test unregistering a daemon."""
        router.register_daemon(sample_daemon)
        router.unregister_daemon("test-daemon")

        assert router.get_daemon("test-daemon") is None

    def test_get_online_daemons(self, router, sample_daemon):
        """Test getting online daemons."""
        router.register_daemon(sample_daemon)

        online = router.get_online_daemons()
        assert len(online) == 1
        assert online[0].name == "test-daemon"

    def test_get_online_daemons_filters_offline(self, router, sample_daemon):
        """Test that offline daemons are filtered out."""
        sample_daemon.online = False
        router.register_daemon(sample_daemon)

        online = router.get_online_daemons()
        assert len(online) == 0

    def test_get_daemons_with_capability(self, router, sample_daemon):
        """Test getting daemons with a specific capability."""
        router.register_daemon(sample_daemon)

        shell_daemons = router.get_daemons_with_capability("shell")
        assert len(shell_daemons) == 1

        browser_daemons = router.get_daemons_with_capability("browser")
        assert len(browser_daemons) == 0

    def test_select_daemon(self, router, sample_daemon):
        """Test selecting a daemon for an action."""
        router.register_daemon(sample_daemon)

        daemon = router.select_daemon("shell.run")
        assert daemon is not None
        assert daemon.name == "test-daemon"

    def test_select_daemon_with_preferred(self, router, sample_daemon):
        """Test selecting a preferred daemon."""
        router.register_daemon(sample_daemon)

        # Create another daemon
        other = DaemonInfo(
            name="other-daemon",
            machine_type="workstation",
            capabilities=[Capability.SHELL],
            hostname="localhost",
            ip_address="127.0.0.1",
            port=8002,
            online=True,
            last_seen=datetime.utcnow(),
        )
        router.register_daemon(other)

        daemon = router.select_daemon("shell.run", preferred="other-daemon")
        assert daemon.name == "other-daemon"

    def test_select_daemon_no_capability(self, router, sample_daemon):
        """Test selecting when no daemon has the capability."""
        sample_daemon.capabilities = [Capability.FILES]
        router.register_daemon(sample_daemon)

        daemon = router.select_daemon("browser.open")
        assert daemon is None

    def test_update_heartbeat(self, router, sample_daemon):
        """Test updating daemon heartbeat."""
        router.register_daemon(sample_daemon)
        old_time = sample_daemon.last_seen

        result = router.update_daemon_heartbeat("test-daemon")
        assert result is True

        daemon = router.get_daemon("test-daemon")
        assert daemon.last_seen >= old_time

    def test_update_heartbeat_unknown_daemon(self, router):
        """Test updating heartbeat for unknown daemon."""
        result = router.update_daemon_heartbeat("unknown")
        assert result is False

    def test_mark_daemon_offline(self, router, sample_daemon):
        """Test marking a daemon as offline."""
        router.register_daemon(sample_daemon)
        router.mark_daemon_offline("test-daemon")

        daemon = router.get_daemon("test-daemon")
        assert daemon.online is False
