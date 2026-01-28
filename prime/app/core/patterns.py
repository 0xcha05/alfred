"""Learned patterns for personalized shortcuts and "the usual" commands."""

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from datetime import datetime
import json
import re

logger = logging.getLogger(__name__)


@dataclass
class LearnedPattern:
    """A learned pattern that maps a trigger phrase to an action."""
    id: str
    trigger: str  # Trigger phrase (e.g., "the usual", "order food")
    trigger_regex: str  # Regex pattern for matching
    action: str  # Action type (shell, workflow, etc.)
    parameters: Dict[str, Any]  # Action parameters
    target_machine: Optional[str] = None
    description: Optional[str] = None
    usage_count: int = 0
    last_used: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    context: Dict[str, Any] = field(default_factory=dict)  # Additional context
    
    def matches(self, text: str) -> bool:
        """Check if the text matches this pattern."""
        return bool(re.search(self.trigger_regex, text.lower()))
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "action": self.action,
            "parameters": self.parameters,
            "target_machine": self.target_machine,
            "description": self.description,
            "usage_count": self.usage_count,
            "last_used": self.last_used.isoformat() if self.last_used else None,
        }


class PatternLearner:
    """Service for learning and applying user patterns."""
    
    def __init__(self):
        self.patterns: Dict[str, LearnedPattern] = {}
        self.corrections: List[Dict] = []  # Track corrections for learning
        self.command_history: List[Dict] = []  # Recent command history
        
        # Pre-defined common patterns
        self._load_default_patterns()
    
    def _load_default_patterns(self):
        """Load default patterns that can be customized."""
        defaults = [
            {
                "id": "the-usual-food",
                "trigger": "the usual",
                "trigger_regex": r"\b(the usual|my usual order)\b",
                "action": "custom",
                "parameters": {},
                "description": "Your usual food order (configure this)",
            },
            {
                "id": "deploy-staging",
                "trigger": "deploy to staging",
                "trigger_regex": r"\b(deploy|push)\s+(to\s+)?staging\b",
                "action": "shell",
                "parameters": {"command": "deploy.sh staging"},
                "description": "Deploy to staging environment",
            },
            {
                "id": "run-tests",
                "trigger": "run tests",
                "trigger_regex": r"\b(run|execute)\s+(the\s+)?tests?\b",
                "action": "shell",
                "parameters": {"command": "npm test"},
                "description": "Run project tests",
            },
            {
                "id": "check-status",
                "trigger": "check status",
                "trigger_regex": r"\b(check|show|what'?s)\s+(the\s+)?(status|running)\b",
                "action": "status",
                "parameters": {},
                "description": "Check system status",
            },
        ]
        
        for p in defaults:
            pattern = LearnedPattern(**p)
            self.patterns[pattern.id] = pattern
    
    def match(self, text: str) -> Optional[LearnedPattern]:
        """Find a matching pattern for the given text."""
        text_lower = text.lower().strip()
        
        # Check all patterns
        matches = []
        for pattern in self.patterns.values():
            if pattern.matches(text_lower):
                matches.append(pattern)
        
        if not matches:
            return None
        
        # Return the most specific match (longest trigger)
        # or most used pattern if tied
        matches.sort(key=lambda p: (-len(p.trigger), -p.usage_count))
        return matches[0]
    
    def use_pattern(self, pattern_id: str):
        """Record that a pattern was used."""
        if pattern_id in self.patterns:
            pattern = self.patterns[pattern_id]
            pattern.usage_count += 1
            pattern.last_used = datetime.utcnow()
    
    def learn_pattern(
        self,
        trigger: str,
        action: str,
        parameters: Dict[str, Any],
        target_machine: Optional[str] = None,
        description: Optional[str] = None,
    ) -> LearnedPattern:
        """Learn a new pattern from user interaction."""
        import uuid
        
        # Create regex from trigger
        trigger_regex = self._create_regex(trigger)
        
        pattern = LearnedPattern(
            id=str(uuid.uuid4())[:8],
            trigger=trigger,
            trigger_regex=trigger_regex,
            action=action,
            parameters=parameters,
            target_machine=target_machine,
            description=description or f"Learned pattern: {trigger}",
        )
        
        self.patterns[pattern.id] = pattern
        logger.info(f"Learned new pattern: '{trigger}' -> {action}")
        
        return pattern
    
    def _create_regex(self, trigger: str) -> str:
        """Create a regex pattern from a trigger phrase."""
        # Escape special regex characters
        escaped = re.escape(trigger.lower())
        
        # Make it more flexible
        # Allow optional words like "the", "my", "please"
        flexible = escaped.replace(r"\ ", r"\s+")
        
        return rf"\b{flexible}\b"
    
    def learn_from_correction(self, original: str, corrected: str, context: Dict):
        """Learn from a user correction."""
        self.corrections.append({
            "original": original,
            "corrected": corrected,
            "context": context,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        # If we see the same correction multiple times, learn it
        similar_corrections = [
            c for c in self.corrections
            if c["original"].lower() == original.lower()
        ]
        
        if len(similar_corrections) >= 2:
            # User has corrected this multiple times, learn it
            logger.info(f"Learning from repeated correction: '{original}' -> '{corrected}'")
            self.learn_pattern(
                trigger=original,
                action="shell",  # Assume shell for now
                parameters={"command": corrected},
                description=f"Learned: '{original}' means '{corrected}'",
            )
    
    def record_command(self, message: str, action: str, parameters: Dict, success: bool):
        """Record a command execution for pattern mining."""
        self.command_history.append({
            "message": message,
            "action": action,
            "parameters": parameters,
            "success": success,
            "timestamp": datetime.utcnow().isoformat(),
        })
        
        # Keep only last 100 commands
        if len(self.command_history) > 100:
            self.command_history = self.command_history[-100:]
    
    def suggest_patterns(self) -> List[Dict]:
        """Suggest new patterns based on command history."""
        # Find frequently used commands
        from collections import Counter
        
        command_counts = Counter()
        for cmd in self.command_history:
            if cmd.get("success"):
                key = json.dumps(cmd.get("parameters", {}), sort_keys=True)
                command_counts[key] += 1
        
        suggestions = []
        for params_json, count in command_counts.most_common(5):
            if count >= 3:  # Used at least 3 times
                params = json.loads(params_json)
                suggestions.append({
                    "parameters": params,
                    "count": count,
                    "suggestion": f"Create shortcut for: {params.get('command', params)}",
                })
        
        return suggestions
    
    def update_pattern(self, pattern_id: str, updates: Dict) -> bool:
        """Update an existing pattern."""
        if pattern_id not in self.patterns:
            return False
        
        pattern = self.patterns[pattern_id]
        
        if "trigger" in updates:
            pattern.trigger = updates["trigger"]
            pattern.trigger_regex = self._create_regex(updates["trigger"])
        if "parameters" in updates:
            pattern.parameters = updates["parameters"]
        if "target_machine" in updates:
            pattern.target_machine = updates["target_machine"]
        if "description" in updates:
            pattern.description = updates["description"]
        
        return True
    
    def delete_pattern(self, pattern_id: str) -> bool:
        """Delete a pattern."""
        if pattern_id in self.patterns:
            del self.patterns[pattern_id]
            return True
        return False
    
    def list_patterns(self) -> List[Dict]:
        """List all patterns."""
        return [p.to_dict() for p in sorted(
            self.patterns.values(),
            key=lambda p: (-p.usage_count, p.trigger)
        )]
    
    def export_patterns(self) -> str:
        """Export patterns to JSON."""
        return json.dumps([p.to_dict() for p in self.patterns.values()], indent=2)
    
    def import_patterns(self, json_str: str) -> int:
        """Import patterns from JSON."""
        data = json.loads(json_str)
        count = 0
        
        for p in data:
            pattern = LearnedPattern(
                id=p.get("id", str(uuid.uuid4())[:8]),
                trigger=p["trigger"],
                trigger_regex=self._create_regex(p["trigger"]),
                action=p["action"],
                parameters=p.get("parameters", {}),
                target_machine=p.get("target_machine"),
                description=p.get("description"),
            )
            self.patterns[pattern.id] = pattern
            count += 1
        
        return count


# Global pattern learner instance
pattern_learner = PatternLearner()
