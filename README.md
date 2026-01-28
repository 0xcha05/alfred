# Alfred Prime

A persistent AI agent that lives across all your machines, accessible through any channel, capable of acting on your behalf.

**One conversation. N machines. Things just happen.**

## Features

- **FULL CONTROL**: Alfred can do anything - shell, files, services, docker, git, even modify himself
- **Multi-machine orchestration**: Control all your machines from one interface
- **Self-improvement**: Alfred can modify his own code and restart himself
- **Intent-based commands**: Say "run the tests" instead of remembering exact commands
- **Parallel execution**: Tasks run simultaneously across machines
- **Learned patterns**: Alfred remembers "the usual" and your preferences
- **Soul Daemon**: A special daemon on Prime's server for self-modification
- **Full audit trail**: Every action logged for review

## Architecture

Daemons connect TO Prime using bidirectional TCP streams. This means daemons behind NAT (home networks, VPNs) work without port forwarding.

```
                    ┌─────────────────────────────────────┐
                    │           ALFRED PRIME (EC2)        │
                    │                                     │
                    │  HTTP :8000  - Telegram webhooks    │
                    │  TCP  :50051 - Daemon connections   │
                    │                                     │
                    │  • Understands intent (Claude API)  │
                    │  • Routes to machines               │
                    │  • Manages parallel execution       │
                    │  • Holds memory & patterns          │
                    └─────────────────────────────────────┘
                                     ▲
            ┌────────────────────────┼────────────────────────┐
            │                        │                        │
            │      Daemons CONNECT   │   to Prime             │
            │      (outbound TCP)    │                        │
            │                        │                        │
    ┌──────────────┐        ┌──────────────┐        ┌──────────────┐
    │   DAEMON     │        │   DAEMON     │        │   DAEMON     │
    │   MacBook    │        │    Soul      │        │  ThinkPad    │
    │  (home NAT)  │        │  (on Prime)  │        │  (office)    │
    │              │        │              │        │              │
    │  Connects ───┼────────┼──► Prime     │        │  Connects ───┤
    │  to Prime    │        │              │        │  to Prime    │
    └──────────────┘        └──────────────┘        └──────────────┘
```

**Key insight**: Daemons initiate the connection. Prime sends commands back on the same connection. No inbound ports needed on daemon machines.

## Quick Start

### Prerequisites

- Python 3.11+
- Go 1.22+
- Docker & Docker Compose
- ngrok (for Telegram webhook)

### 1. Clone and Setup

```bash
git clone <repository>
cd alfred

# Copy environment file
cp .env.example prime/.env
```

### 2. Configure Environment

Edit `prime/.env` with your settings:

```bash
# Required
TELEGRAM_TOKEN=your_bot_token          # From @BotFather
TELEGRAM_ALLOWED_USER_IDS=123456789    # Your Telegram user ID
CLAUDE_API_KEY=your_claude_api_key     # From console.anthropic.com
DAEMON_REGISTRATION_KEY=your_secret    # openssl rand -hex 32
```

### 3. Start Infrastructure

```bash
docker-compose up -d postgres redis
```

### 4. Start Prime

```bash
cd prime
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Start Daemon

On any machine you want Alfred to control:

```bash
cd daemon
DAEMON_NAME=macbook \
PRIME_ADDRESS=your-ec2-ip:50051 \
DAEMON_REGISTRATION_KEY=your_secret \
go run cmd/daemon/main.go
```

For local development (daemon on same machine as Prime):
```bash
DAEMON_NAME=local \
PRIME_ADDRESS=localhost:50051 \
DAEMON_REGISTRATION_KEY=your_secret \
go run cmd/daemon/main.go
```

### 6. Set Up Telegram Webhook

```bash
# Expose Prime with ngrok
ngrok http 8000

# Set webhook (replace with your ngrok URL)
curl -X POST "http://localhost:8000/setup-webhook?webhook_url=https://your-ngrok-url.ngrok.io"
```

### 7. Start Chatting

Message your bot on Telegram:
- "help" - See what Alfred can do
- "run ls -la" - Execute commands
- "what's running?" - Check status
- "machines" - List connected daemons

## Usage Examples

### Shell Commands

```
You: run the tests
Alfred: Running tests...
        ✓ 147 tests passed

You: check disk space
Alfred: $ df -h
        Filesystem      Size  Used  Avail
        /dev/sda1       500G  120G  380G

You: what's using port 3000
Alfred: $ lsof -i :3000
        node    12345  user   23u  IPv4  TCP *:3000 (LISTEN)
```

### Multi-Machine Operations

```
You: on the server, restart nginx
Alfred: Restarting nginx on server...
        ✓ nginx restarted

You: deploy to staging
Alfred: ⚠️ Confirm: deploy.sh staging?
        [Yes] [No]
You: [Yes]
Alfred: Deploying to staging...
        ✓ Deployed successfully
```

### Learned Patterns

```
You: the usual
Alfred: Order: Green curry + Pad Thai from Thai Garden, ₹850
        [Confirm] [Cancel]
```

## CLI Usage

```bash
# Direct commands
./cli/alfred.py "run the tests"
./cli/alfred.py machines
./cli/alfred.py status

# Interactive mode
./cli/alfred.py -i
alfred> ls -la
alfred> machines
alfred> exit
```

## Project Structure

```
alfred/
├── prime/                      # Alfred Prime (Python/FastAPI)
│   ├── app/
│   │   ├── main.py             # FastAPI entrypoint
│   │   ├── config.py           # Configuration
│   │   ├── grpc_server.py      # Daemon connection server
│   │   ├── api/                # REST endpoints
│   │   │   ├── telegram.py     # Telegram webhook
│   │   │   └── daemon.py       # Daemon status API
│   │   ├── core/               # Business logic
│   │   │   ├── intent.py       # Intent parsing
│   │   │   ├── router.py       # Task routing
│   │   │   ├── orchestrator.py # Parallel execution
│   │   │   ├── workflow.py     # Multi-step workflows
│   │   │   ├── patterns.py     # Learned patterns
│   │   │   ├── audit.py        # Audit logging
│   │   │   └── memory.py       # Persistent context
│   │   ├── models/             # Database models
│   │   └── services/           # External services
│   └── requirements.txt
├── daemon/                     # Daemon (Go)
│   ├── cmd/daemon/             # Entry point
│   ├── internal/
│   │   ├── config/             # Configuration
│   │   ├── executor/           # Shell/file execution
│   │   ├── primeclient/        # Bidirectional connection to Prime
│   │   ├── session/            # tmux sessions
│   │   └── browser/            # Browser automation
│   └── pkg/proto/              # Protocol definitions
├── proto/                      # Protobuf definitions
│   └── daemon.proto
├── cli/                        # CLI interface
│   └── alfred.py
├── scripts/                    # Utility scripts
├── docker-compose.yml          # Infrastructure
└── README.md
```

## Security

### What's Protected

| Threat | Mitigation |
|--------|------------|
| Unauthorized Telegram user | User ID whitelist |
| Webhook spoofing | Secret token verification |
| Network sniffing | TLS on all gRPC |
| Rogue daemon | Pre-shared registration key |

### Configuration

```bash
# Telegram: Only allow specific users
TELEGRAM_ALLOWED_USER_IDS=123456789,987654321

# Webhook: Verify requests from Telegram
TELEGRAM_WEBHOOK_SECRET=your_secret

# Daemon: Require registration key
DAEMON_REGISTRATION_KEY=your_secure_key
```

### Confirmation System

Dangerous actions require confirmation:
- Destructive: `rm`, `delete`, `drop`
- Deployment: `deploy`, `push to production`
- Financial: `order`, `purchase`

## Full Control - Daemon Capabilities

Alfred has **FULL CONTROL** over every machine. No restrictions.

| Capability | Description |
|------------|-------------|
| shell | Execute ANY command, with or without sudo |
| files | Read, write, delete, move, copy, chmod, chown |
| docker | Full docker and docker-compose control |
| services | Start/stop/restart system services (systemd, launchd) |
| packages | Install/remove packages (apt, yum, brew, pip, npm) |
| processes | List, kill any process |
| git | Full git operations |
| network | Network diagnostics, curl, wget |
| cron | Manage scheduled tasks |
| sessions | tmux session management |
| browser | Headless browser automation |

## Soul Daemon (Self-Modification)

The **Soul Daemon** is a special daemon that runs on the same server as Prime. It allows Alfred to:

- **Modify his own code**: Edit Prime or Daemon source files
- **Create new features**: Add new capabilities dynamically
- **Rebuild himself**: Recompile the daemon, restart Prime
- **Update dependencies**: pip install, go mod download
- **Backup and restore**: Create backups before modifications

### Running the Soul Daemon

On the **same machine as Prime**, run a daemon with the soul flag:

```bash
cd daemon
DAEMON_IS_SOUL=true \
ALFRED_ROOT=/path/to/alfred \
DAEMON_NAME=soul \
PRIME_ADDRESS=localhost:50051 \
DAEMON_REGISTRATION_KEY=your_secret \
go run cmd/daemon/main.go
```

The soul daemon connects to Prime locally and can modify Alfred's own code.

### Self-Improvement Commands

```
You: "update your dependencies"
Alfred: ⚠️ Confirm: Update Prime and Daemon dependencies?
You: Yes
Alfred: Updating... Done.

You: "add a feature to handle voice commands"
Alfred: ⚠️ Confirm: Modify Prime code to add voice handling?
You: Yes
Alfred: Creating app/services/voice.py... Done.
        Please rebuild and restart Prime.
```

## Audit Logging

All actions are logged:

```json
{
  "id": "audit-20240115120000-000001",
  "timestamp": "2024-01-15T12:00:00Z",
  "event_type": "command",
  "action": "shell",
  "parameters": {"command": "ls -la"},
  "success": true,
  "duration_ms": 42
}
```

Query via Telegram: "show me what you did yesterday"

## Development

### Generate Protobuf

```bash
./scripts/generate_proto.sh
```

### Run Tests

```bash
cd prime && python -m pytest
cd daemon && go test ./...
```

### Test Setup

```bash
python scripts/test_setup.py
```

## How Connections Work

### NAT-Friendly Design

Most machines (laptops, home servers) are behind NAT. Alfred uses a "daemon connects to Prime" model:

1. **Prime runs on a public server** (EC2, DigitalOcean, etc.) with ports 8000 (HTTP) and 50051 (TCP) open
2. **Daemons connect outbound** to Prime - this always works, even behind strict NAT
3. **Prime sends commands** back on the same connection using bidirectional streaming
4. **No port forwarding** needed on daemon machines

```
MacBook (behind NAT)              EC2 (public IP)
┌─────────────────┐              ┌─────────────────┐
│     Daemon      │──────────────│      Prime      │
│                 │  outbound    │                 │
│  No open ports  │  TCP :50051  │  Listens on     │
│  needed!        │◄─────────────│  :8000, :50051  │
└─────────────────┘  bidirectional└─────────────────┘
```

### Connection Protocol

- **TCP with JSON messages** (length-prefixed)
- **Bidirectional streaming** - both sides can send messages anytime
- **Auto-reconnect** with exponential backoff
- **Heartbeats** every 30 seconds

## Configuration Reference

### Prime Configuration

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_TOKEN` | Bot token from @BotFather | Yes |
| `TELEGRAM_WEBHOOK_SECRET` | Webhook verification secret | Recommended |
| `TELEGRAM_ALLOWED_USER_IDS` | Comma-separated user IDs | Recommended |
| `CLAUDE_API_KEY` | Anthropic API key | Yes |
| `CLAUDE_MODEL` | Model to use (default: claude-sonnet-4-20250514) | No |
| `DAEMON_REGISTRATION_KEY` | Shared secret for daemons | Yes |
| `DAEMON_PORT` | Port for daemon connections (default: 50051) | No |
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `REDIS_URL` | Redis connection string | Yes |

### Daemon Configuration

| Variable | Description | Required |
|----------|-------------|----------|
| `DAEMON_NAME` | Friendly name (e.g., "macbook", "server") | Recommended |
| `PRIME_ADDRESS` | Prime's TCP address (e.g., "ec2-ip:50051") | Yes |
| `DAEMON_REGISTRATION_KEY` | Same key as Prime | Yes |
| `DAEMON_IS_SOUL` | Set to "true" for soul daemon | No |
| `ALFRED_ROOT` | Path to Alfred source (soul daemon only) | No |

## Roadmap

- [x] Phase 1: Single daemon, Telegram, basic execution
- [x] Phase 2: Multi-machine routing, parallel execution
- [x] Phase 3: Browser automation, workflows, patterns
- [x] Phase 4: Audit logging, CLI, error recovery
- [ ] Phase 5: WhatsApp integration
- [ ] Phase 6: Voice commands
- [ ] Phase 7: Mobile app

## License

MIT
