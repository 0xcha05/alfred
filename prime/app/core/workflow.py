"""Workflow engine for multi-step task execution."""

import logging
from typing import Optional, List, Any, Dict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import uuid

logger = logging.getLogger(__name__)


class StepType(str, Enum):
    """Types of workflow steps."""
    SHELL = "shell"
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    BROWSER = "browser"
    WAIT = "wait"
    CONFIRM = "confirm"
    CONDITION = "condition"


class StepStatus(str, Enum):
    """Status of a workflow step."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING = "waiting"  # Waiting for confirmation


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    id: str
    type: StepType
    name: str
    parameters: Dict[str, Any]
    target_machine: Optional[str] = None
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Rollback action if this step fails
    rollback: Optional[Dict[str, Any]] = None
    
    # Condition for execution (e.g., "previous.exit_code == 0")
    condition: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "parameters": self.parameters,
            "target_machine": self.target_machine,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class Workflow:
    """A multi-step workflow."""
    id: str
    name: str
    description: Optional[str] = None
    steps: List[WorkflowStep] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    context: Dict[str, Any] = field(default_factory=dict)  # Shared context between steps
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_step: int = 0
    
    def add_step(self, step: WorkflowStep):
        """Add a step to the workflow."""
        self.steps.append(step)
    
    def get_current_step(self) -> Optional[WorkflowStep]:
        """Get the current step to execute."""
        if self.current_step < len(self.steps):
            return self.steps[self.current_step]
        return None
    
    def advance(self):
        """Advance to the next step."""
        self.current_step += 1
    
    def is_complete(self) -> bool:
        """Check if all steps are complete."""
        return self.current_step >= len(self.steps)
    
    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "current_step": self.current_step,
            "context": self.context,
        }


class WorkflowEngine:
    """Engine for executing multi-step workflows."""
    
    def __init__(self):
        self.workflows: Dict[str, Workflow] = {}
        self.templates: Dict[str, Workflow] = {}  # Saved workflow templates
    
    def create_workflow(self, name: str, description: str = "") -> Workflow:
        """Create a new workflow."""
        workflow = Workflow(
            id=str(uuid.uuid4())[:8],
            name=name,
            description=description,
        )
        self.workflows[workflow.id] = workflow
        return workflow
    
    def create_from_template(self, template_name: str, variables: Dict[str, Any] = None) -> Optional[Workflow]:
        """Create a workflow from a saved template."""
        if template_name not in self.templates:
            return None
        
        template = self.templates[template_name]
        workflow = Workflow(
            id=str(uuid.uuid4())[:8],
            name=f"{template.name} ({datetime.utcnow().strftime('%H:%M')})",
            description=template.description,
            context=variables or {},
        )
        
        # Copy steps with variable substitution
        for step in template.steps:
            new_step = WorkflowStep(
                id=str(uuid.uuid4())[:8],
                type=step.type,
                name=step.name,
                parameters=self._substitute_variables(step.parameters, variables or {}),
                target_machine=step.target_machine,
                rollback=step.rollback,
                condition=step.condition,
            )
            workflow.add_step(new_step)
        
        self.workflows[workflow.id] = workflow
        return workflow
    
    def _substitute_variables(self, params: Dict, variables: Dict) -> Dict:
        """Substitute variables in parameters."""
        result = {}
        for key, value in params.items():
            if isinstance(value, str):
                for var_name, var_value in variables.items():
                    value = value.replace(f"${{{var_name}}}", str(var_value))
                    value = value.replace(f"${var_name}", str(var_value))
            elif isinstance(value, dict):
                value = self._substitute_variables(value, variables)
            result[key] = value
        return result
    
    async def execute_workflow(self, workflow_id: str) -> Workflow:
        """Execute a workflow step by step."""
        from app.core.orchestrator import orchestrator
        from app.core.router import router
        
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            raise ValueError(f"Workflow not found: {workflow_id}")
        
        workflow.status = StepStatus.RUNNING
        workflow.started_at = datetime.utcnow()
        
        try:
            while not workflow.is_complete():
                step = workflow.get_current_step()
                if not step:
                    break
                
                # Check condition
                if step.condition and not self._evaluate_condition(step.condition, workflow.context):
                    step.status = StepStatus.SKIPPED
                    workflow.advance()
                    continue
                
                # Handle confirmation steps
                if step.type == StepType.CONFIRM:
                    step.status = StepStatus.WAITING
                    workflow.status = StepStatus.WAITING
                    return workflow  # Pause execution, wait for confirmation
                
                # Execute step
                step.status = StepStatus.RUNNING
                step.started_at = datetime.utcnow()
                
                try:
                    result = await self._execute_step(step, workflow.context)
                    step.result = result
                    step.status = StepStatus.COMPLETED
                    
                    # Add result to context
                    workflow.context[f"step_{step.id}"] = result
                    workflow.context["previous"] = result
                    
                except Exception as e:
                    step.error = str(e)
                    step.status = StepStatus.FAILED
                    
                    # Execute rollback if defined
                    if step.rollback:
                        await self._execute_rollback(step, workflow)
                    
                    workflow.status = StepStatus.FAILED
                    workflow.completed_at = datetime.utcnow()
                    return workflow
                
                step.completed_at = datetime.utcnow()
                workflow.advance()
            
            workflow.status = StepStatus.COMPLETED
            
        except Exception as e:
            logger.error(f"Workflow execution failed: {e}")
            workflow.status = StepStatus.FAILED
        
        workflow.completed_at = datetime.utcnow()
        return workflow
    
    async def _execute_step(self, step: WorkflowStep, context: Dict) -> Any:
        """Execute a single workflow step."""
        from app.core.orchestrator import orchestrator
        from app.core.router import router
        from app.core.intent import ParsedIntent, ActionType
        
        if step.type == StepType.SHELL:
            # Create intent for shell command
            intent = ParsedIntent(
                action=ActionType.SHELL,
                target_machine=step.target_machine,
                parameters=step.parameters,
                original_message=step.name,
            )
            
            # Get target daemon
            daemon_id = step.target_machine or router.get_target_daemon(intent)
            if not daemon_id:
                raise Exception("No daemon available")
            
            # Execute
            task = orchestrator.create_task(daemon_id, "shell", step.parameters)
            task = await orchestrator.execute_task(task)
            
            if task.error:
                raise Exception(task.error)
            
            return task.result
        
        elif step.type == StepType.WAIT:
            import asyncio
            seconds = step.parameters.get("seconds", 1)
            await asyncio.sleep(seconds)
            return {"waited": seconds}
        
        elif step.type == StepType.CONDITION:
            # Condition steps just evaluate and return true/false
            condition = step.parameters.get("expression", "true")
            return {"result": self._evaluate_condition(condition, context)}
        
        else:
            raise Exception(f"Unknown step type: {step.type}")
    
    async def _execute_rollback(self, step: WorkflowStep, workflow: Workflow):
        """Execute rollback for a failed step."""
        logger.info(f"Executing rollback for step {step.id}")
        
        rollback_step = WorkflowStep(
            id=f"rollback_{step.id}",
            type=StepType(step.rollback.get("type", "shell")),
            name=f"Rollback: {step.name}",
            parameters=step.rollback.get("parameters", {}),
            target_machine=step.target_machine,
        )
        
        try:
            await self._execute_step(rollback_step, workflow.context)
            logger.info(f"Rollback completed for step {step.id}")
        except Exception as e:
            logger.error(f"Rollback failed for step {step.id}: {e}")
    
    def _evaluate_condition(self, condition: str, context: Dict) -> bool:
        """Evaluate a condition expression."""
        try:
            # Simple evaluation - in production, use a safe expression parser
            # For now, just handle basic conditions
            
            if condition.lower() == "true":
                return True
            if condition.lower() == "false":
                return False
            
            # Handle "previous.success" pattern
            if "previous" in condition and "previous" in context:
                prev = context["previous"]
                if isinstance(prev, dict):
                    if "success" in condition:
                        return prev.get("success", False)
                    if "exit_code" in condition:
                        return prev.get("exit_code", 1) == 0
            
            return True
            
        except Exception as e:
            logger.warning(f"Condition evaluation failed: {e}")
            return True
    
    def confirm_step(self, workflow_id: str) -> bool:
        """Confirm a waiting step and resume execution."""
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            return False
        
        step = workflow.get_current_step()
        if step and step.status == StepStatus.WAITING:
            step.status = StepStatus.COMPLETED
            step.completed_at = datetime.utcnow()
            workflow.advance()
            return True
        
        return False
    
    def cancel_workflow(self, workflow_id: str) -> bool:
        """Cancel a workflow."""
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            return False
        
        workflow.status = StepStatus.FAILED
        workflow.completed_at = datetime.utcnow()
        
        # Mark remaining steps as skipped
        for step in workflow.steps[workflow.current_step:]:
            step.status = StepStatus.SKIPPED
        
        return True
    
    def save_as_template(self, workflow_id: str, template_name: str):
        """Save a workflow as a reusable template."""
        workflow = self.workflows.get(workflow_id)
        if not workflow:
            return False
        
        template = Workflow(
            id=template_name,
            name=workflow.name,
            description=workflow.description,
        )
        
        for step in workflow.steps:
            template.add_step(WorkflowStep(
                id=step.id,
                type=step.type,
                name=step.name,
                parameters=step.parameters,
                target_machine=step.target_machine,
                rollback=step.rollback,
                condition=step.condition,
            ))
        
        self.templates[template_name] = template
        return True


# Global workflow engine instance
workflow_engine = WorkflowEngine()
