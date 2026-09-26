# Signing links (FVR-7)

How a signing token lives and dies, and what an operator must keep in mind
because the token travels in a URL.

## Lifecycle

| Step | Who | What happens |
|------|-----|--------------|
| Send | admin, `POST /admin/contracts/{id}/send` | 32 CSPRNG bytes → 43-char base64url token. `signers.token_hash = sha256(token)`, `token_created_at = now`, `token_invalidated_at = null`, `contracts.expires_at = now + N days` (N = `expires_in_days` or `SIGNING_LINK_TTL_DAYS`, always 1..30). Status → `sent`. Event `contract.sent` (from `draft`/`expired`) or `link.resent` (from `sent`/`viewed`). The raw link is in this response only. |
| View | signer, `GET /public/sign/{token}` | Lookup by hash under a row lock. First open moves `sent` → `viewed`; every open writes `link.viewed` with IP and user agent in `contract_event_pii`. Returns a `DOWNLOAD_URL_TTL_SECONDS` signed URL to the original PDF. |
| Sign | signer, `POST /public/sign/{token}/signature` | Re-validates the token, checks the original's SHA-256, stamps and certifies the PDF, stores `signed.pdf` and `signature.png`, then in one transaction: `sent`/`viewed` → `signed`, signer fields (typed name, consent, IP, user agent), `token_invalidated_at = now`, event `contract.signed`. If anything fails nothing is stored and the link still works. |
| Expire | system, lazily on any public call | `expires_at` in the past and status `sent`/`viewed` → `expired`, event `contract.expired` (actor `system`), response `410 link_expired`. A periodic sweep is a separate issue. |
| Cancel | admin | Status → `cancelled`, `token_invalidated_at = now`, hash kept. |

## What the signer sees for a dead link

| Situation | Response |
|-----------|----------|
| Never issued, malformed, or rotated by a re-send | `404 not_found` (identical body in all three cases) |
| Past `expires_at`, or already `expired` | `410 link_expired` with `details.expired_at` |
| Contract already `signed` | `410 link_used` with `details.signed_at` |
| Contract `cancelled` | `410 contract_cancelled` |
| More than 60 public calls a minute from one IP, or more than 10 signature attempts a minute on one token | `429 rate_limited` with `Retry-After` |

The hash is kept after signing and cancelling so those links can be told
apart from unknown ones; a re-send overwrites it so the old link falls into
the 404 bucket.

## Operator notes

- **Access logs.** The token is the last path segment of `/api/v1/public/sign/...`.
  The API redacts that segment from its own error logs, but uvicorn's
  access log and any reverse proxy log would print it. Run uvicorn with
  `--no-access-log` in production, or configure the proxy to drop or hash
  the path for `/api/v1/public/sign/`.
- **Rate limiter state is per process.** With more than one API replica the
  limits apply per replica. Put a shared store behind `app.ratelimit` before
  scaling out.
- **Consent wording.** `CONSENT_TEXT_VERSION` must name a template in
  `app/services/consent.py`; the app refuses to start otherwise. Add a new
  version instead of editing an old one.
- **Email.** Sending currently returns `email_sent: false`; SMTP delivery of
  the link is wired in by the notifications issue. The admin copies the link
  from the send response in the meantime.
