"""Pytest configuration and fixtures."""

import os
import sys

import pytest

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture(scope="session")
def anyio_backend():
    """Configure async backend for pytest."""
    return "asyncio"


# Configure pytest-asyncio
def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line("markers", "asyncio: mark test as async")
