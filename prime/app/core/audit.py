"""Audit logging for all Ultron actions."""

import logging
from datetime import datetime
from typing import Optional, List, Any, Dict
from dataclasses import dataclass, field
from enum import Enum
import json
import os

logger = logging.getLogger(__name__)


class AuditEventType(str, Enum):
    """Types of auditable events."""
    COMMAND = "command"
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    DAEMON_REGISTER = "daemon_register"
    DAEMON_DISCONNECT = "daemon_disconnect"
    USER_MESSAGE = "user_message"
    CONFIRMATION = "confirmation"
    ERROR = "error"
    WORKFLOW = "workflow"


@dataclass
class AuditEvent:
    """An auditable event."""
    id: str
    timestamp: datetime
    event_type: AuditEventType
    user_id: Optional[str]
    machine_id: Optional[str]
    action: str
    parameters: Dict[str, Any]
    result: Optional[Dict[str, Any]] = None
    success: bool = True
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "event_type": self.event_type.value,
            "user_id": self.user_id,
            "machine_id": self.machine_id,
            "action": self.action,
            "parameters": self._sanitize(self.parameters),
            "result": self._sanitize(self.result) if self.result else None,
            "success": self.success,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }
    
    def _sanitize(self, data: Any) -> Any:
        """Remove sensitive information from data."""
        if isinstance(data, dict):
            sanitized = {}
            for key, value in data.items():
                # Redact sensitive keys
                if any(s in key.lower() for s in ["password", "secret", "token", "key", "api_key"]):
                    sanitized[key] = "[REDACTED]"
                else:
                    sanitized[key] = self._sanitize(value)
            return sanitized
        elif isinstance(data, list):
            return [self._sanitize(item) for item in data]
        elif isinstance(data, str) and len(data) > 1000:
            return data[:1000] + "... (truncated)"
        return data
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())


class AuditLogger:
    """Service for audit logging."""
    
    def __init__(self, log_dir: str = None, retention_days: int = 30):
        self.log_dir = log_dir or os.path.join(os.path.dirname(__file__), "..", "..", "logs", "audit")
        self.retention_days = retention_days
        self.events: List[AuditEvent] = []
        self.event_counter = 0
        
        # Create log directory
        os.makedirs(self.log_dir, exist_ok=True)
    
    def log(
        self,
        event_type: AuditEventType,
        action: str,
        parameters: Dict[str, Any],
        user_id: Optional[str] = None,
        machine_id: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        success: bool = True,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
        metadata: Dict[str, Any] = None,
    ) -> AuditEvent:
        """Log an audit event."""
        self.event_counter += 1
        
        event = AuditEvent(
            id=f"audit-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{self.event_counter:06d}",
            timestamp=datetime.utcnow(),
            event_type=event_type,
            user_id=user_id,
            machine_id=machine_id,
            action=action,
            parameters=parameters,
            result=result,
            success=success,
            error=error,
            duration_ms=duration_ms,
            metadata=metadata or {},
        )
        
        # Keep in memory (last 1000 events)
        self.events.append(event)
        if len(self.events) > 1000:
            self.events = self.events[-1000:]
        
        # Write to file
        self._write_to_file(event)
        
        # Log to standard logger too
        log_msg = f"[AUDIT] {event_type.value}: {action}"
        if success:
            logger.info(log_msg)
        else:
            logger.warning(f"{log_msg} - FAILED: {error}")
        
        return event
    
    def _write_to_file(self, event: AuditEvent):
        """Write event to daily log file."""
        try:
            date_str = event.timestamp.strftime("%Y-%m-%d")
            log_file = os.path.join(self.log_dir, f"audit-{date_str}.jsonl")
            
            with open(log_file, "a") as f:
                f.write(event.to_json() + "\n")
        except Exception as e:
            logger.error(f"Failed to write audit log: {e}")
    
    def query(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        event_type: Optional[AuditEventType] = None,
        user_id: Optional[str] = None,
        machine_id: Optional[str] = None,
        success_only: bool = False,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """Query audit events."""
        results = []
        
        for event in reversed(self.events):
            if start_date and event.timestamp < start_date:
                continue
            if end_date and event.timestamp > end_date:
                continue
            if event_type and event.event_type != event_type:
                continue
            if user_id and event.user_id != user_id:
                continue
            if machine_id and event.machine_id != machine_id:
                continue
            if success_only and not event.success:
                continue
            
            results.append(event)
            
            if len(results) >= limit:
                break
        
        return results
    
    def get_recent(self, limit: int = 10) -> List[AuditEvent]:
        """Get most recent events."""
        return list(reversed(self.events[-limit:]))
    
    def get_by_date(self, date: datetime) -> List[AuditEvent]:
        """Get all events for a specific date."""
        date_str = date.strftime("%Y-%m-%d")
        log_file = os.path.join(self.log_dir, f"audit-{date_str}.jsonl")
        
        if not os.path.exists(log_file):
            return []
        
        events = []
        try:
            with open(log_file, "r") as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        events.append(AuditEvent(
                            id=data["id"],
                            timestamp=datetime.fromisoformat(data["timestamp"]),
                            event_type=AuditEventType(data["event_type"]),
                            user_id=data.get("user_id"),
                            machine_id=data.get("machine_id"),
                            action=data["action"],
                            parameters=data.get("parameters", {}),
                            result=data.get("result"),
                            success=data.get("success", True),
                            error=data.get("error"),
                            duration_ms=data.get("duration_ms"),
                        ))
        except Exception as e:
            logger.error(f"Failed to read audit log: {e}")
        
        return events
    
    def summarize(self, hours: int = 24) -> Dict[str, Any]:
        """Generate a summary of recent activity."""
        from datetime import timedelta
        
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        recent = [e for e in self.events if e.timestamp >= cutoff]
        
        # Count by type
        by_type = {}
        for event in recent:
            by_type[event.event_type.value] = by_type.get(event.event_type.value, 0) + 1
        
        # Count success/failure
        success_count = sum(1 for e in recent if e.success)
        failure_count = len(recent) - success_count
        
        # Most active machines
        machines = {}
        for event in recent:
            if event.machine_id:
                machines[event.machine_id] = machines.get(event.machine_id, 0) + 1
        
        return {
            "period_hours": hours,
            "total_events": len(recent),
            "by_type": by_type,
            "success_count": success_count,
            "failure_count": failure_count,
            "machines": machines,
        }
    
    def cleanup_old_logs(self):
        """Remove logs older than retention period."""
        from datetime import timedelta
        
        cutoff = datetime.utcnow() - timedelta(days=self.retention_days)
        
        for filename in os.listdir(self.log_dir):
            if filename.startswith("audit-") and filename.endswith(".jsonl"):
                try:
                    date_str = filename.replace("audit-", "").replace(".jsonl", "")
                    file_date = datetime.strptime(date_str, "%Y-%m-%d")
                    
                    if file_date < cutoff:
                        os.remove(os.path.join(self.log_dir, filename))
                        logger.info(f"Cleaned up old audit log: {filename}")
                except Exception as e:
                    logger.warning(f"Failed to process {filename}: {e}")


# Global audit logger instance
audit_logger = AuditLogger()
