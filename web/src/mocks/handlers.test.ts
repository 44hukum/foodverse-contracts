import { describe, expect, it } from 'vitest';
import { session } from '../auth/session';
import { getContract, sendContractLink } from '../api/client';
import { MOCK_ACCESS_TOKEN, MOCK_ADMIN, db } from './data';

const DRAFT_ID = 'c0000001-0000-4000-8000-000000000001';
const SENT_ID = 'c0000002-0000-4000-8000-000000000002';
const SIGNED_ID = 'c0000004-0000-4000-8000-000000000004';

describe('mock send endpoint', () => {
  it('issues a fresh 43-character token on every send and never repeats it', async () => {
    session.set({ token: MOCK_ACCESS_TOKEN, admin: MOCK_ADMIN });
    const first = await sendContractLink(DRAFT_ID, { send_email: true });
    const second = await sendContractLink(DRAFT_ID, { send_email: false });
    const token = (url: string) => url.split('/sign/')[1] ?? '';
    expect(token(first.signing_link.url)).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(token(second.signing_link.url)).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(token(first.signing_link.url)).not.toBe(token(second.signing_link.url));

    expect(first.contract.events.at(-1)?.event_type).toBe('contract.sent');
    expect(second.contract.events.at(-1)?.event_type).toBe('link.resent');
    expect(second.contract.events.at(-1)?.metadata).toEqual({
      from_status: 'sent',
      to_status: 'sent',
      delivery: 'manual',
    });
    expect(second.email_sent).toBe(false);

    // The token is not retrievable afterwards: get returns no link.
    const detail = await getContract(DRAFT_ID);
    expect(JSON.stringify(detail)).not.toContain(token(second.signing_link.url));
  });

  it('refuses to send from a terminal status with 409 invalid_state', async () => {
    session.set({ token: MOCK_ACCESS_TOKEN, admin: MOCK_ADMIN });
    await expect(sendContractLink(SIGNED_ID, { send_email: true })).rejects.toMatchObject({
      status: 409,
      code: 'invalid_state',
      details: { status: 'signed', allowed_from: ['draft', 'sent', 'viewed', 'expired'] },
    });
  });

  it('keeps events append-only when re-sending', async () => {
    session.set({ token: MOCK_ACCESS_TOKEN, admin: MOCK_ADMIN });
    const before = db.contracts.find((c) => c.id === SENT_ID)!.events.map((e) => e.id);
    const after = (await sendContractLink(SENT_ID, { send_email: true })).contract.events.map((e) => e.id);
    expect(after.slice(0, before.length)).toEqual(before);
    expect(after).toHaveLength(before.length + 1);
  });
});
