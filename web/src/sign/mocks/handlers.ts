/**
 * MSW handlers for the public signing endpoints in openapi.yaml
 * (`GET /public/sign/{token}`, `POST /public/sign/{token}/signature`).
 * Behaviour follows SPEC.md §4–5: first open moves `sent` to `viewed`, every
 * open writes `link.viewed`, expiry is applied lazily, signing is single use,
 * and unknown or rotated tokens are indistinguishable (404).
 */
import { HttpResponse, http } from 'msw';
import type {
  ApiErrorBody,
  ContractDetail,
  ErrorCode,
  PublicContract,
  SignatureResult,
  SubmitSignatureRequest,
} from '../../api/types';
import { API_BASE_URL } from '../../config';
import { db, fakeSha256 } from '../../mocks/data';
import {
  MAX_SIGNATURE_PNG_BYTES,
  SIGNING_TOKEN_RE,
  TYPED_NAME_MAX_LENGTH,
  TYPED_NAME_MIN_LENGTH,
  pngDataUrlBytes,
} from '../signing';
import { MOCK_CONSENT_TEXT_VERSION } from './data';

const PDF_URL_TTL_MS = 300_000;
const PNG_DATA_URL_RE = /^data:image\/png;base64,[A-Za-z0-9+/=]+$/;

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

function notFound(): HttpResponse<ApiErrorBody> {
  return error(404, 'not_found', 'Not found.');
}

function nowIso(): string {
  return new Date().toISOString();
}

/**
 * Shaped like the local storage backend's signed URL (SPEC.md §6). No PDF
 * bytes are served in mock mode; see the placeholder handler below.
 */
function mockStorageUrl(contractId: string, variant: 'original' | 'signed', expiresAt: string): string {
  const origin = new URL(API_BASE_URL).origin;
  const exp = Math.floor(new Date(expiresAt).getTime() / 1000);
  return `${origin}/_storage/local/contracts/${contractId}/${variant}.pdf?exp=${exp}&sig=mock`;
}

function findByToken(token: string): ContractDetail | null {
  for (const [contractId, active] of db.signingTokens) {
    if (active === token) return db.contracts.find((c) => c.id === contractId) ?? null;
  }
  return null;
}

function pushEvent(
  contract: ContractDetail,
  eventType: ContractDetail['events'][number]['event_type'],
  actorType: 'signer' | 'system',
  occurredAt: string,
  metadata: Record<string, unknown>,
): void {
  contract.events.push({
    id: db.nextEventId(),
    contract_id: contract.id,
    event_type: eventType,
    actor_type: actorType,
    actor_id: actorType === 'signer' ? contract.signer.id : null,
    occurred_at: occurredAt,
    ip: null,
    user_agent: null,
    metadata,
  });
}

/** The 410 (or 404) a once-valid link now gets, or null while it is live. Applies lazy expiry. */
function goneResponse(contract: ContractDetail): HttpResponse<ApiErrorBody> | null {
  switch (contract.status) {
    case 'signed':
      return error(410, 'link_used', 'This document has already been signed.', {
        signed_at: contract.signed_at,
      });
    case 'cancelled':
      return error(410, 'contract_cancelled', 'This contract has been cancelled by the sender.');
    case 'expired':
      return error(410, 'link_expired', 'This signing link has expired. Ask the sender for a new one.', {
        expired_at: contract.expires_at,
      });
    case 'draft':
      return notFound();
    case 'sent':
    case 'viewed': {
      if (contract.expires_at && new Date(contract.expires_at).getTime() < Date.now()) {
        const fromStatus = contract.status;
        const now = nowIso();
        contract.status = 'expired';
        contract.updated_at = now;
        contract.signer.has_active_link = false;
        pushEvent(contract, 'contract.expired', 'system', now, {
          from_status: fromStatus,
          to_status: 'expired',
        });
        return error(410, 'link_expired', 'This signing link has expired. Ask the sender for a new one.', {
          expired_at: contract.expires_at,
        });
      }
      return null;
    }
  }
}

/** SPEC.md §8 consent text `v0-draft`, with the placeholders filled in. */
function consentText(contract: ContractDetail): string {
  return (
    `I confirm that I am ${contract.signer.name ?? 'the signer'}, that I have read the document ` +
    `titled "${contract.title}", and that I agree to sign it electronically. I understand that my ` +
    'typed name, drawn signature, IP address, and the time of signing will be recorded and ' +
    'attached to the document as evidence of my agreement. [v0-draft — pending legal review]'
  );
}

function slug(title: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 60) || 'contract'
  );
}

function plusYears(isoDate: string, years: number): string {
  const [y = '1970', rest = '01-01'] = [isoDate.slice(0, 4), isoDate.slice(5)];
  return `${Number(y) + years}-${rest}`;
}

function resolveToken(params: Record<string, string | readonly string[] | undefined>): string {
  const raw = params['token'];
  return typeof raw === 'string' ? raw : '';
}

export const publicSigningHandlers = [
  http.get(url('/public/sign/:token'), ({ params }) => {
    const token = resolveToken(params);
    if (!SIGNING_TOKEN_RE.test(token)) return notFound();
    const contract = findByToken(token);
    if (!contract) return notFound();
    const gone = goneResponse(contract);
    if (gone) return gone;

    const now = nowIso();
    const fromStatus = contract.status;
    if (contract.status === 'sent') {
      contract.status = 'viewed';
      contract.first_viewed_at = now;
    }
    contract.updated_at = now;
    pushEvent(
      contract,
      'link.viewed',
      'signer',
      now,
      fromStatus === 'sent' ? { from_status: 'sent', to_status: 'viewed' } : {},
    );

    const pdfExpires = new Date(Date.now() + PDF_URL_TTL_MS).toISOString();
    const body: PublicContract = {
      contract_id: contract.id,
      title: contract.title,
      status: 'viewed',
      signer: { name: contract.signer.name ?? '', email: contract.signer.email ?? '' },
      sent_by: 'Foodverse',
      expires_at: contract.expires_at ?? now,
      pdf: {
        url: mockStorageUrl(contract.id, 'original', pdfExpires),
        expires_at: pdfExpires,
        sha256: contract.original_pdf_sha256,
        size: contract.original_pdf_size,
      },
      consent_text: consentText(contract),
      consent_text_version: MOCK_CONSENT_TEXT_VERSION,
    };
    return HttpResponse.json(body);
  }),

  http.post(url('/public/sign/:token/signature'), async ({ params, request }) => {
    const token = resolveToken(params);
    if (!SIGNING_TOKEN_RE.test(token)) return notFound();
    const contract = findByToken(token);
    if (!contract) return notFound();
    const gone = goneResponse(contract);
    if (gone) return gone;

    let body: Partial<SubmitSignatureRequest>;
    try {
      body = (await request.json()) as Partial<SubmitSignatureRequest>;
    } catch {
      return error(400, 'bad_request', 'Request body is not valid JSON.');
    }

    const fields: { field: string; message: string }[] = [];
    const typedName = typeof body.typed_name === 'string' ? body.typed_name.trim() : '';
    if (typedName.length < TYPED_NAME_MIN_LENGTH || typedName.length > TYPED_NAME_MAX_LENGTH) {
      fields.push({
        field: 'typed_name',
        message: `Must be ${TYPED_NAME_MIN_LENGTH} to ${TYPED_NAME_MAX_LENGTH} characters.`,
      });
    }
    const image = typeof body.signature_image === 'string' ? body.signature_image : '';
    if (!PNG_DATA_URL_RE.test(image)) {
      fields.push({ field: 'signature_image', message: 'Must be a PNG data URL.' });
    } else if (pngDataUrlBytes(image) > MAX_SIGNATURE_PNG_BYTES) {
      return error(413, 'payload_too_large', 'Signature image must be 500 KB or smaller.', {
        max_bytes: MAX_SIGNATURE_PNG_BYTES,
      });
    }
    if (body.consent !== true) {
      fields.push({ field: 'consent', message: 'Consent must be true.' });
    }
    if (body.consent_text_version !== MOCK_CONSENT_TEXT_VERSION) {
      fields.push({
        field: 'consent_text_version',
        message: `Expected consent text version ${MOCK_CONSENT_TEXT_VERSION}.`,
      });
    }
    if (fields.length) {
      return error(422, 'validation_error', 'One or more fields are invalid.', { fields });
    }

    // Conditional transition: only sent/viewed reach this point (goneResponse handled the rest).
    const now = nowIso();
    const fromStatus = contract.status;
    contract.status = 'signed';
    contract.signed_at = now;
    contract.updated_at = now;
    contract.final_pdf_sha256 = fakeSha256(`${contract.id}-signed`);
    contract.retain_until = plusYears(contract.term_end_date ?? now.slice(0, 10), 7);
    contract.signer.has_active_link = false;
    contract.signer.typed_name = typedName;
    contract.signer.consent_given_at = now;
    contract.signer.consent_text_version = MOCK_CONSENT_TEXT_VERSION;
    pushEvent(contract, 'contract.signed', 'signer', now, {
      from_status: fromStatus,
      to_status: 'signed',
    });

    const downloadExpires = new Date(Date.now() + PDF_URL_TTL_MS).toISOString();
    const result: SignatureResult = {
      contract_id: contract.id,
      status: 'signed',
      signed_at: now,
      final_pdf_sha256: contract.final_pdf_sha256,
      download: {
        variant: 'signed',
        url: mockStorageUrl(contract.id, 'signed', downloadExpires),
        expires_at: downloadExpires,
        sha256: contract.final_pdf_sha256,
        filename: `${slug(contract.title)}-signed.pdf`,
      },
    };
    return HttpResponse.json(result);
  }),

  /** Stand-in for the local storage backend's download route. Serves text, never PDF bytes. */
  http.get(`${new URL(API_BASE_URL).origin}/_storage/local/*`, () => {
    return new HttpResponse('Mock storage: no document bytes are served in mock mode.', {
      headers: { 'content-type': 'text/plain; charset=utf-8' },
    });
  }),
];
