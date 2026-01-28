# Alfred Prime

A persistent AI agent that lives across all your machines, accessible through any channel, capable of acting on your behalf.

## Overview

Alfred Prime is a distributed AI assistant system that:
- **Understands intent**: You speak what you want, not how to do it
- **Manages multiple machines**: One conversation, N machines
- **Remembers context**: Your projects, preferences, and history
- **Acts, not advises**: Executes tasks directly on your infrastructure

## Architecture

```
                    YOU
                     │
                     │ Telegram / CLI
                     │
                     ▼
        ┌─────────────────────────┐
        │     ALFRED PRIME        │
        │  (Brain & Orchestrator) │
        └─────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
   ┌─────────┐ ┌─────────┐ ┌─────────┐
   │ DAEMON  │ │ DAEMON  │ │ DAEMON  │
   │ MacBook │ │  Server │ │   EC2   │
   └─────────┘ └─────────┘ └─────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL 16+
- Redis 7+
- Anthropic API key

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/alfred.git
cd alfred

# Install dependencies
pip install -e ".[dev]"

# Copy environment template
cp .env.example .env
# Edit .env with your API keys
```

### Running with Docker

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f alfred-prime
```

### Running Locally

```bash
# Start PostgreSQL and Redis (or use Docker)
docker-compose up -d postgres redis

# Run database migrations
alembic upgrade head

# Start Alfred Prime
alfred-prime

# In another terminal, start a daemon
DAEMON_NAME=my-laptop DAEMON_SECRET_KEY=your-secret alfred-daemon

# Use the CLI
alfred-cli
```

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `ANTHROPIC_API_KEY` | Anthropic API key for Claude | Yes |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | No |
| `DATABASE_URL` | PostgreSQL connection URL | Yes |
| `REDIS_URL` | Redis connection URL | Yes |
| `DAEMON_SECRET_KEY` | Shared secret for daemon auth | Yes |

### Daemon Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DAEMON_NAME` | Unique daemon identifier | Required |
| `DAEMON_MACHINE_TYPE` | Type of machine | `server` |
| `DAEMON_CAPABILITIES` | Enabled capabilities | `["shell", "files"]` |
| `DAEMON_PRIME_URL` | Alfred Prime URL | `http://localhost:8000` |
| `DAEMON_PORT` | Local API port | `8001` |

## Usage

### Telegram

1. Create a bot via [@BotFather](https://t.me/botfather)
2. Set `TELEGRAM_BOT_TOKEN` in your `.env`
3. Start Alfred Prime
4. Message your bot!

### CLI

```bash
# Interactive mode
alfred-cli

# Single message
alfred-cli "list files in ~/projects"

# Check status
alfred-cli --status
```

### API

```bash
# Send a message
curl -X POST http://localhost:8000/api/message \
  -H "Content-Type: application/json" \
  -d '{"message": "run the tests", "user_id": "user1"}'

# Check status
curl http://localhost:8000/status
```

## Daemon Capabilities

| Capability | Description |
|------------|-------------|
| `shell` | Execute commands, manage processes |
| `files` | Read, write, move, copy, delete files |
| `browser` | Browser automation (coming soon) |
| `docker` | Container management (coming soon) |

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run linter
ruff check src tests

# Run type checker
mypy src
```

## Project Structure

```
alfred/
├── src/alfred/
│   ├── common/          # Shared models and utilities
│   ├── config.py        # Configuration management
│   ├── memory/          # Database models and store
│   ├── prime/           # Alfred Prime (brain)
│   │   ├── brain.py     # Central orchestrator
│   │   ├── intent.py    # Intent parsing with Claude
│   │   ├── router.py    # Task routing to daemons
│   │   ├── channels/    # Communication channels
│   │   └── main.py      # API server
│   ├── daemon/          # Daemon (hands)
│   │   ├── capabilities/# Pluggable capabilities
│   │   ├── executor.py  # Task execution
│   │   └── main.py      # Daemon server
│   └── cli/             # Command-line interface
├── tests/               # Test suite
├── alembic/             # Database migrations
└── docker-compose.yml   # Local development setup
```

## License

MIT
