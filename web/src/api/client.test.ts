import { HttpResponse, http } from 'msw';
import { describe, expect, it } from 'vitest';
import { session } from '../auth/session';
import { API_BASE_URL } from '../config';
import { MOCK_ACCESS_TOKEN, MOCK_ADMIN, MOCK_ADMIN_EMAIL, MOCK_ADMIN_PASSWORD } from '../mocks/data';
import { server } from '../mocks/server';
import { ApiError, getContract, listContracts, login, sendContractLink } from './client';

function signIn(): void {
  session.set({ token: MOCK_ACCESS_TOKEN, admin: MOCK_ADMIN });
}

describe('login', () => {
  it('returns the LoginResponse shape on success', async () => {
    const result = await login({ email: MOCK_ADMIN_EMAIL, password: MOCK_ADMIN_PASSWORD });
    expect(result.token_type).toBe('bearer');
    expect(result.access_token).toBe(MOCK_ACCESS_TOKEN);
    expect(result.admin.email).toBe(MOCK_ADMIN_EMAIL);
  });

  it('maps the Error schema into ApiError', async () => {
    const attempt = login({ email: MOCK_ADMIN_EMAIL, password: 'definitely-wrong-password' });
    await expect(attempt).rejects.toBeInstanceOf(ApiError);
    await expect(attempt).rejects.toMatchObject({
      status: 401,
      code: 'invalid_credentials',
      message: 'Email or password is incorrect.',
    });
  });
});

describe('authenticated requests', () => {
  it('sends the in-memory session as a bearer token', async () => {
    let seen: string | null = null;
    server.use(
      http.get(`${API_BASE_URL}/admin/contracts`, ({ request }) => {
        seen = request.headers.get('authorization');
        return HttpResponse.json({ items: [], next_cursor: null });
      }),
    );
    signIn();
    await listContracts();
    expect(seen).toBe(`Bearer ${MOCK_ACCESS_TOKEN}`);
  });

  it('rejects with unauthorized and clears the session when the token is refused', async () => {
    session.set({ token: 'stale-token', admin: MOCK_ADMIN });
    await expect(listContracts()).rejects.toMatchObject({ status: 401, code: 'unauthorized' });
    expect(session.get()).toBeNull();
  });

  it('serialises the list query as repeated status params, q, limit and cursor', async () => {
    let seen = '';
    server.use(
      http.get(`${API_BASE_URL}/admin/contracts`, ({ request }) => {
        seen = new URL(request.url).search;
        return HttpResponse.json({ items: [], next_cursor: null });
      }),
    );
    signIn();
    await listContracts({ status: ['sent', 'viewed'], q: 'aurora', limit: 10, cursor: 'abc' });
    const params = new URLSearchParams(seen);
    expect(params.getAll('status')).toEqual(['sent', 'viewed']);
    expect(params.get('q')).toBe('aurora');
    expect(params.get('limit')).toBe('10');
    expect(params.get('cursor')).toBe('abc');
  });

  it('surfaces 404 as not_found', async () => {
    signIn();
    await expect(getContract('00000000-0000-4000-8000-000000000000')).rejects.toMatchObject({
      status: 404,
      code: 'not_found',
    });
  });

  it('exposes validation details per field', async () => {
    signIn();
    const attempt = sendContractLink('c0000001-0000-4000-8000-000000000001', {
      send_email: true,
      expires_in_days: 99,
    });
    await expect(attempt).rejects.toBeInstanceOf(ApiError);
    const err = (await attempt.catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe('validation_error');
    expect(err.fieldErrors()).toEqual({ expires_in_days: 'Must be between 1 and 30.' });
  });

  it('turns a failed fetch into a network_error', async () => {
    server.use(http.get(`${API_BASE_URL}/admin/contracts`, () => HttpResponse.error()));
    signIn();
    await expect(listContracts()).rejects.toMatchObject({ status: 0, code: 'network_error' });
  });
});
