"""Database models for the memory store."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from alfred.memory.database import Base


class Machine(Base):
    """A registered machine/daemon."""

    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    machine_type: Mapped[str] = mapped_column(String(50))
    hostname: Mapped[str] = mapped_column(String(255))
    ip_address: Mapped[str] = mapped_column(String(45))
    port: Mapped[int] = mapped_column()
    capabilities: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_online: Mapped[bool] = mapped_column(default=False)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )

    tasks: Mapped[list["Task"]] = relationship(back_populates="machine")


class User(Base):
    """A user who interacts with Alfred."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    channel: Mapped[str] = mapped_column(String(50))  # telegram, whatsapp, cli
    display_name: Mapped[str | None] = mapped_column(String(255))
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversations: Mapped[list["Conversation"]] = relationship(back_populates="user")


class Conversation(Base):
    """A conversation thread with a user."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    channel: Mapped[str] = mapped_column(String(50))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation", order_by="ConversationMessage.created_at"
    )


class ConversationMessage(Base):
    """A message in a conversation."""

    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"))
    role: Mapped[str] = mapped_column(String(20))  # user, assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Task(Base):
    """A task executed by a daemon."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    machine_id: Mapped[int | None] = mapped_column(ForeignKey("machines.id"))
    action: Mapped[str] = mapped_column(String(50))
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    output: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    exit_code: Mapped[int | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    machine: Mapped["Machine | None"] = relationship(back_populates="tasks")


class Project(Base):
    """A project tracked by Alfred."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    path: Mapped[str | None] = mapped_column(String(500))
    machine_name: Mapped[str | None] = mapped_column(String(100))
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Preference(Base):
    """User preferences and learned patterns."""

    __tablename__ = "preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[Any] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
