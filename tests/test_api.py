import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_ctr.db")
os.environ.setdefault("ADMIN_USERNAME", "testadmin")
os.environ.setdefault("ADMIN_PASSWORD", "testpassword")
os.environ.setdefault("SETUP_TOKEN", "testsetup")
os.environ.setdefault("APP_SECRET", "test-secret")

test_db = Path("test_ctr.db")
if test_db.exists():
    test_db.unlink()

from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


def register_server(registration_id="ctr-test-1"):
    response = client.post(
        "/api/v1/servers/register",
        headers={"X-Setup-Token": "testsetup"},
        json={"name": "Test Server", "address": "127.0.0.1:27015", "registration_id": registration_id},
    )
    assert response.status_code == 200
    return response.json()


def test_server_registration_is_pending_and_idempotent():
    first = register_server()
    second = register_server(first["registration_id"])
    assert first["status"] == "pending_verification"
    assert second["server_id"] == first["server_id"]
    assert second["api_key"] is None


def test_player_status_and_global_ban_lifecycle():
    steamid = "76561198000000001"
    no_ban = client.get(f"/api/v1/players/{steamid}/status")
    assert no_ban.status_code == 200
    assert no_ban.json()["globally_banned"] is False

    login = client.post("/login", data={"username": "testadmin", "password": "testpassword"}, follow_redirects=False)
    assert login.status_code == 303

    ban = client.post(
        "/api/v1/moderation/bans",
        json={"steamid": steamid, "duration": "1d", "reason": "Confirmed repeated targeted harassment"},
        cookies=login.cookies,
    )
    assert ban.status_code == 200
    assert ban.json()["confirmed"] is True
    banned = client.get(f"/api/v1/players/{steamid}/status")
    assert banned.json()["globally_banned"] is True

    revoke = client.post(
        f"/api/v1/moderation/bans/{ban.json()['ban_id']}/revoke",
        cookies=login.cookies,
    )
    assert revoke.status_code == 200
    assert revoke.json()["revoked"] is True
    assert client.get(f"/api/v1/players/{steamid}/status").json()["globally_banned"] is False


def test_reports_do_not_create_global_bans():
    steamid = "76561198000000002"
    registration = register_server("ctr-test-report")
    response = client.post(
        "/api/v1/reports",
        headers={"X-API-Key": registration["api_key"]},
        json={"steamid": steamid, "reason": "Unreviewed allegation", "details": "Awaiting review"},
    )
    assert response.status_code == 200
    status = client.get(f"/api/v1/players/{steamid}/status")
    assert status.json()["globally_banned"] is False
    assert status.json()["pending_reports"] >= 1


def test_invalid_credential_and_steamid_are_rejected():
    assert client.get("/api/v1/players/not-a-steamid/status").status_code == 422
    heartbeat = client.post(
        "/api/v1/servers/heartbeat",
        headers={"X-API-Key": "ctr_invalid"},
        json={"server_name": "Invalid"},
    )
    assert heartbeat.status_code in (401, 403)
