import { describe, expect, it } from 'vitest';
import { getContractByToken, sendContractLink, submitSignature } from '../../api/client';
import { session } from '../../auth/session';
import { MOCK_ACCESS_TOKEN, MOCK_ADMIN, db } from '../../mocks/data';
import { MAX_SIGNATURE_PNG_BYTES, SIGNING_TOKEN_RE } from '../signing';
import { MOCK_SIGNING_CONTRACT_IDS, MOCK_SIGNING_TOKENS, SEED_SIGNING_TOKENS } from './data';

const PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';

const validBody = {
  typed_name: 'Anita Gurung',
  signature_image: PNG,
  consent: true as const,
  consent_text_version: 'v0-draft',
};

describe('fixture tokens', () => {
  it('match the API token shape and are all distinct', () => {
    const tokens = Object.values(MOCK_SIGNING_TOKENS);
    for (const token of tokens) expect(token).toMatch(SIGNING_TOKEN_RE);
    expect(new Set(tokens).size).toBe(tokens.length);
    expect(SEED_SIGNING_TOKENS.map(([id]) => id)).toEqual(Object.values(MOCK_SIGNING_CONTRACT_IDS));
  });
});

describe('mock GET /public/sign/{token}', () => {
  it('returns the public contract with a short-lived pdf url and the consent text', async () => {
    const body = await getContractByToken(MOCK_SIGNING_TOKENS.viewed);
    expect(body).toMatchObject({
      contract_id: MOCK_SIGNING_CONTRACT_IDS.viewed,
      status: 'viewed',
      signer: { name: 'Anita Gurung', email: 'anita@lakesideresort.example' },
      consent_text_version: 'v0-draft',
    });
    expect(body.consent_text).toContain('I confirm that I am Anita Gurung');
    expect(body.consent_text).toContain('"Lakeside Resort — Onboarding Agreement"');
    expect(body.pdf.sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(body.pdf.url).toContain(`/contracts/${MOCK_SIGNING_CONTRACT_IDS.viewed}/original.pdf`);
    expect(new Date(body.pdf.expires_at).getTime()).toBeGreaterThan(Date.now());
    expect(JSON.stringify(body)).not.toContain(MOCK_SIGNING_TOKENS.viewed);
  });

  it('writes link.viewed on every open, with the transition only on the first', async () => {
    const row = db.contracts.find((c) => c.id === MOCK_SIGNING_CONTRACT_IDS.sent)!;
    const before = row.events.length;
    await getContractByToken(MOCK_SIGNING_TOKENS.sent);
    await getContractByToken(MOCK_SIGNING_TOKENS.sent);
    expect(row.events).toHaveLength(before + 2);
    expect(row.events[before]?.metadata).toEqual({ from_status: 'sent', to_status: 'viewed' });
    expect(row.events[before + 1]?.metadata).toEqual({});
    expect(row.status).toBe('viewed');
  });

  it('answers 404 for malformed and unknown tokens alike', async () => {
    await expect(getContractByToken('short')).rejects.toMatchObject({ status: 404, code: 'not_found' });
    await expect(getContractByToken(MOCK_SIGNING_TOKENS.unknown)).rejects.toMatchObject({
      status: 404,
      code: 'not_found',
    });
  });

  it('answers 410 with a reason for signed, expired, and cancelled contracts', async () => {
    await expect(getContractByToken(MOCK_SIGNING_TOKENS.signed)).rejects.toMatchObject({
      status: 410,
      code: 'link_used',
      details: { signed_at: '2026-09-28T14:22:10Z' },
    });
    await expect(getContractByToken(MOCK_SIGNING_TOKENS.expired)).rejects.toMatchObject({
      status: 410,
      code: 'link_expired',
      details: { expired_at: '2026-08-15T08:05:00Z' },
    });
    await expect(getContractByToken(MOCK_SIGNING_TOKENS.cancelled)).rejects.toMatchObject({
      status: 410,
      code: 'contract_cancelled',
    });
  });

  it('stops resolving the old token once the admin re-sends (rotation)', async () => {
    session.set({ token: MOCK_ACCESS_TOKEN, admin: MOCK_ADMIN });
    const sent = await sendContractLink(MOCK_SIGNING_CONTRACT_IDS.viewed, { send_email: false });
    session.clear();
    await expect(getContractByToken(MOCK_SIGNING_TOKENS.viewed)).rejects.toMatchObject({
      status: 404,
    });
    const fresh = sent.signing_link.url.split('/sign/')[1] ?? '';
    const body = await getContractByToken(fresh);
    expect(body.contract_id).toBe(MOCK_SIGNING_CONTRACT_IDS.viewed);
  });
});

describe('mock POST /public/sign/{token}/signature', () => {
  it('signs once, invalidates the link, and then answers 410 link_used', async () => {
    const result = await submitSignature(MOCK_SIGNING_TOKENS.viewed, validBody);
    expect(result).toMatchObject({
      contract_id: MOCK_SIGNING_CONTRACT_IDS.viewed,
      status: 'signed',
      download: { variant: 'signed', sha256: result.final_pdf_sha256 },
    });
    expect(result.download.filename).toMatch(/-signed\.pdf$/);
    const row = db.contracts.find((c) => c.id === MOCK_SIGNING_CONTRACT_IDS.viewed)!;
    expect(row.retain_until).toBe(`${new Date().getUTCFullYear() + 7}-${result.signed_at.slice(5, 10)}`);

    await expect(submitSignature(MOCK_SIGNING_TOKENS.viewed, validBody)).rejects.toMatchObject({
      status: 410,
      code: 'link_used',
      details: { signed_at: result.signed_at },
    });
    await expect(getContractByToken(MOCK_SIGNING_TOKENS.viewed)).rejects.toMatchObject({
      status: 410,
      code: 'link_used',
    });
  });

  it('accepts a submit straight from sent (client skipped the GET)', async () => {
    const result = await submitSignature(MOCK_SIGNING_TOKENS.sent, validBody);
    expect(result.status).toBe('signed');
    const row = db.contracts.find((c) => c.id === MOCK_SIGNING_CONTRACT_IDS.sent)!;
    expect(row.events.at(-1)?.metadata).toEqual({ from_status: 'sent', to_status: 'signed' });
  });

  it('rejects missing consent, a stale consent version, and a short name with 422', async () => {
    await expect(
      submitSignature(MOCK_SIGNING_TOKENS.viewed, { ...validBody, consent: false as unknown as true }),
    ).rejects.toMatchObject({
      status: 422,
      code: 'validation_error',
      details: { fields: [{ field: 'consent', message: 'Consent must be true.' }] },
    });
    await expect(
      submitSignature(MOCK_SIGNING_TOKENS.viewed, { ...validBody, consent_text_version: 'v9' }),
    ).rejects.toMatchObject({
      status: 422,
      details: { fields: [{ field: 'consent_text_version', message: expect.stringContaining('v0-draft') }] },
    });
    await expect(
      submitSignature(MOCK_SIGNING_TOKENS.viewed, { ...validBody, typed_name: ' A ' }),
    ).rejects.toMatchObject({ status: 422, details: { fields: [{ field: 'typed_name' }] } });
    const row = db.contracts.find((c) => c.id === MOCK_SIGNING_CONTRACT_IDS.viewed)!;
    expect(row.status).toBe('viewed');
  });

  it('rejects a non-PNG image with 422 and an oversized PNG with 413', async () => {
    await expect(
      submitSignature(MOCK_SIGNING_TOKENS.viewed, {
        ...validBody,
        signature_image: 'data:image/jpeg;base64,QUJD',
      }),
    ).rejects.toMatchObject({ status: 422, details: { fields: [{ field: 'signature_image' }] } });
    const oversized = `data:image/png;base64,${'A'.repeat(Math.ceil((MAX_SIGNATURE_PNG_BYTES + 3) / 3) * 4)}`;
    await expect(
      submitSignature(MOCK_SIGNING_TOKENS.viewed, { ...validBody, signature_image: oversized }),
    ).rejects.toMatchObject({
      status: 413,
      code: 'payload_too_large',
      details: { max_bytes: MAX_SIGNATURE_PNG_BYTES },
    });
  });

  it('refuses to sign expired, cancelled, or unknown links', async () => {
    await expect(submitSignature(MOCK_SIGNING_TOKENS.expired, validBody)).rejects.toMatchObject({
      status: 410,
      code: 'link_expired',
    });
    await expect(submitSignature(MOCK_SIGNING_TOKENS.cancelled, validBody)).rejects.toMatchObject({
      status: 410,
      code: 'contract_cancelled',
    });
    await expect(submitSignature(MOCK_SIGNING_TOKENS.unknown, validBody)).rejects.toMatchObject({
      status: 404,
    });
  });
});
