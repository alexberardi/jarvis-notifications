# jarvis-notifications

Push notification service for the Jarvis ecosystem. Manages device token registration, notification sending with dedup, and optional relay forwarding to Expo Push API.

## Quick Reference

```bash
# Setup
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# Configure
cp .env.example .env
# Edit .env — set DATABASE_URL, AUTH_SECRET_KEY, JARVIS_APP_KEY

# Run migrations
.venv/bin/python -m alembic upgrade head

# Run (port 7712)
./run.sh                    # Local dev
./run.sh --docker           # Docker dev

# Test
.venv/bin/pytest
```

## Architecture

```
app/
├── main.py                    # FastAPI app, lifespan, logging
├── config.py                  # Pydantic Settings
├── db.py                      # SQLAlchemy engine + session
├── models.py                  # DeviceToken, NotificationLog, InboxItem
├── deps.py                    # Auth dependencies (JWT, app-to-app, admin)
├── core/
│   └── service_config.py      # jarvis-config-client wrapper
├── api/
│   ├── tokens.py              # Token registration (JWT auth)
│   ├── notify.py              # Send notifications (app-to-app auth)
│   ├── inbox.py               # Inbox CRUD (JWT + app-to-app auth)
│   └── admin.py               # Stats/cleanup (admin auth)
└── services/
    ├── token_service.py        # Token CRUD
    ├── notification_service.py # Send logic, relay, dedup, retry
    ├── inbox_service.py        # Inbox item CRUD
    └── cleanup_service.py      # Background pruning
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | PostgreSQL connection |
| `NOTIFICATIONS_PORT` | 7712 | API port |
| `AUTH_SECRET_KEY` | change-me | JWT signing key (must match jarvis-auth) |
| `AUTH_ALGORITHM` | HS256 | JWT algorithm |
| `ADMIN_API_KEY` | - | Admin endpoint protection |
| `JARVIS_APP_ID` | jarvis-notifications | App credential ID |
| `JARVIS_APP_KEY` | - | App credential key |
| `JARVIS_CONFIG_URL` | http://localhost:7700 | Service discovery |
| `RELAY_URL` | - | Relay URL (optional, omit to skip push delivery) |
| `RELAY_HOUSEHOLD_JWT` | - | Household JWT for relay auth |
| `NOTIFICATION_LOG_RETENTION_DAYS` | 30 | Days to keep notification logs |
| `TOKEN_CLEANUP_INTERVAL_HOURS` | 24 | Cleanup interval |

## API Endpoints

**Token Management (JWT auth — mobile app):**
- `POST /api/v0/tokens` — Register push token
- `DELETE /api/v0/tokens` — Unregister push token
- `GET /api/v0/tokens/me` — List my tokens

**Notification Sending (app-to-app auth — services):**
- `POST /api/v0/notify` — Send notification
- `POST /api/v0/notify/batch` — Send batch (max 100)

**Inbox (JWT auth — mobile app):**
- `GET /api/v0/inbox` — List items (paginated, filter by category/is_read)
- `GET /api/v0/inbox/unread-count` — Unread count for badge
- `GET /api/v0/inbox/{id}` — Get full item (auto-marks read)
- `PATCH /api/v0/inbox/{id}/read` — Mark as read
- `DELETE /api/v0/inbox/{id}` — Delete item

**Inbox Creation (app-to-app auth — services):**
- `POST /api/v0/inbox` — Create inbox item (e.g., deep research results)

**Admin (X-Api-Key auth):**
- `GET /api/v0/admin/stats` — Token counts, send volume
- `POST /api/v0/admin/cleanup` — Force cleanup

**Health (unauthenticated):**
- `GET /health` — Health check
- `GET /info` — Service identity

## Authentication

Three auth patterns:
- **User JWT** (mobile): `Authorization: Bearer <token>` — validated locally via python-jose
- **App-to-app** (services): `X-Jarvis-App-Id` + `X-Jarvis-App-Key` — validated via jarvis-auth
- **Admin**: `X-Api-Key` header — checked against `ADMIN_API_KEY` env var

## Database

PostgreSQL required. Three tables:
- `device_tokens` — Push token registry (Expo push tokens per user/device)
- `notification_log` — Send history with delivery status
- `inbox_items` — Long-form content delivery (deep research results, alerts, etc.)

Run migrations: `alembic upgrade head`

## Dependencies

**Service Dependencies:**
- **Required**: `jarvis-config-service` (7700) — Service discovery
- **Required**: `jarvis-auth` (7701) — App-to-app auth validation
- **Required**: PostgreSQL — Data storage
- **Optional**: `jarvis-logs` (7702) — Centralized logging
- **Optional**: Relay (`relay.jarvisautomation.io`) — Expo Push delivery

**Used By:**
- `jarvis-command-center` — Send push for deep research results
- `jarvis-recipes-server` — Send push for meal plan reminders
- `jarvis-node-setup` — Agent scheduler push alerts
- `jarvis-node-mobile` — Token registration

**Impact if Down:**
- No push notification delivery
- Services can still call the API (graceful failure)
- Token registration fails (mobile retries on next launch)

## Key Features

- **Dedup**: Same notification (source, target, title, body, category) suppressed within 60s
- **Relay forwarding**: Optional — if `RELAY_URL` not set, everything works except push delivery
- **Retry queue**: In-memory, exponential backoff (30s/60s/120s), lost on restart
- **Cleanup**: Background task prunes logs (30d) and stale tokens (90d)

## Testing

```bash
.venv/bin/pytest -v --tb=short
.venv/bin/pytest --cov=app --cov-report=term-missing
```

37 tests, 77% coverage. Inbox endpoints need test coverage (coming soon). Uncovered code is auth boilerplate (mocked in tests) and relay retry logic.
