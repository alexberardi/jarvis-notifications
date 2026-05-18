# jarvis-notifications

Push notifications **and** in-app inbox storage. Services post notifications here; this service deduplicates, persists, optionally relays to Expo Push for device delivery, and surfaces long-form content via the inbox API for mobile.

> **Identity rule:** this is the *outbound* user-communication channel. If a service has something to *tell* a user, it goes through here. For ephemeral confirmations during a voice flow (e.g. "send this email?") the inbox is the durable record; the voice channel handles the immediate prompt.

---

## Two product surfaces

| Surface | What it is | Consumers |
|---|---|---|
| **Push notifications** | Short, fire-and-forget alerts → device via Expo Push | Mobile app via registered device tokens |
| **Inbox** | Persistent content items (deep-research results, meal-plan reminders, action confirmations) | Mobile app reads via `/api/v0/inbox` |

A typical event creates **both** — an inbox item for durable content + a push to alert the user.

---

## Topology

```
Service (CC, recipes, etc.)
   │ POST /api/v0/notify (or /inbox)
   │ X-Jarvis-App-Id/Key
   ▼
┌─────────────────────────────────────────┐
│  jarvis-notifications :7712             │
│                                          │
│  ├─ dedup (60s in-memory key)           │
│  ├─ persist (NotificationLog / Inbox)   │
│  ├─ resolve device tokens (per target)  │
│  └─ (optional) forward to Relay         │
└──────────────────────────────────┬──────┘
                                   │
                       (if RELAY_URL set)
                                   │
                                   ▼
                          Relay (Expo Push proxy)
                                   │
                                   ▼
                            Mobile device

Mobile reads inbox via GET /api/v0/inbox (JWT auth)
Mobile registers/unregisters tokens via /api/v0/tokens (JWT auth)
```

---

## Quick Reference

```bash
# Local dev
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m alembic upgrade head
./run.sh

# Docker dev
./run.sh --docker

# Tests
.venv/bin/pytest -v --tb=short
```

---

## Dependency graph

**Upstream (notifications depends on):**
- **PostgreSQL** (required) — tokens, notification log, inbox items
- **jarvis-auth** (required) — app-to-app validation + JWT validation (shared secret)
- **jarvis-config-service** (required) — service discovery
- **jarvis-logs** (optional) — remote logging
- **Relay** (optional, `RELAY_URL`) — forwards to Expo Push API. **If not set, the service still works for storage + inbox; only push delivery is disabled.**

**Downstream (depends on notifications):**
- **jarvis-command-center** — pushes deep-research results into the inbox; pushes action-confirmation items (from voice tool results with `context.actions`) via `inbox_notification_service`
- **jarvis-recipes-server** — meal plan reminders
- **jarvis-node-setup** — agent scheduler alerts
- **jarvis-node-mobile** — registers tokens, reads inbox, reads unread count

**Impact if down:**
- No new push notifications, no new inbox items, no token registration changes
- Mobile inbox UI shows stale state (last cached fetch)
- Services calling `/api/v0/notify` fail soft (their flows shouldn't crash)

---

## Lifecycle / common operations

### 1. Send a push notification (service → user)

```
Service               jarvis-notifications              jarvis-auth        Relay → Expo
  │ POST /notify
  │ {app_id, app_key, target: {type: "user"|"household"|"node", id},
  │  title, body, category, data}
  │
  │       ├─ verify_app_auth (X-Jarvis-App-Id/Key → /internal/app-ping) ─▶
  │       │
  │       ├─ dedup check (60s in-memory cache, key=md5(source:target:title:body:category))
  │       │   └─ duplicate? short-circuit, return {status: deduped}
  │       │
  │       ├─ resolve target → list of active DeviceToken rows
  │       ├─ insert NotificationLog(status=pending)
  │       │
  │       ├─ if RELAY_URL: POST tokens + payload to relay (async, fire-and-forget)
  │       │   ├─ on success: log.status=delivered
  │       │   ├─ on 410 (invalid token): deactivate that token row
  │       │   ├─ on 5xx: push to in-memory retry queue (3 attempts, 30/60/120s)
  │       │   └─ on no-relay: log.status=skipped
  │       │
  │ ◀── {"status": "delivered" | "deduped" | "skipped", "tokens_used": N}
```

### 2. Create an inbox item (from CC for confirmations or deep research)

```
CC                  jarvis-notifications
  │ POST /api/v0/inbox (app-to-app)
  │ {household_id, user_id?, title, summary, body, category,
  │  command_name?, actions[], draft?}
  │
  │       ├─ verify_app_auth
  │       ├─ persist InboxItem
  │       └─ optionally also create a push (caller's choice; CC's inbox_notification_service
  │          calls both endpoints when it wants both surfaces)
```

### 3. Mobile reads inbox

```
Mobile              jarvis-notifications
  │ GET /api/v0/inbox?page=1&limit=20&category=...&is_read=false
  │ Bearer <JWT>
  │
  │       ├─ JWT validated locally (shared AUTH_SECRET_KEY)
  │       ├─ scope to household_id from JWT
  │       └─ paginate, return items
```

### 4. Background cleanup

- **Hourly** (configurable): clean expired dedup cache entries
- **Every `TOKEN_CLEANUP_INTERVAL_HOURS`** (default 24h): prune NotificationLog rows older than `NOTIFICATION_LOG_RETENTION_DAYS` (default 30) and inactive DeviceTokens older than 90 days

---

## "How to..." recipes

### Add a new notification category

No code change. `category` is a free-form string field. The mobile UI can filter by it. Keep categories stable — they appear in the dedup key, so changing the category of an existing notification effectively bypasses dedup for that event.

### Add a new inbox item type (e.g. "weekly digest")

Just POST to `/api/v0/inbox` with the new `category`. The mobile inbox renders items generically; specialized rendering happens client-side. **If you need per-category server-side handling** (e.g. TTL), add it to `inbox_service.py` — there's no schema change because it's all in JSON columns.

### Wire a new service to push notifications

1. The calling service needs `JARVIS_APP_ID` + `JARVIS_APP_KEY` (created via config-service first-boot or `/admin/app-clients`).
2. POST to `/api/v0/notify` with the standard payload. Target by `{type: "user", id: <user_id>}`, `{type: "household", id: <hh_id>}`, or `{type: "node", id: <node_id>}`.
3. **Handle the response gracefully** — don't fail the caller's flow if notify returns non-200. Notifications are a side channel.

### Test push delivery without a real device

Set `RELAY_URL=` (empty) — notifications persist and dedup but skip delivery. Inspect `notification_log` in Postgres to see what would have been sent. For full end-to-end, point at the dev relay (`relay.jarvisautomation.io` with a dev household JWT) or a local mock.

### Turn off push delivery temporarily

Unset `RELAY_URL`. The service stays functional for storage + inbox + token CRUD. Don't drop tokens — they'll be valid again when push is re-enabled.

---

## Invariants & gotchas

1. **Dedup is in-memory, not durable.** The dedup cache (`_dedup_cache` in `notification_service.py`) is per-process. A restart resets it; duplicates within 60s across a restart are possible but rare. Don't expect dedup to survive deploys.
2. **Retry queue is in-memory, not durable.** Same as dedup: a restart drops queued retries. Acceptable trade-off — push delivery is best-effort by design. If you need durable delivery, use the inbox (the persisted record).
3. **Relay is optional by design.** Missing `RELAY_URL` is a *valid* configuration, not a bug. Code paths that assume push delivery happened are wrong; check the response's `status` field.
4. **Dedup key includes `source_service`.** Two services posting the same notification body to the same user **don't** dedup against each other — that's deliberate. If you want cross-service dedup, you'd need to normalize source_service to a constant.
5. **JWT validation is local.** Same shared-secret pattern as the rest of the stack — uses `AUTH_SECRET_KEY` (must match jarvis-auth). No round-trip to auth for JWT validation. App-to-app does round-trip.
6. **`AUTH_SECRET_KEY` is named differently across services.** Here it's `AUTH_SECRET_KEY`. In jarvis-auth it's `AUTH_SECRET_KEY` too (via Pydantic alias). Keep them aligned. The meta CLAUDE.md still calls this `SECRET_KEY` — outdated.
7. **Token deactivation on 410 from Expo.** Stale tokens (uninstalled app, etc.) are auto-deactivated when Expo returns 410. Don't rely on tokens existing forever; mobile re-registers on every launch.
8. **Inbox auto-marks-as-read on GET single item.** `GET /api/v0/inbox/{id}` flips `is_read=true` as a side effect. If you don't want that, use the list endpoint with `?id=...` filter (if/when added) or peek directly into Postgres.
9. **Three auth patterns coexist on this service.** Token endpoints = JWT (the mobile user). Notify endpoints = app-to-app (service callers). Admin endpoints = `X-Api-Key`. Don't pick the wrong one when adding a new route.
10. **Batch endpoint caps at 100.** `/api/v0/notify/batch` rejects payloads bigger than that. For bulk sends (household-wide announcements), chunk client-side.

---

## API surface

### Token management (JWT, mobile)
| Method | Path | Notes |
|---|---|---|
| POST | `/api/v0/tokens` | Register a push token. Body: `{token, platform, device_name?}` |
| DELETE | `/api/v0/tokens` | Unregister (body: `{token}`) |
| GET | `/api/v0/tokens/me` | List my tokens |

### Notify (app-to-app, services)
| Method | Path | Notes |
|---|---|---|
| POST | `/api/v0/notify` | Send one |
| POST | `/api/v0/notify/batch` | Send many (≤100) |

### Inbox
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v0/inbox` | JWT | Pagination + filter by `category`, `is_read` |
| GET | `/api/v0/inbox/unread-count` | JWT | Badge count |
| GET | `/api/v0/inbox/{id}` | JWT | **Auto-marks read** |
| PATCH | `/api/v0/inbox/{id}/read` | JWT | Mark read without fetch |
| DELETE | `/api/v0/inbox/{id}` | JWT | Soft delete |
| POST | `/api/v0/inbox` | app-to-app | Create (services only) |

### Admin
| Method | Path | Auth | Notes |
|---|---|---|---|
| GET | `/api/v0/admin/stats` | X-Api-Key | Token counts, send volume |
| POST | `/api/v0/admin/cleanup` | X-Api-Key | Force cleanup tick |

### Open
| Method | Path |
|---|---|
| GET | `/health` |
| GET | `/info` |

---

## Data model

```python
DeviceToken        # token (unique), platform, user_id, household_id, device_name, last_used_at, is_active
NotificationLog    # source_service, target_type, target_id, title, body, category, status, retry_count, ...
InboxItem          # household_id, user_id?, title, summary, body, category, actions (JSON), draft (JSON),
                   # command_name, is_read, created_at
```

Migrations under `alembic/`. No multi-tenant settings table — this service has no runtime configuration UI.

---

## Config surface

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DATABASE_URL` | yes | — | Postgres |
| `AUTH_SECRET_KEY` | yes | — | JWT validation — must match jarvis-auth |
| `AUTH_ALGORITHM` | no | `HS256` | |
| `JARVIS_CONFIG_URL` | yes | `http://localhost:7700` | Service discovery |
| `JARVIS_APP_ID` | yes | `jarvis-notifications` | App credential |
| `JARVIS_APP_KEY` | yes | — | App credential key |
| `ADMIN_API_KEY` | yes | — | Admin endpoint protection |
| `RELAY_URL` | optional | — | Expo Push relay (omit to disable push delivery) |
| `RELAY_HOUSEHOLD_JWT` | optional | — | Auth for relay |
| `NOTIFICATIONS_PORT` | no | `7712` | API bind |
| `NOTIFICATION_LOG_RETENTION_DAYS` | no | `30` | Pruning |
| `TOKEN_CLEANUP_INTERVAL_HOURS` | no | `24` | Pruning cadence |

---

## Architecture

```
app/
├── main.py                            # FastAPI factory, lifespan, logging
├── config.py                          # Pydantic Settings (env-based)
├── db.py                              # SQLAlchemy engine + session
├── models.py                          # DeviceToken, NotificationLog, InboxItem
├── deps.py                            # require_jwt, require_app_auth, require_admin
├── core/service_config.py             # jarvis-config-client wrapper
├── api/
│   ├── tokens.py                      # /tokens (JWT)
│   ├── notify.py                      # /notify (+ /batch) (app-to-app)
│   ├── inbox.py                       # /inbox (mixed JWT + app-to-app)
│   └── admin.py                       # /admin (X-Api-Key)
├── services/
│   ├── token_service.py
│   ├── notification_service.py        # Dedup, retry queue, relay forwarding
│   ├── inbox_service.py
│   └── cleanup_service.py             # Background pruning
alembic/                               # Migrations
tests/                                 # 37 tests, 77% coverage
```

---

## Testing

```bash
.venv/bin/pytest -v --tb=short
.venv/bin/pytest --cov=app --cov-report=term-missing
```

37 tests, 77% coverage. Inbox endpoints need more coverage (TODO). Uncovered code is mostly auth boilerplate (mocked) and relay-retry edge paths.

---

## Failure modes

| Failure | Behavior |
|---|---|
| Postgres down | All endpoints 5xx |
| Auth down | App-to-app fails (401/503); JWT validation still works locally (no round-trip) |
| Relay down | Notifications persist + dedup; push delivery fails; retries fire then give up |
| `RELAY_URL` unset | All notify calls return `status=skipped` for push; inbox still works |
| Wrong AUTH_SECRET_KEY | All JWT requests 401 |
| Service restart with retries in queue | Queued retries lost; persisted notification logs stay marked as pending until cleanup |

---

## Out of scope / explicitly not here

- **SMS / email.** No email/SMS providers. Push + in-app only.
- **Direct device-to-device push.** All push goes through the relay → Expo Push.
- **Long-term archival.** NotificationLog is pruned at 30d (configurable). For permanent records, use the inbox.
- **Templating.** Callers send pre-formatted title/body. No template engine here.
- **Scheduled notifications.** No "send at 5pm" scheduler. If the caller wants delayed delivery, they schedule it on their side.
