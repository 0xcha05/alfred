"""Cross-machine file transfer service."""

import asyncio
import logging
from typing import Optional, AsyncIterator
from dataclasses import dataclass
from datetime import datetime

from app.grpc_client import daemon_client
from app.core.router import router

logger = logging.getLogger(__name__)


@dataclass
class TransferProgress:
    """Progress update for file transfer."""
    source_machine: str
    dest_machine: str
    filename: str
    bytes_transferred: int
    total_bytes: int
    status: str  # "starting", "transferring", "completed", "failed"
    error: Optional[str] = None
    
    @property
    def percent(self) -> float:
        if self.total_bytes == 0:
            return 0.0
        return (self.bytes_transferred / self.total_bytes) * 100


class FileTransferService:
    """Service for transferring files between machines via Prime relay."""
    
    def __init__(self):
        self.active_transfers: dict = {}
    
    async def transfer_file(
        self,
        source_machine: str,
        source_path: str,
        dest_machine: str,
        dest_path: str,
        chunk_size: int = 1024 * 1024,  # 1MB chunks
    ) -> AsyncIterator[TransferProgress]:
        """
        Transfer a file from source machine to destination machine.
        
        Uses Prime as a relay - reads from source, writes to destination.
        """
        transfer_id = f"{source_machine}-{dest_machine}-{datetime.utcnow().timestamp()}"
        
        try:
            # Initial progress
            yield TransferProgress(
                source_machine=source_machine,
                dest_machine=dest_machine,
                filename=source_path,
                bytes_transferred=0,
                total_bytes=0,
                status="starting",
            )
            
            # Read file from source
            logger.info(f"Reading {source_path} from {source_machine}")
            content = await daemon_client.read_file(source_machine, source_path)
            
            if isinstance(content, bytes):
                total_size = len(content)
            else:
                content = str(content).encode('utf-8')
                total_size = len(content)
            
            yield TransferProgress(
                source_machine=source_machine,
                dest_machine=dest_machine,
                filename=source_path,
                bytes_transferred=0,
                total_bytes=total_size,
                status="transferring",
            )
            
            # Write to destination
            logger.info(f"Writing {dest_path} to {dest_machine}")
            success = await daemon_client.write_file(dest_machine, dest_path, content)
            
            if success:
                yield TransferProgress(
                    source_machine=source_machine,
                    dest_machine=dest_machine,
                    filename=source_path,
                    bytes_transferred=total_size,
                    total_bytes=total_size,
                    status="completed",
                )
            else:
                yield TransferProgress(
                    source_machine=source_machine,
                    dest_machine=dest_machine,
                    filename=source_path,
                    bytes_transferred=0,
                    total_bytes=total_size,
                    status="failed",
                    error="Write failed",
                )
                
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            yield TransferProgress(
                source_machine=source_machine,
                dest_machine=dest_machine,
                filename=source_path,
                bytes_transferred=0,
                total_bytes=0,
                status="failed",
                error=str(e),
            )
    
    async def transfer_files(
        self,
        source_machine: str,
        source_paths: list[str],
        dest_machine: str,
        dest_dir: str,
    ) -> AsyncIterator[TransferProgress]:
        """Transfer multiple files to a destination directory."""
        import os
        
        for path in source_paths:
            filename = os.path.basename(path)
            dest_path = os.path.join(dest_dir, filename)
            
            async for progress in self.transfer_file(
                source_machine=source_machine,
                source_path=path,
                dest_machine=dest_machine,
                dest_path=dest_path,
            ):
                yield progress
    
    async def sync_directory(
        self,
        source_machine: str,
        source_dir: str,
        dest_machine: str,
        dest_dir: str,
    ) -> AsyncIterator[TransferProgress]:
        """Sync a directory from source to destination."""
        # List files on source
        logger.info(f"Listing {source_dir} on {source_machine}")
        files = await daemon_client.list_files(source_machine, source_dir, recursive=True)
        
        if not files:
            yield TransferProgress(
                source_machine=source_machine,
                dest_machine=dest_machine,
                filename=source_dir,
                bytes_transferred=0,
                total_bytes=0,
                status="completed",
            )
            return
        
        # Filter to only files (not directories)
        file_paths = [
            f.get("path") for f in files
            if not f.get("is_directory") and f.get("path")
        ]
        
        # Transfer each file
        for file_path in file_paths:
            # Calculate relative path
            import os
            rel_path = os.path.relpath(file_path, source_dir)
            dest_path = os.path.join(dest_dir, rel_path)
            
            async for progress in self.transfer_file(
                source_machine=source_machine,
                source_path=file_path,
                dest_machine=dest_machine,
                dest_path=dest_path,
            ):
                yield progress


# Global service instance
file_transfer_service = FileTransferService()
