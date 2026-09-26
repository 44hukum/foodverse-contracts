/**
 * MSW request handlers that implement the admin surface of openapi.yaml well
 * enough to run and test the web app without the backend. Shapes and error
 * codes follow the contract; behaviour follows SPEC.md §4–5 loosely.
 */
import { HttpResponse, http } from 'msw';
import type { DefaultBodyType, StrictRequest } from 'msw';
import { API_BASE_URL, MAX_PDF_BYTES } from '../config';
import type {
  ApiErrorBody,
  ContractDetail,
  ContractList,
  ContractStatus,
  ContractSummary,
  ErrorCode,
  LoginResponse,
  SendContractRequest,
  SendContractResponse,
} from '../api/types';
import { CONTRACT_STATUSES, SENDABLE_STATUSES } from '../api/types';
import { publicSigningHandlers } from '../sign/mocks/handlers';
import {
  MOCK_ACCESS_TOKEN,
  MOCK_ADMIN,
  MOCK_ADMIN_EMAIL,
  MOCK_ADMIN_PASSWORD,
  MOCK_TOKEN_TTL_SECONDS,
  db,
  fakeSha256,
} from './data';

const url = (path: string): string => `${API_BASE_URL}${path}`;

function error(
  status: number,
  code: ErrorCode,
  message: string,
  details?: Record<string, unknown>,
): HttpResponse<ApiErrorBody> {
  const body: ApiErrorBody = { error: { code, message } };
  if (details) body.error.details = details;
  return HttpResponse.json(body, { status });
}

function unauthorized(request: StrictRequest<DefaultBodyType>): HttpResponse<ApiErrorBody> | null {
  const header = request.headers.get('authorization');
  if (header !== `Bearer ${MOCK_ACCESS_TOKEN}`) {
    return error(401, 'unauthorized', 'A valid bearer token is required.');
  }
  return null;
}

function toSummary(contract: ContractDetail): ContractSummary {
  const { signer: _signer, events: _events, original_pdf_size: _size, ...summary } = contract;
  return summary;
}

function uuid(): string {
  return crypto.randomUUID();
}

/** 32 CSPRNG bytes as unpadded base64url (43 chars), generated fresh per send. */
function newSigningToken(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  let binary = '';
  for (const b of bytes) binary += String.fromCharCode(b);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function webBaseUrl(): string {
  return typeof window !== 'undefined' && window.location?.origin
    ? window.location.origin
    : 'http://localhost:5173';
}

function nowIso(): string {
  return new Date().toISOString();
}

function isStatus(value: string): value is ContractStatus {
  return (CONTRACT_STATUSES as readonly string[]).includes(value);
}

export const handlers = [
  // ---------------------------------------------------------- admin auth
  http.post(url('/admin/auth/login'), async ({ request }) => {
    let body: { email?: unknown; password?: unknown };
    try {
      body = (await request.json()) as { email?: unknown; password?: unknown };
    } catch {
      return error(400, 'bad_request', 'Request body is not valid JSON.');
    }
    if (typeof body.email !== 'string' || typeof body.password !== 'string') {
      return error(422, 'validation_error', 'One or more fields are invalid.', {
        fields: [{ field: 'email', message: 'Required.' }],
      });
    }
    if (body.password.length < 12) {
      return error(422, 'validation_error', 'One or more fields are invalid.', {
        fields: [{ field: 'password', message: 'Must be at least 12 characters.' }],
      });
    }
    if (body.email.toLowerCase() !== MOCK_ADMIN_EMAIL || body.password !== MOCK_ADMIN_PASSWORD) {
      return error(401, 'invalid_credentials', 'Email or password is incorrect.');
    }
    const response: LoginResponse = {
      access_token: MOCK_ACCESS_TOKEN,
      token_type: 'bearer',
      expires_in: MOCK_TOKEN_TTL_SECONDS,
      admin: { ...MOCK_ADMIN, last_login_at: nowIso() },
    };
    return HttpResponse.json(response, { status: 200 });
  }),

  http.get(url('/admin/auth/me'), ({ request }) => {
    return unauthorized(request) ?? HttpResponse.json(MOCK_ADMIN);
  }),

  // ------------------------------------------------------ admin contracts
  http.get(url('/admin/contracts'), ({ request }) => {
    const denied = unauthorized(request);
    if (denied) return denied;
    const params = new URL(request.url).searchParams;
    const statuses = params.getAll('status');
    if (statuses.some((s) => !isStatus(s))) {
      return error(422, 'validation_error', 'One or more fields are invalid.', {
        fields: [{ field: 'status', message: 'Unknown status.' }],
      });
    }
    const q = (params.get('q') ?? '').trim().toLowerCase();
    const limit = Math.min(Math.max(Number(params.get('limit') ?? 25) || 25, 1), 100);
    const cursor = params.get('cursor');
    const offset = cursor ? Number(atob(cursor)) || 0 : 0;

    let rows = [...db.contracts].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
    if (statuses.length) rows = rows.filter((c) => statuses.includes(c.status));
    if (q) {
      rows = rows.filter((c) =>
        [c.title, c.signer_name ?? '', c.signer_email ?? ''].some((v) => v.toLowerCase().includes(q)),
      );
    }
    const page = rows.slice(offset, offset + limit);
    const response: ContractList = {
      items: page.map(toSummary),
      next_cursor: offset + limit < rows.length ? btoa(String(offset + limit)) : null,
    };
    return HttpResponse.json(response);
  }),

  http.post(url('/admin/contracts'), async ({ request }) => {
    const denied = unauthorized(request);
    if (denied) return denied;
    let form: FormData;
    try {
      form = await request.formData();
    } catch {
      return error(400, 'bad_request', 'Expected multipart/form-data.');
    }
    const file = form.get('file');
    const title = form.get('title');
    const signerName = form.get('signer_name');
    const signerEmail = form.get('signer_email');
    const termEnd = form.get('term_end_date');

    if (!(file instanceof Blob)) {
      return error(400, 'bad_request', 'Missing multipart part "file".');
    }
    const fileName = 'name' in file && typeof file.name === 'string' ? file.name : '';
    if (file.type !== 'application/pdf' && !/\.pdf$/i.test(fileName)) {
      return error(415, 'unsupported_media_type', 'Only PDF files are accepted.');
    }
    if (file.size > MAX_PDF_BYTES) {
      return error(413, 'payload_too_large', 'PDF must be 20 MB or smaller.', {
        max_bytes: MAX_PDF_BYTES,
      });
    }
    const fields: { field: string; message: string }[] = [];
    if (typeof title !== 'string' || !title.trim() || title.length > 200) {
      fields.push({ field: 'title', message: 'Must be 1 to 200 characters.' });
    }
    if (typeof signerName !== 'string' || !signerName.trim() || signerName.length > 200) {
      fields.push({ field: 'signer_name', message: 'Must be 1 to 200 characters.' });
    }
    if (typeof signerEmail !== 'string' || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(signerEmail)) {
      fields.push({ field: 'signer_email', message: 'Not a valid email address.' });
    }
    if (termEnd !== null && typeof termEnd === 'string' && !/^\d{4}-\d{2}-\d{2}$/.test(termEnd)) {
      fields.push({ field: 'term_end_date', message: 'Must be a date (YYYY-MM-DD).' });
    }
    if (fields.length) {
      return error(422, 'validation_error', 'One or more fields are invalid.', { fields });
    }

    const id = uuid();
    const createdAt = nowIso();
    const contract: ContractDetail = {
      id,
      title: (title as string).trim(),
      status: 'draft',
      created_by: MOCK_ADMIN.id,
      term_end_date: typeof termEnd === 'string' && termEnd ? termEnd : null,
      signer_name: (signerName as string).trim(),
      signer_email: (signerEmail as string).trim(),
      original_pdf_sha256: fakeSha256(`${id}-${file.size}`),
      final_pdf_sha256: null,
      sent_at: null,
      first_viewed_at: null,
      signed_at: null,
      expires_at: null,
      cancelled_at: null,
      retain_until: null,
      anonymized_at: null,
      created_at: createdAt,
      updated_at: createdAt,
      original_pdf_size: file.size,
      signer: {
        id: uuid(),
        name: (signerName as string).trim(),
        email: (signerEmail as string).trim(),
        has_active_link: false,
        token_created_at: null,
        typed_name: null,
        consent_given_at: null,
        consent_text_version: null,
        signed_ip: null,
        signed_user_agent: null,
      },
      events: [
        {
          id: db.nextEventId(),
          contract_id: id,
          event_type: 'contract.created',
          actor_type: 'admin',
          actor_id: MOCK_ADMIN.id,
          occurred_at: createdAt,
          ip: null,
          user_agent: null,
          metadata: { to_status: 'draft' },
        },
      ],
    };
    db.contracts.unshift(contract);
    return HttpResponse.json(contract, { status: 201 });
  }),

  http.get(url('/admin/contracts/:contractId'), ({ request, params }) => {
    const denied = unauthorized(request);
    if (denied) return denied;
    const contract = db.contracts.find((c) => c.id === params['contractId']);
    if (!contract) return error(404, 'not_found', 'Not found.');
    return HttpResponse.json(contract);
  }),

  http.post(url('/admin/contracts/:contractId/send'), async ({ request, params }) => {
    const denied = unauthorized(request);
    if (denied) return denied;
    const contract = db.contracts.find((c) => c.id === params['contractId']);
    if (!contract) return error(404, 'not_found', 'Not found.');

    let body: SendContractRequest = { send_email: true };
    const raw = await request.text();
    if (raw) {
      try {
        body = { ...body, ...(JSON.parse(raw) as Partial<SendContractRequest>) };
      } catch {
        return error(400, 'bad_request', 'Request body is not valid JSON.');
      }
    }
    const days = body.expires_in_days ?? 14;
    if (!Number.isInteger(days) || days < 1 || days > 30) {
      return error(422, 'validation_error', 'One or more fields are invalid.', {
        fields: [{ field: 'expires_in_days', message: 'Must be between 1 and 30.' }],
      });
    }
    if (contract.anonymized_at) {
      return error(
        409,
        'invalid_state',
        'Signer data was removed by the retention policy; this contract cannot be sent.',
        { reason: 'anonymized' },
      );
    }
    if (!SENDABLE_STATUSES.includes(contract.status)) {
      return error(409, 'invalid_state', `Contract cannot be sent from status '${contract.status}'.`, {
        status: contract.status,
        allowed_from: [...SENDABLE_STATUSES],
      });
    }

    const now = new Date();
    const expires = new Date(now.getTime() + days * 86_400_000);
    const resend = contract.status === 'sent' || contract.status === 'viewed';
    const fromStatus = contract.status;
    contract.status = 'sent';
    contract.sent_at = now.toISOString();
    contract.expires_at = expires.toISOString();
    contract.updated_at = now.toISOString();
    contract.signer.has_active_link = true;
    contract.signer.token_created_at = now.toISOString();
    contract.events.push({
      id: db.nextEventId(),
      contract_id: contract.id,
      event_type: resend ? 'link.resent' : 'contract.sent',
      actor_type: 'admin',
      actor_id: MOCK_ADMIN.id,
      occurred_at: now.toISOString(),
      ip: null,
      user_agent: null,
      metadata: {
        from_status: fromStatus,
        to_status: 'sent',
        delivery: body.send_email ? 'email' : 'manual',
      },
    });

    // Rotation: the previous token stops resolving the moment a new one is issued.
    const token = newSigningToken();
    db.signingTokens.set(contract.id, token);
    const response: SendContractResponse = {
      contract,
      signing_link: {
        url: `${webBaseUrl()}/sign/${token}`,
        expires_at: expires.toISOString(),
      },
      email_sent: Boolean(body.send_email),
    };
    return HttpResponse.json(response);
  }),

  ...publicSigningHandlers,
];
