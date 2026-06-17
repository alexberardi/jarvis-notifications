# jarvis-notifications

FastAPI push-notification **and** in-app inbox service for Jarvis. Other services post events here; this service deduplicates them, persists durable inbox items and a notification log, resolves per-user device tokens, and (optionally) relays short alerts to Expo Push for device delivery. The mobile app reads the inbox and registers/unregisters its device tokens against this service.

Runs on **port 7712**.

## Two surfaces

- **Push notifications** — short, fire-and-forget alerts delivered to a device via Expo Push (through an optional relay).
- **Inbox** — persistent content items (deep-research results, meal-plan reminders, action confirmations) the mobile app reads via `GET /api/v0/inbox`.

A typical event creates both: an inbox item for durable content plus a push to alert the user.

## Requirements

- Python 3.11+
- Docker & Docker Compose (recommended)
- PostgreSQL (Alembic migrations; `DATABASE_URL` uses `psycopg2`). SQLite is supported for local/testing.
- Optional: an Expo Push relay (`RELAY_URL`) for actual device delivery. Without it, notifications are still persisted and served via the inbox.

## Setup & run

```bash
cp .env.example .env   # then edit values (see Environment below)

# Local development (hot reload):
./run.sh

# Docker development:
./run.sh --docker            # add --build to rebuild, --rebuild for a clean no-cache build
```

`./run.sh` activates `.venv` if present, installs the Jarvis client libraries, and runs Uvicorn on `${NOTIFICATIONS_PORT:-7712}` with `--reload`.

For a local run from scratch:

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m alembic upgrade head
./run.sh
```

- Swagger UI: http://localhost:7712/docs
- Health: http://localhost:7712/health
- Identity: http://localhost:7712/info

## Environment

Copy `.env.example` to `.env`. Configuration is defined in `app/config.py`.

The service **fails closed**: it refuses to start if `AUTH_SECRET_KEY` or `ADMIN_API_KEY` is empty or left as the `change-me`/`__SET_ME__` placeholder, since those secrets verify user JWTs and gate the admin API.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `AUTH_SECRET_KEY` | yes | — | Secret for verifying user JWTs. **Must match `jarvis-auth` and every service that validates JWTs.** |
| `AUTH_ALGORITHM` | no | `HS256` | JWT signing algorithm |
| `ADMIN_API_KEY` | yes | — | Gates the admin API (`X-Api-Key` header) |
| `DATABASE_URL` | yes | `sqlite:///./jarvis_notifications.db` | Database connection string (`postgresql+psycopg2://...` in deployment) |
| `NOTIFICATIONS_PORT` | no | `7712` | Port the service binds to |
| `JARVIS_APP_ID` | yes | — | This service's app id for app-to-app auth + remote logging |
| `JARVIS_APP_KEY` | yes | — | This service's app key (paired with `JARVIS_APP_ID`) |
| `JARVIS_CONFIG_URL` | yes | — | Service discovery (`jarvis-config-service`) |
| `JARVIS_AUTH_BASE_URL` | yes | — | `jarvis-auth` base URL for app-to-app validation |
| `RELAY_URL` | no | — | Expo Push relay URL; omit to disable device delivery |
| `RELAY_HOUSEHOLD_JWT` | no | — | Household JWT used when forwarding to the relay |
| `NOTIFICATION_LOG_RETENTION_DAYS` | no | `30` | How long to retain notification-log rows |
| `TOKEN_CLEANUP_INTERVAL_HOURS` | no | `24` | Interval for the device-token cleanup task |

## Authentication

- **User JWT** (mobile app): `Authorization: Bearer <jwt>` — validated locally with `AUTH_SECRET_KEY`. Used by the inbox and token endpoints.
- **App-to-app** (services): `X-Jarvis-App-Id` + `X-Jarvis-App-Key` — validated against `jarvis-auth`. Used by services posting notifications.
- **Admin**: `X-Api-Key` — compared (constant-time) against `ADMIN_API_KEY`.

## API

Routes are mounted under `/api/v0`:

- `POST /api/v0/notify` — services post a notification (app auth)
- `GET  /api/v0/inbox` — mobile reads inbox items (user JWT)
- `/api/v0/tokens` — register/unregister device tokens (user JWT)
- `/api/v0/admin/*` — admin operations (`X-Api-Key`)

See the Swagger UI at `/docs` for the full schema.

## Testing

```bash
.venv/bin/pytest
```
