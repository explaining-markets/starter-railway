"""The FastAPI app boots and guards the webhook route — fully offline.

Railway's healthcheck hits GET /; an unsigned POST must be rejected with 401
before anything downstream (predict, submission) runs.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import app


def test_health_ok() -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_unsigned_post_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("EM_API_KEY", "test-key")
    monkeypatch.setenv("EM_WEBHOOK_SECRET", "whsec_" + "A" * 43)
    client = TestClient(app)
    for path in ("/", "/competition/webhook"):
        resp = client.post(path, content=b"{}")
        assert resp.status_code == 401
