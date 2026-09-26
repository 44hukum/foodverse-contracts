# Contract Signing v1 — Specification

Ticket: FVR-5
Status: Draft for review
Owner: Foodverse platform team

## 1. Goal

An internal Foodverse tool that lets an admin send an onboarding contract (a
PDF) to a single signer at a hotel or restaurant, lets that signer sign it
from a unique link without creating an account, and produces a tamper-evident
signed PDF with a full audit trail of everything that happened to the
contract.

v1 is deliberately small. It must be correct, auditable, and boring before it
is convenient.

## 2. Non-goals for v1

Explicitly out of scope. Do not build these, and do not design v1 in a way
that forecloses them either.

- Multi-signer ordering (sequential or parallel signing by several people).
- Reminder emails, nudges, or scheduled re-sends.
- A template builder or any in-app document editing. The admin uploads a
  finished PDF.
- Form fields inside the PDF (dates, initials, checkboxes placed by the
  admin). v1 stamps a signature block and a certificate page only.
- Signer accounts, signer login, or signer dashboards.
- Counter-signature by Foodverse.
- Qualified / advanced electronic signatures under eIDAS or equivalent. v1
  produces a simple electronic signature with evidence.
- Webhooks or public API for third parties.
- Bulk send.

## 3. Actors

- **Admin**: an authenticated Foodverse employee using the internal web app.
  Admin authentication is provided by the internal auth layer and is
  represented in the API as a bearer token. Every admin request carries an
  `admin_id` that is recorded in the audit log.
- **Signer**: the hotel or restaurant representative. Unauthenticated. Their
  only credential is the unguessable link they received by email.
- **System**: background jobs (expiry sweep) and the API itself when it acts
  on its own (e.g. hashing the final PDF).

## 4. User flow

1. **Admin creates a contract.** In the web app the admin uploads a PDF, gives
   the contract a title, and enters the signer's name and email. The backend
   stores the PDF in object storage, computes its SHA-256, creates a
   `contracts` row in status `draft` and a `signers` row, and writes a
   `contract.created` event.
2. **Admin sends the link.** The admin clicks "Send". The backend generates a
   signing token, stores only its hash, sets `expires_at`, emails the signer
   a link of the form `{WEB_BASE_URL}/sign/{token}`, moves the contract to
   `sent`, and writes `contract.sent`.
3. **Signer opens the link.** The web app loads the public contract endpoint
   with the token. The backend validates the token, returns contract metadata
   plus a short-lived signed URL to the original PDF, moves the contract from
   `sent` to `viewed` on first successful load, and writes `link.viewed`
   (every load, not just the first).
4. **Signer reviews the PDF** in the browser.
5. **Signer signs.** The signer types their full name, draws a signature on a
   canvas, and ticks a consent checkbox ("I agree to sign this document
   electronically and I understand this is legally binding"). The web app
   submits all three to the public signature endpoint.
6. **Backend stamps the PDF.** In one transaction-like unit of work the
   backend:
   1. Re-validates the token and that the contract is `sent` or `viewed`.
   2. Downloads the original PDF from storage and verifies its SHA-256
      matches the stored value.
   3. Appends a signature block (drawn signature image, typed name, UTC
      timestamp) to the last page, or to a new page if there is no room.
   4. Appends a **certificate page** containing: contract id, title, signer
      name and email, signing timestamp (UTC), signer IP, signer user agent,
      the SHA-256 of the original PDF, the token's creation and expiry times,
      and a note that the audit log is held by Foodverse.
   5. Computes the SHA-256 of the resulting PDF and stores the PDF under a
      new object key.
   6. Updates the contract to `signed` with `signed_at`, `final_pdf_key`,
      `final_pdf_sha256`, and records the signature data on the signer.
   7. Invalidates the token (single use).
   8. Writes `contract.signed`.
   If any step fails the contract stays in its previous status and nothing
   is stored; the signer sees an error and can retry with the same link.
7. **Notifications.** The backend emails the signer a copy of the signed PDF
   (attached, plus the SHA-256 printed in the email body) and emails the
   admin who created the contract that it was signed. Email failures are
   logged as events and do not roll back the signature.
8. **Admin downloads.** The admin can request a download link for the
   original or the signed PDF at any time. The backend returns a short-lived
   signed URL and writes `pdf.downloaded`.

### Failure and edge paths

- Link opened after `expires_at`: the backend marks the contract `expired`
  (if it was `sent` or `viewed`), writes `contract.expired`, and returns
  `410 link_expired`. The admin can send a fresh link, which returns the
  contract to `sent`.
- Link opened after signing: `410 link_used`. The page tells the signer the
  document is already signed and to check their email for the copy.
- Link opened after cancellation: `410 contract_cancelled`.
- Unknown or malformed token: `404 not_found`. The response is identical
  whether the token never existed or was rotated, to avoid leaking
  information.
- Admin re-sends while `sent` or `viewed`: a new token is issued, the old one
  is invalidated immediately, `expires_at` is reset, and `link.resent` is
  written. Status is set back to `sent`.
- Admin cancels while `draft`, `sent`, or `viewed`: status becomes
  `cancelled`, the token is invalidated, `contract.cancelled` is written.
  `signed` and `expired` contracts cannot be cancelled (`409 invalid_state`).

## 5. Statuses and transitions

| Status      | Meaning                                                              |
|-------------|----------------------------------------------------------------------|
| `draft`     | Created, PDF stored, no link sent yet.                               |
| `sent`      | A live signing link exists and has not been opened.                  |
| `viewed`    | The signer has opened the link at least once.                        |
| `signed`    | Signature submitted, final PDF stored and hashed. Terminal.          |
| `expired`   | The link passed `expires_at` before signing. Recoverable by re-send. |
| `cancelled` | Admin cancelled. Terminal.                                           |

Allowed transitions:

```
draft     -> sent        (admin: send)
draft     -> cancelled   (admin: cancel)
sent      -> viewed      (signer: first open)
sent      -> sent        (admin: re-send, token rotated)
sent      -> signed      (signer: submit; possible if the client skipped GET)
sent      -> expired     (system: expiry)
sent      -> cancelled   (admin: cancel)
viewed    -> signed      (signer: submit)
viewed    -> sent        (admin: re-send, token rotated)
viewed    -> expired     (system: expiry)
viewed    -> cancelled   (admin: cancel)
expired   -> sent        (admin: re-send)
```

Any other transition is rejected with `409 invalid_state`. Status changes are
made with a conditional `UPDATE ... WHERE status IN (...)` so that concurrent
requests cannot double-sign or sign a cancelled contract.

Expiry is evaluated both lazily (on any public access) and by a periodic
sweep job that runs at least every 15 minutes so that the admin list is
accurate without waiting for the signer to click.

## 6. Data model

All tables use UUIDv4 primary keys, `timestamptz` timestamps in UTC, and are
managed by Alembic migrations. Emails are stored as entered but compared
case-insensitively.

### `contracts`

| Column               | Type          | Notes                                                       |
|----------------------|---------------|-------------------------------------------------------------|
| `id`                 | uuid PK       |                                                             |
| `title`              | text          | 1–200 chars, shown to signer.                               |
| `status`             | text          | One of the six statuses. Check constraint.                  |
| `created_by`         | text          | Admin id from the auth layer.                               |
| `original_pdf_key`   | text          | Object key of the uploaded PDF.                             |
| `original_pdf_sha256`| char(64)      | Hex, computed at upload.                                    |
| `original_pdf_size`  | integer       | Bytes.                                                      |
| `final_pdf_key`      | text null     | Set when signed.                                            |
| `final_pdf_sha256`   | char(64) null | Hex, computed over the stamped PDF. Set when signed.        |
| `sent_at`            | timestamptz null | Time of the most recent send.                            |
| `first_viewed_at`    | timestamptz null |                                                          |
| `signed_at`          | timestamptz null |                                                          |
| `expires_at`         | timestamptz null | Expiry of the current link.                              |
| `cancelled_at`       | timestamptz null |                                                          |
| `created_at`         | timestamptz   |                                                             |
| `updated_at`         | timestamptz   |                                                             |

### `signers`

One row per contract in v1. Kept as its own table so multi-signer can be
added later without a migration of historic data.

| Column                 | Type            | Notes                                                        |
|------------------------|-----------------|--------------------------------------------------------------|
| `id`                   | uuid PK         |                                                              |
| `contract_id`          | uuid FK, unique | Unique in v1 (one signer per contract).                      |
| `name`                 | text            | As entered by the admin.                                     |
| `email`                | text            | As entered by the admin.                                     |
| `token_hash`           | char(64) null   | SHA-256 hex of the current signing token. Null when no live link. |
| `token_created_at`     | timestamptz null|                                                              |
| `token_invalidated_at` | timestamptz null| Set on sign, cancel, or re-send.                             |
| `typed_name`           | text null       | Name typed by the signer at signing.                         |
| `signature_image_key`  | text null       | Object key of the drawn signature PNG.                       |
| `consent_given_at`     | timestamptz null|                                                              |
| `signed_ip`            | inet null       |                                                              |
| `signed_user_agent`    | text null       |                                                              |
| `created_at`           | timestamptz     |                                                              |
| `updated_at`           | timestamptz     |                                                              |

The raw token is never stored. Lookup is by `token_hash = sha256(token)`.

### `contract_events` (append-only audit log)

| Column        | Type        | Notes                                                                  |
|---------------|-------------|------------------------------------------------------------------------|
| `id`          | bigserial PK| Monotonic, gives a total order per contract.                           |
| `contract_id` | uuid FK     | Indexed.                                                               |
| `event_type`  | text        | See list below.                                                        |
| `actor_type`  | text        | `admin`, `signer`, or `system`.                                        |
| `actor_id`    | text null   | Admin id for admin actions; signer id for signer actions; null for system. |
| `occurred_at` | timestamptz | Server time.                                                           |
| `ip`          | inet null   | Client IP (X-Forwarded-For resolved by the API, first trusted hop).    |
| `user_agent`  | text null   |                                                                        |
| `metadata`    | jsonb       | Event-specific payload, e.g. `{"from_status": "sent", "to_status": "viewed"}`. Never contains the raw token or the signature image. |

Event types in v1:

`contract.created`, `contract.sent`, `link.resent`, `link.viewed`,
`contract.signed`, `contract.expired`, `contract.cancelled`,
`pdf.downloaded`, `notification.sent`, `notification.failed`.

Rules:

- Rows are inserted only. The application database role has `INSERT` and
  `SELECT` on this table and **no** `UPDATE` or `DELETE` grant. A migration
  also adds a trigger that raises on `UPDATE` or `DELETE` as a second line of
  defence.
- Every status change writes exactly one event in the same transaction as
  the status change.
- Events are returned to admins in `GET /admin/contracts/{id}` ordered by
  `id` ascending.

### Object storage layout

Bucket is private. No public-read ACLs, ever.

```
contracts/{contract_id}/original.pdf
contracts/{contract_id}/signed.pdf
contracts/{contract_id}/signature.png
```

## 7. Security

- **Tokens.** 32 bytes from a CSPRNG (`secrets.token_bytes(32)`), encoded
  base64url without padding (43 characters). Only `sha256(token)` is stored.
  Tokens never appear in logs, events, or error messages. The public API
  accepts the token in the path; the web app must not forward it to any
  third-party script or analytics.
- **Expiry.** Every link has `expires_at`, default 14 days after send
  (`SIGNING_LINK_TTL_DAYS`), configurable per send between 1 and 30 days.
  Expired links fail closed.
- **Single use.** A token is invalidated the moment a signature is accepted,
  when the admin cancels, and when a new link is sent. Repeated reads of the
  contract before signing are allowed (the signer may refresh or come back
  later); it is the signing action that is single use.
- **Integrity.** SHA-256 of the original PDF is computed at upload and
  re-verified before stamping. SHA-256 of the final PDF is computed after
  stamping, stored, returned in API responses, printed in the completion
  email, and shown in the admin UI. Anyone holding a copy can verify it
  against the stored hash.
- **Downloads.** PDFs are never served by the API and never at a stable URL.
  Every download goes through a pre-signed object storage URL with a TTL of
  `DOWNLOAD_URL_TTL_SECONDS` (default 300). Each admin download request writes
  a `pdf.downloaded` event.
- **Uploads.** Only `application/pdf`, checked by magic bytes as well as
  content type. Maximum size 20 MB. Rejected files are never written to
  storage.
- **Signature image.** PNG only, decoded and re-encoded server-side before
  stamping to strip any embedded payload, maximum 500 KB, maximum
  2000×1000 px.
- **Public endpoints.** Rate limited per IP and per token (e.g. 60 requests
  per minute per IP, 10 signature attempts per token). No CORS beyond the web
  app origin. Responses for unknown tokens are indistinguishable from rotated
  tokens.
- **Admin endpoints.** Require a valid bearer token from the internal auth
  layer. All admin actions record `admin_id` in `contract_events`.
- **Secrets.** All configuration through environment variables (see
  `.env.example`). No secrets in the repository, the OpenAPI file, or tests.
- **Transport.** HTTPS only. HSTS on the web app.
- **PII.** Signer name, email, IP, and user agent are personal data. They are
  needed for the audit trail and are kept for the life of the contract.
  Deletion or retention policy is an open question (see §10).

## 8. Notifications

Transactional email only, through the provider configured in `.env`.

| Trigger            | To     | Content                                                         |
|--------------------|--------|-----------------------------------------------------------------|
| `contract.sent`, `link.resent` | Signer | Title, who sent it, expiry date, the signing link.  |
| `contract.signed`  | Signer | Confirmation, signed PDF attached, SHA-256 in the body.         |
| `contract.signed`  | Admin (`created_by`) | Confirmation, link to the admin contract page.    |

Every send attempt writes `notification.sent` or `notification.failed` with
the recipient role (never the address) and provider message id in
`metadata`. Failures are surfaced in the admin UI; there is no automatic
retry in v1.

## 9. Interfaces

The HTTP contract is defined in `openapi.yaml` at the repo root and is the
source of truth. In summary:

Admin (`/api/v1/admin`, bearer auth):

- `POST /contracts` — multipart upload of PDF + title + signer.
- `GET /contracts` — paginated list, filterable by status.
- `GET /contracts/{contract_id}` — detail including signer and events.
- `POST /contracts/{contract_id}/send` — issue (or rotate) the signing link.
- `POST /contracts/{contract_id}/cancel` — cancel.
- `GET /contracts/{contract_id}/download` — short-lived signed URL for
  `original` or `signed`.

Public (`/api/v1/public`, token in path, rate limited):

- `GET /sign/{token}` — contract metadata plus short-lived URL to the PDF.
  Marks `viewed`.
- `POST /sign/{token}/signature` — submit typed name, drawn signature,
  consent. Returns the final hash and a short-lived download URL.

## 10. Decisions made and open questions

Decisions taken in this spec (change them here first if you disagree):

1. One signer per contract, but `signers` is a separate table for forward
   compatibility.
2. "Single use" applies to the signing action, not to viewing. Signers can
   reopen the link until they sign or it expires.
3. `GET /sign/{token}` has the side effect of marking `viewed`. Email link
   scanners fetch the web page, not the JSON API, so this is acceptable for
   v1. If it proves noisy, the frontend can call an explicit view endpoint.
4. Re-sending rotates the token and resets `expires_at`; the old link dies
   immediately.
5. Downloads return a JSON body with a signed URL rather than a 302, so the
   frontend can show the hash next to the link and so the URL never lands in
   browser history via a redirect.
6. The final PDF hash cannot be embedded in the PDF itself (it would change
   the hash). The certificate page carries the original PDF hash; the final
   hash lives in the database, the API, and the email.
7. Email failures after a successful signature do not roll back the
   signature. The signature is the legally meaningful event.

Open questions for the reviewer:

1. **Admin auth.** Which internal auth provider issues the bearer token, and
   what claim carries the admin id? The spec assumes an opaque `admin_id`
   string.
2. **Data retention.** How long do we keep signed PDFs, signature images, and
   audit rows? Is there a GDPR erasure path for a signer who never signed?
3. **Legal wording.** The exact consent checkbox text and certificate page
   wording should come from legal. The spec uses placeholders.
4. **Timezone on the certificate page.** UTC only, or UTC plus the signer's
   browser timezone?
5. **Email provider.** SES, Postmark, SMTP relay? Affects `.env` keys and the
   attachment size limit (SES caps at 40 MB, Postmark at 10 MB).
6. **Rate limit numbers.** The figures in §7 are starting points.
7. **Should `expired` be reachable from `draft`?** Currently no: drafts have
   no link and never expire.
