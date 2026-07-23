# Advanced notes

The hero README keeps the path to a first deploy as short as possible. This file
collects everything intentionally left out of it.

## The webhook verifier is vendored

`src/explaining_markets/webhook_verification.py` is a verbatim copy of the
competition's reference verifier (stdlib-only, zero runtime dependencies). It's
vendored — not installed from PyPI — so the starter is self-contained.

If the competition later publishes the verifier as a package, you can delete the
vendored file and depend on the pinned package instead, importing
`verify_webhook` / `WebhookVerificationError` from there. The frozen test vectors
in `tests/test_vectors.json` will keep passing either way, since both
implementations pin to the same values.

## Credentials: local `.env` vs Railway Variables

Locally, `app.py` loads `.env` via `python-dotenv`, so runs and tests just work.
Deployed services read **Railway Variables** instead — Railway never sees your
local `.env`. The README's one-liner pushes every non-comment line of `.env` to
the linked service:

```bash
railway variable set $(grep -v '^#' .env | xargs)
```

Setting variables triggers a redeploy by default (add `--skip-deploys` to batch
several `set` calls). The dashboard equivalent is the service's **Variables** tab,
whose raw editor accepts pasted `KEY=value` lines — the same format the portal's
credentials dialog gives you.

## Webhook path and URL

The handler is registered on both `POST /` (primary) and `POST /competition/webhook`
(alias), so either URL works. We serve it at the root so the URL `railway domain`
prints *is* your webhook URL, with nothing to append.

`railway domain` mints a `https://<service>.up.railway.app` subdomain; run
`railway domain example.com` instead to attach a custom domain.

## How the build works

`railway.json` pins the [Railpack](https://railpack.com) builder, which detects
`pyproject.toml` + `uv.lock` and installs with `uv sync --locked --no-dev` — the
project itself (the `src/explaining_markets` package) is installed into the venv,
which is why `app.py` can import it in production. Two consequences:

- **Commit `uv.lock` and keep it in sync.** `--locked` fails the build if the
  lockfile has drifted from `pyproject.toml`; run `uv sync` after editing
  dependencies and commit the updated lockfile.
- The `dev` dependency group (pytest) is not installed in production.

The start command is `python app.py`, which binds `0.0.0.0:$PORT` — Railway
injects `PORT` and healthchecks `GET /` before routing traffic to a new deploy.

## Why synchronous (no queue) in v1

`app.py` verifies → predicts → submits → ACKs 200, all in one request. Your
per-event deadline starts when you ACK 200, so you've always submitted before the
clock starts. This is the simplest correct design.

If your `predict()` becomes slow (long LLM chains, multiple tools) and webhook
deliveries start timing out, move to a queue: ACK 200 immediately, push the
verified event onto a queue (e.g. a Railway Redis service), and process + submit
in a separate worker service. Keep the `Webhook-Id` dedupe guard — retries still
happen.

## Idempotency

Deliveries are deduped on the `Webhook-Id` header (equal to `event["id"]`) via an
in-memory set. The server retries on 5xx and timeout, so the same event can
arrive more than once; the dedupe guard makes reprocessing a no-op.

Unlike a database-backed store, the set resets on every restart or redeploy.
That's fine for the starter — the server's retry window is short, and duplicate
*submissions* are harmless anyway (the API tags them `accepted_duplicate` and
ignores them at scoring — only your first accepted POST counts). If you want dedupe that survives
restarts, add a Railway Redis or Postgres service and key on `Webhook-Id`.

## Not included by design

No Docker, Terraform, GitHub Actions, custom CLI, or multiple deployment modes —
Railway's Railpack builds, healthchecked deploys, and service variables cover the
starter. Add those only if your own setup needs them.
