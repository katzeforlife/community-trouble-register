import os, re, secrets
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Header, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from dotenv import load_dotenv
from .db import Base, engine, get_db, SessionLocal
from .models import User, GameServer, Report, Vote, AuditEvent
from .security import hash_password, verify_password, new_api_key, hash_key

load_dotenv()
BASE = Path(__file__).resolve().parent
app = FastAPI(title="Community Trouble Register API", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")
Base.metadata.create_all(bind=engine)

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

@app.get("/api/v1/health")
def health():
    return {"ok": True, "service": "Community Trouble Register", "api_version": "v1"}

@app.get("/api/v1/players/{steamid}/status")
def player_status(steamid: str, db: Session = Depends(get_db)):
    if not valid_steamid(steamid):
        raise HTTPException(status_code=422, detail="Expected a SteamID64")
    reports = db.scalars(select(Report).where(Report.steamid == steamid, Report.status == "confirmed")).all()
    return {"steamid": steamid, "status": bool(reports), "confirmed_records": len(reports)}

@app.get("/api/v1/players/{steamid}")
def player_record(steamid: str, db: Session = Depends(get_db)):
    if not valid_steamid(steamid):
        raise HTTPException(status_code=422, detail="Expected a SteamID64")
    reports = db.scalars(select(Report).where(Report.steamid == steamid, Report.status.in_(["pending", "confirmed"])).order_by(Report.created_at.desc())).all()
    return {"steamid": steamid, "records": [
        {"id": r.id, "reason": r.reason, "details": r.details, "status": r.status,
         "created_at": r.created_at.isoformat(), "server": r.server.name}
        for r in reports
    ]}

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
    key = new_api_key()
    server = GameServer(name=name, address=address, game_id=str(payload.get("game_id", "4000"))[:32],
                        description=str(payload.get("description", ""))[:2000], api_key_hash=hash_key(key))
    db.add(server)
    db.commit()
    db.refresh(server)
    return {"status": "registered_pending_verification", "server_id": server.id, "api_key": key,
            "warning": "Save this key now; it cannot be retrieved later. Admin verification is required before voting."}

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
    server_rows = "".join(
        f"<tr><td>{s.id}</td><td>{s.name}</td><td>{s.address}</td><td>{'Verified' if s.verified else 'Pending'}</td>"
        f"<td><form method='post' action='/admin/servers/{s.id}/verify'><button>{'Unverify' if s.verified else 'Verify'}</button></form></td></tr>"
        for s in servers
    )
    report_rows = "".join(
        f"<tr><td>{r.id}</td><td>{r.steamid}</td><td>{r.reason}</td><td>{r.status}</td>"
        f"<td><form method='post' action='/admin/reports/{r.id}/status'><select name='status'><option>pending</option><option>confirmed</option><option>rejected</option></select><button>Save</button></form></td></tr>"
        for r in reports
    )
    template = (BASE / "templates" / "admin.html").read_text()
    return template.replace("{{SERVERS}}", server_rows or "<tr><td colspan='5'>No servers registered</td></tr>").replace("{{REPORTS}}", report_rows or "<tr><td colspan='5'>No reports yet</td></tr>")

@app.post("/admin/servers/{server_id}/verify")
def verify_server(server_id: int, request: Request, db: Session = Depends(get_db)):
    admin = require_admin(request, db)
    server = db.get(GameServer, server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    server.verified = not server.verified
    db.add(AuditEvent(actor=admin.username, action="server_verification_changed", target=str(server.id), note=str(server.verified)))
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
