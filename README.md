# Community Trouble Register (CTR)

An original starter project for a community-driven game-server moderation register:
- FastAPI backend and JSON API
- SQLite for local development; PostgreSQL URL supported through `DATABASE_URL`
- Dark web interface with player lookup, server listing, and admin-friendly pages
- Server registration and API keys
- Reports and per-server votes
- Garry's Mod Lua addon example

This is an MVP scaffold, not a production-ready public ban network. Before public launch, add proper account verification, CSRF protection for browser sessions, email/Steam login, abuse monitoring, backups, and a documented appeals/correction process.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000

The first startup creates the database and a development admin account from `.env`.
Change `ADMIN_USERNAME` and `ADMIN_PASSWORD` before exposing the service to a network.

## Environment

See `.env.example`. For PostgreSQL, set `DATABASE_URL` to a SQLAlchemy URL such as:
`postgresql+psycopg://user:password@localhost:5432/ctr`

## API overview

- `GET /api/v1/health`
- `GET /api/v1/players/{steamid}/status`
- `GET /api/v1/players/{steamid}`
- `GET /api/v1/servers`
- `POST /api/v1/servers/register` — admin/development setup token required
- `POST /api/v1/reports` — authenticated server API key
- `POST /api/v1/votes` — authenticated, verified server API key
- `GET /docs` — interactive API docs

Authentication for server endpoints uses `X-API-Key`. The starter deliberately does not implement ETR's HMAC scheme or copy its endpoint contract. HMAC request signing can be added as a separately tested feature.

## Moderation design

This starter records reports and votes but **does not automatically impose a global ban merely because a numeric threshold is met**. A public cross-community ban system should include review, evidence, duplicate-report handling, server verification, voting safeguards, audit history, and a correction/appeals process before automatic enforcement is enabled.

## Garry's Mod addon

Copy `gmod/addon.json` and `gmod/lua/` into a Garry's Mod addon folder named `ctr_integration`, or install the `gmod` folder contents as an addon.

Set server-only convars in `server.cfg`:

```cfg
ctr_api_url "https://your-ctr-service.example"
ctr_setup_token "your-private-server-pairing-token"
ctr_fail_closed "0"
ctr_heartbeat_interval "300"
```

The first successful registration writes the issued API key and registration ID to `garrysmod/data/ctr/server_state.json`. Keep this file private. Restarting the server reuses the credential and remains idempotent. Administrators verify the server in `/admin`; only then can server-originated API actions proceed under the server's assigned permissions.

Testing:

1. Install on a private dedicated server.
2. Set the URL and setup token, then restart.
3. Confirm startup and registration logs, pending status in `/admin`, and heartbeat updates.
4. Verify the server in `/admin`.
5. Console: `ctr_ban 76561198000000000 1d Repeated harassment`
6. Chat: `!ctr_ban 76561198000000000 permanent Serious confirmed abuse`
7. Revoking the ban in `/admin` must stop enforcement on the next player check.

Global ban permission is independent: set it per server in the admin console. A SuperAdmin GMod permission alone does not grant CTR global-ban authority. API outages fail open by default; set `ctr_fail_closed "1"` only for an explicitly chosen strict policy.
