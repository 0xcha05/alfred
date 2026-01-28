"""Configuration settings for Alfred Prime and Daemon."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Anthropic API
    anthropic_api_key: SecretStr = Field(..., description="Anthropic API key")

    # Telegram
    telegram_bot_token: SecretStr | None = Field(
        default=None, description="Telegram bot token"
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://alfred:alfred@localhost:5432/alfred",
        description="PostgreSQL connection URL",
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL",
    )

    # Security
    daemon_secret_key: SecretStr = Field(
        ..., description="Secret key for daemon authentication"
    )

    # Server
    host: str = Field(default="0.0.0.0", description="Server host")
    prime_port: int = Field(default=8000, description="Alfred Prime API port")
    daemon_port: int = Field(default=8001, description="Daemon API port")

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(
        default="INFO", description="Logging level"
    )


class DaemonSettings(BaseSettings):
    """Settings specific to daemon instances."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="DAEMON_",
    )

    # Identity
    name: str = Field(..., description="Unique daemon name")
    machine_type: str = Field(default="server", description="Type of machine")

    # Capabilities
    capabilities: list[str] = Field(
        default=["shell", "files"],
        description="Enabled capabilities",
    )

    # Prime connection
    prime_url: str = Field(
        default="http://localhost:8000",
        description="Alfred Prime API URL",
    )
    secret_key: SecretStr = Field(..., description="Shared secret for auth")

    # Local settings
    port: int = Field(default=8001, description="Local API port")
    work_dir: str = Field(default="/tmp/alfred", description="Working directory")


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


@lru_cache
def get_daemon_settings() -> DaemonSettings:
    """Get cached daemon settings."""
    return DaemonSettings()
