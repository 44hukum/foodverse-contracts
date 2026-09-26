/**
 * Fixture signing tokens for the MSW mocks. Deliberately fake and readable:
 * they exist nowhere outside this mock, and each one maps to a seeded contract
 * in src/mocks/data.ts so every page state is reachable from a URL in
 * `npm run dev:mock`, the Vitest suite, and the Playwright happy path.
 * Tokens issued by the mock send endpoint are random and never written down.
 */

export const MOCK_CONSENT_TEXT_VERSION = 'v0-draft';

/** Pads a readable label to the 43-character base64url shape the API requires. */
function fixtureToken(label: string): string {
  return `${label}${'-'.repeat(43)}`.slice(0, 43);
}

export const MOCK_SIGNING_TOKENS = {
  /** Contract `sent`, never opened: the first GET moves it to `viewed`. */
  sent: fixtureToken('mock-signing-token-sent'),
  /** Contract already `viewed`: the happy path. */
  viewed: fixtureToken('mock-signing-token-viewed'),
  /** Contract `signed`: 410 link_used. */
  signed: fixtureToken('mock-signing-token-signed'),
  /** Contract `expired`: 410 link_expired. */
  expired: fixtureToken('mock-signing-token-expired'),
  /** Contract `cancelled`: 410 contract_cancelled. */
  cancelled: fixtureToken('mock-signing-token-cancelled'),
  /** Well-formed but unknown to the mock: 404 not_found. */
  unknown: fixtureToken('mock-signing-token-unknown'),
} as const;

export const MOCK_SIGNING_CONTRACT_IDS = {
  sent: 'c0000002-0000-4000-8000-000000000002',
  viewed: 'c0000003-0000-4000-8000-000000000003',
  signed: 'c0000004-0000-4000-8000-000000000004',
  expired: 'c0000005-0000-4000-8000-000000000005',
  cancelled: 'c0000006-0000-4000-8000-000000000006',
} as const;

/** contract id -> active token; seeded into the mock db by src/mocks/data.ts. */
export const SEED_SIGNING_TOKENS: ReadonlyArray<readonly [string, string]> = [
  [MOCK_SIGNING_CONTRACT_IDS.sent, MOCK_SIGNING_TOKENS.sent],
  [MOCK_SIGNING_CONTRACT_IDS.viewed, MOCK_SIGNING_TOKENS.viewed],
  [MOCK_SIGNING_CONTRACT_IDS.signed, MOCK_SIGNING_TOKENS.signed],
  [MOCK_SIGNING_CONTRACT_IDS.expired, MOCK_SIGNING_TOKENS.expired],
  [MOCK_SIGNING_CONTRACT_IDS.cancelled, MOCK_SIGNING_TOKENS.cancelled],
];
