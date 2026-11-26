import os, re, secrets
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Header, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy.orm import Session
from sqlalchemy import select, func, text
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from .db import Base, engine, get_db, SessionLocal
from .models import User, GameServer, Report, Vote, AuditEvent, GlobalBan
from .security import hash_password, verify_password, new_api_key, hash_key

load_dotenv()
BASE = Path(__file__).resolve().parent
app = FastAPI(title="Community Trouble Register API", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
Base.metadata.create_all(bind=engine)

def ensure_sqlite_columns():
    if not str(engine.url).startswith("sqlite"):
        return
    with engine.begin() as connection:
        existing = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(game_servers)").fetchall()}
        additions = {
            "verification_status": "VARCHAR(32) NOT NULL DEFAULT 'pending_verification'",
            "pairing_token_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
            "registration_id": "VARCHAR(80) NOT NULL DEFAULT ''",
            "owner_id": "INTEGER",
            "can_issue_global_bans": "BOOLEAN NOT NULL DEFAULT 0",
            "last_heartbeat": "DATETIME",
            "player_count": "INTEGER NOT NULL DEFAULT 0",
            "max_player_count": "INTEGER NOT NULL DEFAULT 0",
            "gmod_version": "VARCHAR(100) NOT NULL DEFAULT ''",
        }
        for column, ddl in additions.items():
            if column not in existing:
                connection.exec_driver_sql(f"ALTER TABLE game_servers ADD COLUMN {column} {ddl}")
ensure_sqlite_columns()

def seed_admin():
    with SessionLocal() as db:
        username = os.getenv("ADMIN_USERNAME", "admin")
        password = os.getenv("ADMIN_PASSWORD", "change-this-password")
        if not db.scalar(select(User).where(User.username == username)):
            db.add(User(username=username, password_hash=hash_password(password), is_admin=True))
            db.commit()
seed_admin()

def _cookie_signer():
    return URLSafeTimedSerializer(os.getenv("APP_SECRET", "replace-with-a-long-random-secret"), salt="ctr-admin-session")

def get_admin(request: Request, db: Session):
    token = request.cookies.get("ctr_admin")
    if not token:
        return None
    try:
        uid = _cookie_signer().loads(token, max_age=8 * 60 * 60)
    except (BadSignature, SignatureExpired):
        return None
    if not str(uid).isdigit():
        return None
    user = db.get(User, int(uid))
    return user if user and user.is_admin else None

def require_admin(request: Request, db: Session):
    user = get_admin(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Admin login required")
    return user

def get_server(x_api_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    if not x_api_key:
        raise HTTPException(status_code=401, detail="X-API-Key required")
    server = db.scalar(select(GameServer).where(GameServer.api_key_hash == hash_key(x_api_key)))
    if not server or not server.active:
        raise HTTPException(status_code=403, detail="Invalid or inactive API key")
    return server

def valid_steamid(value: str) -> bool:
    return bool(re.fullmatch(r"7656119\d{10}", value))

def utcnow():
    return datetime.now(timezone.utc)

def parse_ban_expiry(duration: str) -> tuple[str, datetime | None]:
    duration = duration.strip().lower()
    if duration in ("permanent", "perm", "0"):
        return "permanent", None
    match = re.fullmatch(r"(\d+)([mhdw])", duration)
    if not match:
        raise HTTPException(status_code=422, detail="Duration must be permanent or use m, h, d, or w")
    amount = int(match.group(1))
    if amount < 1:
        raise HTTPException(status_code=422, detail="Duration must be greater than zero")
    unit = match.group(2)
    seconds = amount * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    if seconds > 365 * 86400:
        raise HTTPException(status_code=422, detail="Temporary bans cannot exceed one year")
    return duration, utcnow() + timedelta(seconds=seconds)

def active_global_ban(db: Session, steamid: str):
    now = utcnow()
    bans = db.scalars(
        select(GlobalBan)
        .where(GlobalBan.steamid == steamid, GlobalBan.status == "active")
        .order_by(GlobalBan.created_at.desc())
    ).all()
    for ban in bans:
        if ban.expires_at is not None:
            expires = ban.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires <= now:
                ban.status = "expired"
                continue
        return ban
    db.commit()
    return None

@app.get("/api/v1/health")
def health():
    return {"ok": True, "service": "Community Trouble Register", "api_version": "v1"}

@app.get("/api/v1/players/{steamid}/status")
def player_status(steamid: str, db: Session = Depends(get_db)):
    if not valid_steamid(steamid):
        raise HTTPException(status_code=422, detail="Expected a SteamID64")
    pending = db.scalar(select(func.count(Report.id)).where(Report.steamid == steamid, Report.status == "pending")) or 0
    confirmed_reports = db.scalar(select(func.count(Report.id)).where(Report.steamid == steamid, Report.status == "confirmed")) or 0
    ban = active_global_ban(db, steamid)
    if ban:
        return {
            "steamid": steamid,
            "status": "temporarily_banned" if ban.expires_at else "permanently_banned",
            "globally_banned": True,
            "ban": {
                "id": ban.id,
                "reason": ban.reason,
                "expires_at": ban.expires_at.isoformat() if ban.expires_at else None,
                "issuer": ban.issuer,
            },
            "pending_reports": pending,
            "confirmed_reports": confirmed_reports,
        }
    return {
        "steamid": steamid,
        "status": "no_active_record" if pending == 0 and confirmed_reports == 0 else ("reported" if pending else "confirmed_record"),
        "globally_banned": False,
        "pending_reports": pending,
        "confirmed_reports": confirmed_reports,
    }

@app.get("/api/v1/players/{steamid}")
def player_record(steamid: str, db: Session = Depends(get_db)):
    if not valid_steamid(steamid):
        raise HTTPException(status_code=422, detail="Expected a SteamID64")
    reports = db.scalars(select(Report).where(Report.steamid == steamid, Report.status == "confirmed").order_by(Report.created_at.desc())).all()
    ban = active_global_ban(db, steamid)
    return {"steamid": steamid, "records": [
        {"id": r.id, "reason": r.reason, "details": r.details, "status": r.status,
         "created_at": r.created_at.isoformat(), "server": r.server.name}
        for r in reports
    ], "active_global_ban": None if not ban else {
        "id": ban.id, "reason": ban.reason, "issuer": ban.issuer,
        "created_at": ban.created_at.isoformat(),
        "expires_at": ban.expires_at.isoformat() if ban.expires_at else None,
    }}

@app.get("/api/v1/servers")
def list_servers(db: Session = Depends(get_db)):
    servers = db.scalars(select(GameServer).where(GameServer.verified == True, GameServer.active == True).order_by(GameServer.name)).all()
    return [{"id": s.id, "name": s.name, "game_id": s.game_id, "description": s.description} for s in servers]

@app.post("/api/v1/servers/register")
def register_server(payload: dict, db: Session = Depends(get_db), x_setup_token: str | None = Header(default=None)):
    expected = os.getenv("SETUP_TOKEN", "replace-with-a-long-random-setup-token")
    if not x_setup_token or not secrets.compare_digest(x_setup_token, expected):
        raise HTTPException(status_code=403, detail="Valid X-Setup-Token required")
    name = str(payload.get("name", "")).strip()[:120]
    address = str(payload.get("address", "")).strip()[:255]
    if not name or not address:
        raise HTTPException(status_code=422, detail="name and address are required")
    registration_id = str(payload.get("registration_id", "")).strip()[:80]
    if registration_id:
        existing = db.scalar(select(GameServer).where(GameServer.registration_id == registration_id))
        if existing:
            existing.name = name
            existing.address = address
            db.add(AuditEvent(actor=f"server:{existing.id}", action="server_registration_refresh", target=str(existing.id), note="Idempotent registration"))
            db.commit()
            db.refresh(existing)
            return {
                "status": existing.verification_status or ("verified" if existing.verified else "pending_verification"),
                "server_id": existing.id,
                "api_key": None,
                "warning": "Use the credential previously issued to this server.",
            }
    key = new_api_key()
    pairing_code = secrets.token_urlsafe(18)
    if not registration_id:
        registration_id = "ctr-" + secrets.token_urlsafe(24)
    server = GameServer(name=name, address=address, game_id=str(payload.get("game_id", "4000"))[:32],
                        description=str(payload.get("description", ""))[:2000], api_key_hash=hash_key(key),
                        registration_id=registration_id, pairing_token_hash=hash_key(pairing_code),
                        verification_status="pending_verification")
    db.add(server)
    db.commit()
    db.refresh(server)
    db.add(AuditEvent(actor=f"server:{server.id}", action="server_registered", target=str(server.id), note="Pending verification"))
    db.commit()
    return {"status": "pending_verification", "server_id": server.id, "api_key": key, "pairing_code": pairing_code,
            "registration_id": server.registration_id,
            "warning": "Save this key now; it cannot be retrieved later. Admin verification is required before voting."}

@app.post("/api/v1/servers/heartbeat")
def server_heartbeat(payload: dict, server: GameServer = Depends(get_server), db: Session = Depends(get_db)):
    name = str(payload.get("server_name", "")).strip()[:120]
    if name:
        server.name = name
    server.last_heartbeat = utcnow()
    server.player_count = max(0, min(int(payload.get("player_count", 0) or 0), 100000))
    server.max_player_count = max(0, min(int(payload.get("max_player_count", 0) or 0), 100000))
    server.gmod_version = str(payload.get("gmod_version", ""))[:100]
    db.add(AuditEvent(actor=f"server:{server.id}", action="server_heartbeat", target=str(server.id),
                      note=f"{server.player_count}/{server.max_player_count}"))
    db.commit()
    return {
        "ok": True,
        "server_id": server.id,
        "verification_status": server.verification_status,
        "last_seen": server.last_heartbeat.isoformat(),
    }

@app.post("/api/v1/reports")
def create_report(payload: dict, server: GameServer = Depends(get_server), db: Session = Depends(get_db)):
    steamid = str(payload.get("steamid", ""))
    reason = str(payload.get("reason", "")).strip()[:80]
    details = str(payload.get("details", "")).strip()[:5000]
    evidence_url = str(payload.get("evidence_url", "")).strip()[:500]
    if not valid_steamid(steamid):
        raise HTTPException(status_code=422, detail="Expected a SteamID64")
    if not reason:
        raise HTTPException(status_code=422, detail="reason is required")
    report = Report(steamid=steamid, reason=reason, details=details, evidence_url=evidence_url, server_id=server.id)
    db.add(report)
    db.add(AuditEvent(actor=f"server:{server.id}", action="report_created", target=steamid, note=reason))
    db.commit()
    db.refresh(report)
    return {"status": "pending_review", "report_id": report.id}

@app.post("/api/v1/votes")
def vote(payload: dict, server: GameServer = Depends(get_server), db: Session = Depends(get_db)):
    if not server.verified:
        raise HTTPException(status_code=403, detail="Server must be verified before voting")
    report_id = payload.get("report_id")
    decision = str(payload.get("decision", "approve"))
    if decision not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="decision must be approve or reject")
    report = db.get(Report, report_id) if isinstance(report_id, int) else None
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.server_id == server.id:
        raise HTTPException(status_code=409, detail="A reporting server cannot vote on its own report")
    existing = db.scalar(select(Vote).where(Vote.report_id == report.id, Vote.server_id == server.id))
    if existing:
        raise HTTPException(status_code=409, detail="This server has already voted")
    db.add(Vote(report_id=report.id, server_id=server.id, decision=decision))
    db.add(AuditEvent(actor=f"server:{server.id}", action="vote_cast", target=str(report.id), note=decision))
    db.commit()
    return {"status": "vote_recorded", "report_id": report.id, "decision": decision,
            "note": "This MVP records votes; a moderator must confirm the report."}

@app.post("/api/v1/moderation/bans")
def create_global_ban(
    payload: dict,
    request: Request,
    x_api_key: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    admin = get_admin(request, db)
    server = None
    if not admin and x_api_key:
        server = db.scalar(select(GameServer).where(GameServer.api_key_hash == hash_key(x_api_key)))
        if not server or not server.active:
            raise HTTPException(status_code=403, detail="Invalid or inactive API key")
    if admin:
        if not admin.is_admin:
            raise HTTPException(status_code=403, detail="Global-ban permission required")
        issuer = admin.username
        source_server_id = None
    else:
        if not server:
            raise HTTPException(status_code=401, detail="Admin login or server API key required")
        if not server.verified or not server.active:
            raise HTTPException(status_code=403, detail="Server must be verified and active")
        if not server.can_issue_global_bans:
            raise HTTPException(status_code=403, detail="This server lacks global-ban permission")
        issuer = str(payload.get("actor", "")).strip()[:100]
        if not issuer:
            raise HTTPException(status_code=422, detail="actor is required")
        source_server_id = server.id

    steamid = str(payload.get("steamid", ""))
    reason = str(payload.get("reason", "")).strip()
    if not valid_steamid(steamid):
        raise HTTPException(status_code=422, detail="Expected a SteamID64")
    if len(reason) < 10:
        raise HTTPException(status_code=422, detail="A meaningful reason of at least 10 characters is required")
    duration, expires_at = parse_ban_expiry(str(payload.get("duration", "permanent")))

    existing = active_global_ban(db, steamid)
    if existing:
        if existing.reason == reason and existing.expires_at == expires_at:
            return {"status": "already_active", "ban_id": existing.id, "confirmed": True}
        existing.status = "superseded"
        db.add(existing)

    ban = GlobalBan(
        steamid=steamid,
        reason=reason,
        duration=duration,
        expires_at=expires_at,
        status="active",
        issuer=issuer,
        source_server_id=source_server_id,
    )
    db.add(ban)
    db.add(AuditEvent(actor=issuer, action="global_ban_created", target=steamid,
                      note=f"{duration}: {reason}; server={source_server_id or 'admin'}"))
    db.commit()
    db.refresh(ban)
    return {"status": "confirmed", "confirmed": True, "ban_id": ban.id, "expires_at": ban.expires_at.isoformat() if ban.expires_at else None}

@app.post("/api/v1/moderation/bans/{ban_id}/revoke")
def revoke_global_ban(ban_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    ban = db.get(GlobalBan, ban_id)
    if not ban:
        raise HTTPException(status_code=404, detail="Ban not found")
    if ban.status != "active":
        return {"status": ban.status, "ban_id": ban.id, "revoked": True}
    ban.status = "revoked"
    ban.revoked_at = utcnow()
    ban.revoked_by = admin.username
    db.add(AuditEvent(actor=admin.username, action="global_ban_revoked", target=ban.steamid,
                      note="Revoked by authorized administrator"))
    db.commit()
    return {"status": "revoked", "ban_id": ban.id, "revoked": True}

@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(Report.id)).where(Report.status == "confirmed")) or 0
    servers = db.scalar(select(func.count(GameServer.id)).where(GameServer.verified == True, GameServer.active == True)) or 0
    return (BASE / "templates" / "index.html").read_text().replace("{{TOTAL}}", f"{total:,}").replace("{{SERVERS}}", f"{servers:,}")

@app.get("/search", response_class=HTMLResponse)
def search_page():
    return (BASE / "templates" / "search.html").read_text()

@app.get("/login", response_class=HTMLResponse)
def login_page():
    return (BASE / "templates" / "login.html").read_text()

@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == username))
    if not user or not user.is_admin or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    response = RedirectResponse("/admin", status_code=303)
    response.set_cookie("ctr_admin", _cookie_signer().dumps(str(user.id)), httponly=True, secure=os.getenv("COOKIE_SECURE", "0") == "1",
                        samesite="strict", max_age=8 * 60 * 60)
    return response

@app.post("/logout")
def logout():
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("ctr_admin")
    return response

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    servers = db.scalars(select(GameServer).order_by(GameServer.created_at.desc())).all()
    reports = db.scalars(select(Report).order_by(Report.created_at.desc()).limit(100)).all()
    bans = db.scalars(select(GlobalBan).order_by(GlobalBan.created_at.desc()).limit(100)).all()
    server_rows = "".join(
        f"<tr><td>{s.id}</td><td>{s.name}</td><td>{s.address}</td>"
        f"<td>{s.verification_status}<br>{s.last_heartbeat.isoformat() if s.last_heartbeat else 'Never'}"
        f"<br>{s.player_count}/{s.max_player_count}</td>"
        f"<td><form method='post' action='/admin/servers/{s.id}/verify'><button>{'Unverify' if s.verified else 'Verify'}</button></form>"
        f"<form method='post' action='/admin/servers/{s.id}/suspend'><button>{'Reactivate' if not s.active else 'Suspend'}</button></form>"
        f"<form method='post' action='/admin/servers/{s.id}/rotate'><button>Rotate key</button></form>"
        f"<form method='post' action='/admin/servers/{s.id}/global-ban-permission'><select name='enabled'><option value='true'>Allow global bans</option><option value='false'>Disable global bans</option></select><button>Save</button></form></td></tr>"
        for s in servers
    )
    report_rows = "".join(
        f"<tr><td>{r.id}</td><td>{r.steamid}</td><td>{r.reason}</td><td>{r.status}</td>"
        f"<td><form method='post' action='/admin/reports/{r.id}/status'><select name='status'><option>pending</option><option>confirmed</option><option>rejected</option></select><button>Save</button></form></td></tr>"
        for r in reports
    )
    ban_rows = "".join(
        f"<tr><td>{b.id}</td><td>{b.steamid}</td><td>{b.reason}</td><td>{b.status}</td>"
        f"<td>{b.issuer}</td><td>{b.expires_at.isoformat() if b.expires_at else 'Permanent'}</td>"
        f"<td>{'' if b.status != 'active' else f'<form method=\\\"post\\\" action=\\\"/api/v1/moderation/bans/{b.id}/revoke\\\"><input name=\\\"reason\\\" maxlength=500 placeholder=\\\"Reason\\\"><button>Revoke</button></form>'}</td></tr>"
        for b in bans
    )
    template = (BASE / "templates" / "admin.html").read_text()
    return (template
            .replace("{{SERVERS}}", server_rows or "<tr><td colspan='5'>No servers registered</td></tr>")
            .replace("{{REPORTS}}", report_rows or "<tr><td colspan='5'>No reports yet</td></tr>")
            .replace("{{BANS}}", ban_rows or "<tr><td colspan='7'>No global bans yet</td></tr>"))

@app.post("/admin/servers/{server_id}/verify")
def verify_server(server_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    server = db.get(GameServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    server.verified = not server.verified
    server.verification_status = "verified" if server.verified else "pending_verification"
    db.add(AuditEvent(actor=admin.username, action="server_verification_changed", target=str(server.id), note=server.verification_status))
    db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/api/v1/admin/servers/{server_id}/verify")
def verify_server_api(server_id: int, request: Request, payload: dict, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    server = db.get(GameServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    verify = bool(payload.get("verified", True))
    server.verified = verify
    server.verification_status = "verified" if verify else "pending_verification"
    db.add(AuditEvent(actor=admin.username, action="server_verification_changed", target=str(server.id), note=server.verification_status))
    db.commit()
    return {"server_id": server.id, "verification_status": server.verification_status}

@app.post("/admin/servers/{server_id}/suspend")
def suspend_server(server_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    server = db.get(GameServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    server.active = not server.active
    server.verification_status = "suspended" if not server.active else ("verified" if server.verified else "pending_verification")
    db.add(AuditEvent(actor=admin.username, action="server_access_changed", target=str(server.id),
                      note="active" if server.active else "suspended"))
    db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/servers/{server_id}/rotate")
def rotate_server_key(server_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    server = db.get(GameServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    key = new_api_key()
    server.api_key_hash = hash_key(key)
    db.add(AuditEvent(actor=admin.username, action="server_credentials_rotated", target=str(server.id), note="Previous credential revoked"))
    db.commit()
    return {"status": "rotated", "server_id": server.id, "api_key": key,
            "warning": "Save this key now. It cannot be retrieved later."}

@app.post("/admin/servers/{server_id}/global-ban-permission")
def set_server_global_ban_permission(server_id: int, request: Request, enabled: str = Form(...), db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    server = db.get(GameServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    server.can_issue_global_bans = enabled.lower() == "true"
    db.add(AuditEvent(actor=admin.username, action="server_global_ban_permission_changed", target=str(server.id),
                      note=str(server.can_issue_global_bans)))
    db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/reports/{report_id}/status")
def set_report_status(report_id: int, request: Request, status: str = Form(...), db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    if status not in ("pending", "confirmed", "rejected"):
        raise HTTPException(status_code=422, detail="Invalid status")
    report = db.get(Report, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    report.status = status
    db.add(AuditEvent(actor=admin.username, action="report_status_changed", target=str(report.id), note=status))
    db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.get("/api/v1/admin/audit")
def audit_log(request: Request, db: Session = Depends(get_db)):
    require_admin(request, db)
    events = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(200)).all()
    return [{"id": e.id, "actor": e.actor, "action": e.action, "target": e.target,
             "note": e.note, "created_at": e.created_at.isoformat()} for e in events]
