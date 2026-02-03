# ProjectBot

Minimal, scalable foundation for a multi-tenant project management bot. My intent is to create a bot to facilitate my Project Management for the next 2 years :

- `projectbot.api`: FastAPI app (health endpoints, webhooks later)
- `projectbot.bot`: Discord bot gateway (commands/events)
- `projectbot.worker`: background worker (jobs, schedules)

## Quick start (Docker Compose)

```
cp .env.example .env
docker compose up --build
```

I run the service on Coolify

## Services

- API: `http://localhost:8000/health`
- Bot: connects to Discord using `DISCORD_TOKEN` in .env
- Worker: background loop (placeholder)
