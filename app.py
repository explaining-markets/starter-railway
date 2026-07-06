"""Railway deployment for the Explaining Markets starter.

This is plumbing — you shouldn't need to edit it. It defines a small FastAPI app
that Railway runs as a persistent, public web service:

    GET  /    health check (Railway's healthcheckPath)
    POST /    receive a signed event, verify, predict, submit
              (POST /competition/webhook is kept as an alias of the same handler)

The webhook is served at the root path on purpose: the URL `railway domain`
prints *is* your webhook URL — paste it into the portal as-is, nothing to append.

Deploy:    railway up
Dev/local: uv run uvicorn app:app --reload

The webhook handler is synchronous: it verifies the signature, runs your
`predict()` from predict.py, submits the result, and only then ACKs with 200.
That's safe because your per-event deadline starts when you ACK 200 — so you've
always submitted before the clock starts. Deliveries are deduped on the
`Webhook-Id` header (the server retries on 5xx/timeout, so the same event can
arrive more than once).
"""

import os

from dotenv import load_dotenv

load_dotenv()  # local runs read .env; on Railway, variables come from the service

from fastapi import FastAPI, Request, Response

from explaining_markets import WebhookVerificationError, verify_webhook
from explaining_markets.client import submit_predictions
from explaining_markets.config import Config
from explaining_markets.event_utils import is_test, log_deadline
from predict import predict

app = FastAPI(title="Explaining Markets starter")

# In-memory idempotency cache keyed on the Webhook-Id header. It resets on
# restart/redeploy, which is fine for a starter — the server's retry window is
# short. For durable dedupe options, see docs/advanced.md.
_seen_webhooks: set[str] = set()


@app.get("/")
def health() -> dict:
    return {"ok": True, "service": "explaining-markets-starter"}


@app.post("/")
@app.post("/competition/webhook")  # alias, so an explicit-path URL also works
async def competition_webhook(request: Request) -> Response:
    config = Config.from_env()

    raw_body = await request.body()  # raw bytes — never request.json()
    try:
        event = verify_webhook(
            raw_body=raw_body,
            headers=request.headers,
            secret=config.webhook_secret,
        )
    except WebhookVerificationError as exc:
        return Response(content=str(exc), status_code=401)

    # Idempotency: the Webhook-Id header (== event["id"]) is stable across
    # retries. Skip anything we've already handled.
    webhook_id = event.get("id")
    if webhook_id and webhook_id in _seen_webhooks:
        return Response(status_code=200)

    # The portal's "Test Webhook" button sends a synthetic TEST event — ACK
    # it so the smoke test passes, but don't predict or submit.
    if is_test(event):
        if webhook_id:
            _seen_webhooks.add(webhook_id)
        return Response(status_code=200)

    log_deadline(event)
    predictions = predict(event)
    submit_predictions(
        event_id=event["event_id"],
        predictions=predictions,
        config=config,
    )

    if webhook_id:
        _seen_webhooks.add(webhook_id)
    return Response(status_code=200)


if __name__ == "__main__":
    import uvicorn

    # Railway injects PORT; bind to it (and 0.0.0.0) or healthchecks will fail.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
