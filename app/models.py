from datetime import datetime, timezone
from sqlalchemy import String, Integer, Boolean, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def utcnow():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class GameServer(Base):
    __tablename__ = "game_servers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str] = mapped_column(String(255))
    game_id: Mapped[str] = mapped_column(String(32), default="4000")
    description: Mapped[str] = mapped_column(Text, default="")
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    verification_status: Mapped[str] = mapped_column(String(32), default="pending_verification")
    pairing_token_hash: Mapped[str] = mapped_column(String(64), default="", index=True)
    registration_id: Mapped[str] = mapped_column(String(80), unique=True, index=True, default="")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    can_issue_global_bans: Mapped[bool] = mapped_column(Boolean, default=False)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    player_count: Mapped[int] = mapped_column(Integer, default=0)
    max_player_count: Mapped[int] = mapped_column(Integer, default=0)
    gmod_version: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reports: Mapped[list["Report"]] = relationship(back_populates="server")
    owner: Mapped[User | None] = relationship()

class Report(Base):
    __tablename__ = "reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    steamid: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str] = mapped_column(String(80), index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    evidence_url: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("game_servers.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    server: Mapped[GameServer] = relationship(back_populates="reports")
    votes: Mapped[list["Vote"]] = relationship(back_populates="report", cascade="all, delete-orphan")

class Vote(Base):
    __tablename__ = "votes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("reports.id"), index=True)
    server_id: Mapped[int] = mapped_column(ForeignKey("game_servers.id"))
    decision: Mapped[str] = mapped_column(String(16), default="approve")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    report: Mapped[Report] = relationship(back_populates="votes")
    __table_args__ = (UniqueConstraint("report_id", "server_id", name="uq_vote_server_report"),)

class GlobalBan(Base):
    __tablename__ = "global_bans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    steamid: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str] = mapped_column(String(500))
    duration: Mapped[str] = mapped_column(String(32), default="permanent")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    issuer: Mapped[str] = mapped_column(String(100))
    source_server_id: Mapped[int | None] = mapped_column(ForeignKey("game_servers.id"), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(255), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
