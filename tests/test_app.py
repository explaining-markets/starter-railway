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


def test_signed_test_event_submits_neutral_prediction(monkeypatch) -> None:
    """A TEST delivery round-trips: the handler submits a 0.5 prediction for
    the synthetic event (so the portal test can verify the submit path), then
    ACKs 200. A submit failure must still ACK."""
    import base64
    import hmac
    import json
    import time
    from hashlib import sha256

    secret = "whsec_" + base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
    monkeypatch.setenv("EM_API_KEY", "test-key")
    monkeypatch.setenv("EM_WEBHOOK_SECRET", secret)

    payload = {
        "id": "evt_test_abc",
        "event_id": "test_abc",
        "event_type": "TEST",
        "focal_assets": [
            {"identifier_type": "TICKER", "identifier_value": "TEST"}
        ],
        "prediction_deadline": "2099-01-01T00:00:00+00:00",
    }
    raw_body = json.dumps(payload).encode()
    ts = int(time.time())
    key = base64.urlsafe_b64decode(secret[len("whsec_"):] + "==")
    signed = f"{payload['id']}.{ts}.".encode() + raw_body
    signature = "v1," + base64.b64encode(
        hmac.new(key, signed, sha256).digest()
    ).decode()
    headers = {
        "webhook-id": payload["id"],
        "webhook-timestamp": str(ts),
        "webhook-signature": signature,
    }

    submitted: list[dict] = []

    def fake_submit(*, event_id, predictions, config):
        submitted.append({"event_id": event_id, "predictions": predictions})
        return {"accepted": True}

    import app as app_module

    monkeypatch.setattr(app_module, "submit_predictions", fake_submit)
    app_module._seen_webhooks.clear()

    client = TestClient(app)
    resp = client.post("/", content=raw_body, headers=headers)
    assert resp.status_code == 200
    assert submitted == [
        {
            "event_id": "test_abc",
            "predictions": [
                {"identifier_value": "TEST", "predicted_percentile": 0.5}
            ],
        }
    ]

    # A submit failure must not fail the ACK — the portal reports the missing
    # prediction; the delivery itself succeeded.
    def broken_submit(**kwargs):
        raise RuntimeError("api down")

    monkeypatch.setattr(app_module, "submit_predictions", broken_submit)
    app_module._seen_webhooks.clear()
    resp = client.post("/", content=raw_body, headers=headers)
    assert resp.status_code == 200
