"""Alfred Prime - Configuration."""

from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Environment
    environment: str = "development"
    debug: bool = False
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Database
    database_url: str = "postgresql+asyncpg://alfred:alfred@localhost:5432/alfred"
    
    # Redis
    redis_url: str = "redis://localhost:6379/0"
    
    # Telegram
    telegram_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_allowed_user_ids: List[int] = []
    
    # Claude API
    claude_api_key: str = ""
    claude_model: str = "claude-sonnet-4-20250514"
    
    # Daemon Communication
    daemon_registration_key: str = ""
    grpc_port: int = 50051
    
    # TLS
    tls_cert_path: str = "certs/server.crt"
    tls_key_path: str = "certs/server.key"


settings = Settings()
