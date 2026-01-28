"""Memory Store - high-level interface for persistent state."""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from alfred.common import get_logger
from alfred.common.models import DaemonInfo, TaskResult, TaskStatus
from alfred.memory.models import (
    Conversation,
    ConversationMessage,
    Machine,
    Preference,
    Project,
    Task,
    User,
)

logger = get_logger(__name__)


class MemoryStore:
    """High-level interface for the memory store."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # Machine management

    async def register_machine(self, info: DaemonInfo) -> Machine:
        """Register or update a daemon/machine."""
        stmt = select(Machine).where(Machine.name == info.name)
        result = await self.session.execute(stmt)
        machine = result.scalar_one_or_none()

        if machine:
            machine.hostname = info.hostname
            machine.ip_address = info.ip_address
            machine.port = info.port
            machine.capabilities = [c.value for c in info.capabilities]
            machine.is_online = True
            machine.last_seen = datetime.utcnow()
        else:
            machine = Machine(
                name=info.name,
                machine_type=info.machine_type,
                hostname=info.hostname,
                ip_address=info.ip_address,
                port=info.port,
                capabilities=[c.value for c in info.capabilities],
                is_online=True,
                last_seen=datetime.utcnow(),
            )
            self.session.add(machine)

        await self.session.flush()
        logger.info("machine_registered", name=info.name, hostname=info.hostname)
        return machine

    async def get_machine(self, name: str) -> Machine | None:
        """Get a machine by name."""
        stmt = select(Machine).where(Machine.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_online_machines(self) -> list[Machine]:
        """Get all online machines."""
        cutoff = datetime.utcnow() - timedelta(minutes=5)
        stmt = select(Machine).where(
            Machine.is_online == True,  # noqa: E712
            Machine.last_seen >= cutoff,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_machine_heartbeat(self, name: str) -> None:
        """Update a machine's last seen timestamp."""
        stmt = (
            update(Machine)
            .where(Machine.name == name)
            .values(last_seen=datetime.utcnow(), is_online=True)
        )
        await self.session.execute(stmt)

    async def mark_machine_offline(self, name: str) -> None:
        """Mark a machine as offline."""
        stmt = update(Machine).where(Machine.name == name).values(is_online=False)
        await self.session.execute(stmt)

    # User management

    async def get_or_create_user(
        self, external_id: str, channel: str, display_name: str | None = None
    ) -> User:
        """Get or create a user by external ID."""
        stmt = select(User).where(User.external_id == external_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                external_id=external_id,
                channel=channel,
                display_name=display_name,
            )
            self.session.add(user)
            await self.session.flush()
            logger.info("user_created", external_id=external_id, channel=channel)

        return user

    # Conversation management

    async def get_or_create_conversation(
        self, user: User, channel: str
    ) -> Conversation:
        """Get the active conversation for a user or create one."""
        stmt = select(Conversation).where(
            Conversation.user_id == user.id,
            Conversation.channel == channel,
            Conversation.is_active == True,  # noqa: E712
        )
        result = await self.session.execute(stmt)
        conversation = result.scalar_one_or_none()

        if not conversation:
            conversation = Conversation(
                user_id=user.id,
                channel=channel,
                is_active=True,
            )
            self.session.add(conversation)
            await self.session.flush()

        return conversation

    async def add_message(
        self, conversation: Conversation, role: str, content: str
    ) -> ConversationMessage:
        """Add a message to a conversation."""
        message = ConversationMessage(
            conversation_id=conversation.id,
            role=role,
            content=content,
        )
        self.session.add(message)
        await self.session.flush()
        return message

    async def get_conversation_history(
        self, conversation: Conversation, limit: int = 20
    ) -> list[ConversationMessage]:
        """Get recent messages from a conversation."""
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation.id)
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        messages = list(result.scalars().all())
        messages.reverse()  # Return in chronological order
        return messages

    # Task management

    async def create_task(
        self,
        task_id: str,
        action: str,
        params: dict[str, Any],
        machine_name: str | None = None,
    ) -> Task:
        """Create a new task."""
        machine_id = None
        if machine_name:
            machine = await self.get_machine(machine_name)
            if machine:
                machine_id = machine.id

        task = Task(
            task_id=task_id,
            machine_id=machine_id,
            action=action,
            params=params,
            status=TaskStatus.PENDING.value,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def update_task(self, task_id: str, result: TaskResult) -> None:
        """Update a task with its result."""
        stmt = (
            update(Task)
            .where(Task.task_id == task_id)
            .values(
                status=result.status.value,
                output=result.output,
                error=result.error,
                exit_code=result.exit_code,
                started_at=result.started_at,
                completed_at=result.completed_at,
            )
        )
        await self.session.execute(stmt)

    async def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        stmt = select(Task).where(Task.task_id == task_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # Project management

    async def get_or_create_project(
        self, name: str, path: str | None = None, machine_name: str | None = None
    ) -> Project:
        """Get or create a project."""
        stmt = select(Project).where(Project.name == name)
        result = await self.session.execute(stmt)
        project = result.scalar_one_or_none()

        if not project:
            project = Project(
                name=name,
                path=path,
                machine_name=machine_name,
            )
            self.session.add(project)
            await self.session.flush()

        return project

    async def get_project(self, name: str) -> Project | None:
        """Get a project by name."""
        stmt = select(Project).where(Project.name == name)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # Preference management

    async def set_preference(
        self, key: str, value: Any, description: str | None = None
    ) -> Preference:
        """Set a preference value."""
        stmt = select(Preference).where(Preference.key == key)
        result = await self.session.execute(stmt)
        pref = result.scalar_one_or_none()

        if pref:
            pref.value = value
            if description:
                pref.description = description
        else:
            pref = Preference(key=key, value=value, description=description)
            self.session.add(pref)

        await self.session.flush()
        return pref

    async def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a preference value."""
        stmt = select(Preference).where(Preference.key == key)
        result = await self.session.execute(stmt)
        pref = result.scalar_one_or_none()
        return pref.value if pref else default

    async def get_all_preferences(self) -> dict[str, Any]:
        """Get all preferences as a dictionary."""
        stmt = select(Preference)
        result = await self.session.execute(stmt)
        prefs = result.scalars().all()
        return {p.key: p.value for p in prefs}
