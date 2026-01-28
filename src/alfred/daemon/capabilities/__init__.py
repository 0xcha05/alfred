"""Daemon capabilities - pluggable functionality modules."""

from alfred.daemon.capabilities.base import BaseCapability
from alfred.daemon.capabilities.shell import ShellCapability
from alfred.daemon.capabilities.files import FilesCapability

__all__ = ["BaseCapability", "ShellCapability", "FilesCapability"]
