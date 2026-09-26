/**
 * In-memory fixture database for the MSW mocks. Used by `npm run dev:mock`
 * and by the Vitest suite. Everything here is invented: example.com addresses,
 * synthetic hashes, no real tokens (signing tokens are generated per call in
 * handlers.ts and never written down).
 */
import type { AdminUser, ContractDetail, ContractEvent, ContractStatus } from '../api/types';
import { SEED_SIGNING_TOKENS } from '../sign/mocks/data';

export const MOCK_ADMIN: AdminUser = {
  id: '11111111-1111-4111-8111-111111111111',
  email: 'admin@example.com',
  name: 'Mock Admin',
  last_login_at: null,
  created_at: '2026-09-01T08:00:00Z',
};

/** Credentials the mock login accepts. Not a real account anywhere. */
export const MOCK_ADMIN_EMAIL = MOCK_ADMIN.email;
export const MOCK_ADMIN_PASSWORD = 'mock-only-password';
/** Opaque bearer the mock issues; the mock API accepts only this value. */
export const MOCK_ACCESS_TOKEN = 'mock-access-token-not-a-jwt';
export const MOCK_TOKEN_TTL_SECONDS = 28800;

/** 64 lowercase hex chars derived from a seed, shaped like a SHA-256 but meaningless. */
export function fakeSha256(seed: string): string {
  // FNV-1a over the whole seed, then a small xorshift stream for 64 hex chars.
  let h = 0x811c9dc5;
  for (let i = 0; i < seed.length; i += 1) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  let out = '';
  let x = h || 0x9e3779b9;
  while (out.length < 64) {
    x ^= x << 13;
    x >>>= 0;
    x ^= x >>> 17;
    x ^= x << 5;
    x >>>= 0;
    out += x.toString(16).padStart(8, '0');
  }
  return out.slice(0, 64);
}

let eventSeq = 1;

/** Live links must not expire while the fixtures age; expiry is relative to now. */
function daysFromNow(days: number): string {
  return new Date(Date.now() + days * 86_400_000).toISOString();
}

function event(
  contractId: string,
  eventType: ContractEvent['event_type'],
  actorType: ContractEvent['actor_type'],
  occurredAt: string,
  metadata: Record<string, unknown> = {},
): ContractEvent {
  return {
    id: eventSeq++,
    contract_id: contractId,
    event_type: eventType,
    actor_type: actorType,
    actor_id: actorType === 'admin' ? MOCK_ADMIN.id : actorType === 'signer' ? `${contractId}-signer` : null,
    occurred_at: occurredAt,
    ip: null,
    user_agent: null,
    metadata,
  };
}

interface SeedInput {
  id: string;
  title: string;
  status: ContractStatus;
  signer_name: string | null;
  signer_email: string | null;
  created_at: string;
  sent_at?: string;
  first_viewed_at?: string;
  signed_at?: string;
  expires_at?: string;
  cancelled_at?: string;
  term_end_date?: string;
  anonymized_at?: string;
}

function seed(input: SeedInput): ContractDetail {
  const events: ContractEvent[] = [event(input.id, 'contract.created', 'admin', input.created_at)];
  if (input.sent_at) {
    events.push(
      event(input.id, 'contract.sent', 'admin', input.sent_at, {
        from_status: 'draft',
        to_status: 'sent',
        delivery: 'email',
      }),
    );
  }
  if (input.first_viewed_at) {
    events.push(
      event(input.id, 'link.viewed', 'signer', input.first_viewed_at, {
        from_status: 'sent',
        to_status: 'viewed',
      }),
    );
  }
  if (input.signed_at) {
    events.push(
      event(input.id, 'contract.signed', 'signer', input.signed_at, {
        from_status: 'viewed',
        to_status: 'signed',
      }),
    );
  }
  if (input.status === 'expired' && input.expires_at) {
    events.push(
      event(input.id, 'contract.expired', 'system', input.expires_at, {
        from_status: 'sent',
        to_status: 'expired',
      }),
    );
  }
  if (input.cancelled_at) {
    events.push(
      event(input.id, 'contract.cancelled', 'admin', input.cancelled_at, {
        from_status: 'sent',
        to_status: 'cancelled',
      }),
    );
  }
  if (input.anonymized_at) {
    events.push(event(input.id, 'signer.anonymized', 'system', input.anonymized_at));
  }
  const signed = input.status === 'signed';
  const last = events[events.length - 1];
  return {
    id: input.id,
    title: input.title,
    status: input.status,
    created_by: MOCK_ADMIN.id,
    term_end_date: input.term_end_date ?? null,
    signer_name: input.signer_name,
    signer_email: input.signer_email,
    original_pdf_sha256: fakeSha256(`${input.id}-original`),
    final_pdf_sha256: signed ? fakeSha256(`${input.id}-signed`) : null,
    sent_at: input.sent_at ?? null,
    first_viewed_at: input.first_viewed_at ?? null,
    signed_at: input.signed_at ?? null,
    expires_at: input.expires_at ?? null,
    cancelled_at: input.cancelled_at ?? null,
    retain_until: signed ? '2035-12-31' : null,
    anonymized_at: input.anonymized_at ?? null,
    created_at: input.created_at,
    updated_at: last ? last.occurred_at : input.created_at,
    original_pdf_size: 184_320,
    signer: {
      id: `${input.id.slice(0, 8)}-0000-4000-8000-000000000001`,
      name: input.signer_name,
      email: input.signer_email,
      has_active_link: input.status === 'sent' || input.status === 'viewed',
      token_created_at: input.sent_at ?? null,
      typed_name: signed ? input.signer_name : null,
      consent_given_at: signed ? (input.signed_at ?? null) : null,
      consent_text_version: signed ? 'v0-draft' : null,
      signed_ip: null,
      signed_user_agent: null,
    },
    events,
  };
}

export function seedContracts(): ContractDetail[] {
  eventSeq = 1;
  return [
    seed({
      id: 'c0000001-0000-4000-8000-000000000001',
      title: 'Hotel Aurora — Onboarding Agreement 2026',
      status: 'draft',
      signer_name: 'Maria Petrova',
      signer_email: 'maria@hotelaurora.example',
      created_at: '2026-09-25T09:15:00Z',
      term_end_date: '2028-12-31',
    }),
    seed({
      id: 'c0000002-0000-4000-8000-000000000002',
      title: 'Thakali Kitchen — Partner Terms',
      status: 'sent',
      signer_name: 'Suman Thakali',
      signer_email: 'suman@thakalikitchen.example',
      created_at: '2026-09-24T04:30:00Z',
      sent_at: '2026-09-24T04:35:00Z',
      expires_at: daysFromNow(12),
    }),
    seed({
      id: 'c0000003-0000-4000-8000-000000000003',
      title: 'Lakeside Resort — Onboarding Agreement',
      status: 'viewed',
      signer_name: 'Anita Gurung',
      signer_email: 'anita@lakesideresort.example',
      created_at: '2026-09-22T10:00:00Z',
      sent_at: '2026-09-22T10:05:00Z',
      first_viewed_at: '2026-09-23T02:40:00Z',
      expires_at: daysFromNow(10),
    }),
    seed({
      id: 'c0000004-0000-4000-8000-000000000004',
      title: 'Everest Bakery — Supplier Agreement',
      status: 'signed',
      signer_name: 'Dawa Sherpa',
      signer_email: 'dawa@everestbakery.example',
      created_at: '2026-09-10T06:00:00Z',
      sent_at: '2026-09-10T06:10:00Z',
      first_viewed_at: '2026-09-11T03:00:00Z',
      signed_at: '2026-09-28T14:22:10Z',
      expires_at: '2026-09-24T06:10:00Z',
      term_end_date: '2028-12-31',
    }),
    seed({
      id: 'c0000005-0000-4000-8000-000000000005',
      title: 'Old Town Café — Onboarding Agreement',
      status: 'expired',
      signer_name: 'Bikash Rai',
      signer_email: 'bikash@oldtowncafe.example',
      created_at: '2026-08-01T08:00:00Z',
      sent_at: '2026-08-01T08:05:00Z',
      expires_at: '2026-08-15T08:05:00Z',
    }),
    seed({
      id: 'c0000006-0000-4000-8000-000000000006',
      title: 'Riverside Lodge — Onboarding Agreement',
      status: 'cancelled',
      signer_name: 'Prakash Karki',
      signer_email: 'prakash@riversidelodge.example',
      created_at: '2026-07-20T08:00:00Z',
      sent_at: '2026-07-20T08:05:00Z',
      expires_at: '2026-08-03T08:05:00Z',
      cancelled_at: '2026-07-22T12:00:00Z',
    }),
    seed({
      id: 'c0000007-0000-4000-8000-000000000007',
      title: 'Sunrise Homestay — Onboarding Agreement',
      status: 'expired',
      signer_name: null,
      signer_email: null,
      created_at: '2026-05-01T08:00:00Z',
      sent_at: '2026-05-01T08:05:00Z',
      expires_at: '2026-05-15T08:05:00Z',
      anonymized_at: '2026-08-14T01:00:00Z',
    }),
  ];
}

export interface MockDb {
  contracts: ContractDetail[];
  /** contract id -> the one active signing token. Replaced on re-send (rotation). */
  signingTokens: Map<string, string>;
  nextEventId(): number;
}

function createDb(): MockDb {
  const contracts = seedContracts();
  return {
    contracts,
    signingTokens: new Map(SEED_SIGNING_TOKENS),
    nextEventId: () => eventSeq++,
  };
}

export let db: MockDb = createDb();

export function resetMockDb(): void {
  db = createDb();
}
