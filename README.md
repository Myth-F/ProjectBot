<div align="center">
  <h1>ProjectBot</h1>
  <p><strong>Task management directly inside Discord.</strong></p>

  <p>
    <a href="https://github.com/Myth-F/ProjectBot"><img alt="GitHub" src="https://img.shields.io/badge/GitHub-Myth--F%2FProjectBot-181717?logo=github" /></a>
    <img alt="Python" src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" />
    <img alt="Discord" src="https://img.shields.io/badge/Discord.py-2.4+-5865F2?logo=discord&logoColor=white" />
    <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-ready-009688?logo=fastapi&logoColor=white" />
    <img alt="Docker" src="https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white" />
  </p>

  <p>
    <a href="#quick-start">Quick start</a>
    ·
    <a href="#discord-commands">Commands</a>
    ·
    <a href="#architecture">Architecture</a>
    ·
    <a href="#observability">Observability</a>
  </p>
</div>

---

## About

ProjectBot is a multi-tenant Discord bot for managing tasks without leaving a server. Each Discord server receives its own workspace, members, and tasks.

The project combines an interactive bot, a monitoring API, and a background worker around PostgreSQL and Redis.

## Features

- create and browse tasks from Discord;
- edit titles, descriptions, statuses, and assignments;
- due dates and workspace-specific time zones;
- interactive lists with filters and pagination;
- data separation between Discord servers;
- action audit log;
- API, PostgreSQL, and Redis health checks;
- in-memory operation metrics and structured logs.

## Discord commands

| Command | Description |
| --- | --- |
| `/setup` | Initialize the server workspace |
| `/task` | Open the interactive task manager |
| `/add` | Quickly create a task |
| `/status` | Display system status |
| `/help` | Show built-in help |
| `/ping` | Check whether the bot responds |

Commands are synchronized automatically when the bot starts.

## Tech stack

| Component | Technologies |
| --- | --- |
| Bot | Python 3.11, discord.py |
| API | FastAPI, Uvicorn |
| Persistence | PostgreSQL, async SQLAlchemy, asyncpg |
| Cache and coordination | Redis |
| Configuration | pydantic-settings |
| Runtime | Docker Compose |

## Quick start

### Requirements

- a bot created in the [Discord Developer Portal](https://discord.com/developers/applications);
- Docker and Docker Compose.

Enable the application command permissions, then:

```bash
git clone https://github.com/Myth-F/ProjectBot.git
cd ProjectBot
cp .env.example .env
```

Set `DISCORD_TOKEN` in `.env`, then start the stack:

```bash
docker compose up --build
```

The API listens on port `8000` inside the Docker network. The local stack intentionally publishes no host port; add a reverse proxy route or port mapping if browser access is required.

> Never publish the Discord token or commit `.env`.

## Architecture

```text
src/projectbot/
├── api.py           # FastAPI application and monitoring endpoints
├── bot.py           # Discord commands and interactions
├── worker.py        # Background jobs
├── services.py      # Business use cases
├── models.py        # SQLAlchemy models
├── ui.py            # Embeds, buttons, menus, and modals
├── audit.py         # Action audit log
├── db.py            # PostgreSQL connection
├── redis_client.py  # Redis connection
├── config.py        # Environment configuration
└── logging.py       # Logs and metrics
```

The Docker stack runs five services:

```text
Discord ──► bot ───────┐
                       ├──► PostgreSQL
HTTP ─────► api ───────┤
                       └──► Redis
             worker ───┘
```

Adminer is also included for local database inspection.

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `DISCORD_TOKEN` | — | Required bot token |
| `DATABASE_URL` | Docker PostgreSQL | Asynchronous SQLAlchemy URL |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection |
| `API_HOST` | `0.0.0.0` | Listening interface |
| `API_PORT` | `8000` | API port |
| `WORKER_INTERVAL_SECONDS` | `5` | Worker interval |
| `LOG_LEVEL` | `INFO` | Logging level |

## Observability

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Check that the API process responds |
| `GET /ready` | Check PostgreSQL and Redis |
| `GET /metrics` | Return collected operation metrics |

Query a probe from inside the container:

```bash
docker compose exec api python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read().decode())"
```

## Development

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest
```

To start a single component, run `python -m projectbot.api`, `python -m projectbot.bot`, or `python -m projectbot.worker` in an environment where the package and its dependencies are installed.
