import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { API_BASE_URL } from '../config';
import { db } from '../mocks/data';
import { server } from '../mocks/server';
import { renderApp } from '../test/utils';
import { MOCK_SIGNING_CONTRACT_IDS, MOCK_SIGNING_TOKENS } from './mocks/data';

const { FAKE_PNG } = vi.hoisted(() => ({
  FAKE_PNG:
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
}));

// jsdom has no canvas, so the real pad (react-signature-canvas) is replaced by
// two buttons that drive the same `onChange` contract. The real component is
// exercised by the Playwright happy path in e2e/sign.spec.ts.
vi.mock('./SignaturePad', () => ({
  SignaturePad: ({
    onChange,
    disabled,
  }: {
    onChange: (dataUrl: string | null) => void;
    disabled?: boolean;
  }) => (
    <div>
      <button type="button" disabled={disabled} onClick={() => onChange(FAKE_PNG)}>
        Draw signature
      </button>
      <button type="button" disabled={disabled} onClick={() => onChange(null)}>
        Clear signature
      </button>
    </div>
  ),
}));

const VIEWED_TITLE = 'Lakeside Resort — Onboarding Agreement';
const signatureUrl = (token: string) => `${API_BASE_URL}/public/sign/${token}/signature`;
const contract = (id: string) => db.contracts.find((c) => c.id === id)!;

function openSignPage(token: string) {
  return renderApp(`/sign/${token}`, { authed: false });
}

/** Fills the form completely (name is prefilled), leaving submit enabled. */
async function completeForm(user: ReturnType<typeof userEvent.setup>): Promise<HTMLElement> {
  await screen.findByRole('heading', { name: VIEWED_TITLE });
  await user.click(screen.getByRole('button', { name: 'Draw signature' }));
  await user.click(screen.getByRole('checkbox', { name: /I confirm that I am Anita Gurung/ }));
  const submit = screen.getByRole('button', { name: 'Sign document' });
  expect(submit).toBeEnabled();
  return submit;
}

describe('SignPage: loading a live link', () => {
  it('shows the document, prefilled name, consent text, and a disabled submit', async () => {
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    expect(await screen.findByRole('heading', { name: VIEWED_TITLE })).toBeInTheDocument();

    const frame = screen.getByTitle(`${VIEWED_TITLE} (PDF)`);
    expect(frame.tagName).toBe('IFRAME');
    expect(frame).toHaveAttribute(
      'src',
      expect.stringContaining(`/_storage/local/contracts/${MOCK_SIGNING_CONTRACT_IDS.viewed}/original.pdf`),
    );
    expect(screen.getByRole('link', { name: 'open the PDF in a new tab' })).toHaveAttribute(
      'target',
      '_blank',
    );

    expect(screen.getByLabelText('Full name')).toHaveValue('Anita Gurung');
    expect(
      screen.getByRole('checkbox', {
        name: /I confirm that I am Anita Gurung, that I have read the document titled "Lakeside Resort/,
      }),
    ).not.toBeChecked();
    expect(screen.getByText(/Consent text version v0-draft/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Sign document' })).toBeDisabled();

    // Public page: no admin chrome, no login redirect.
    expect(screen.queryByRole('button', { name: 'Log out' })).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument();
  });

  it('never renders the signing token as a link', async () => {
    const { container } = openSignPage(MOCK_SIGNING_TOKENS.viewed);
    await screen.findByRole('heading', { name: VIEWED_TITLE });
    for (const anchor of container.querySelectorAll('a')) {
      expect(anchor.getAttribute('href') ?? '').not.toContain(MOCK_SIGNING_TOKENS.viewed);
    }
  });

  it('moves a sent contract to viewed and records link.viewed on first open', async () => {
    openSignPage(MOCK_SIGNING_TOKENS.sent);
    expect(
      await screen.findByRole('heading', { name: 'Thakali Kitchen — Partner Terms' }),
    ).toBeInTheDocument();
    const row = contract(MOCK_SIGNING_CONTRACT_IDS.sent);
    expect(row.status).toBe('viewed');
    expect(row.first_viewed_at).not.toBeNull();
    expect(row.events.at(-1)).toMatchObject({
      event_type: 'link.viewed',
      actor_type: 'signer',
      metadata: { from_status: 'sent', to_status: 'viewed' },
    });
  });
});

describe('SignPage: error pages', () => {
  it('rejects a malformed token without calling the API', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    openSignPage('not-a-real-token');
    expect(
      await screen.findByRole('heading', { name: 'This signing link is not valid' }),
    ).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument();
  });

  it('shows the invalid-link page for an unknown token (404)', async () => {
    openSignPage(MOCK_SIGNING_TOKENS.unknown);
    expect(
      await screen.findByRole('heading', { name: 'This signing link is not valid' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/ask the sender for a new link/)).toBeInTheDocument();
  });

  it('shows the expired page with the expiry time in both timezones', async () => {
    openSignPage(MOCK_SIGNING_TOKENS.expired);
    expect(
      await screen.findByRole('heading', { name: 'This signing link has expired' }),
    ).toBeInTheDocument();
    expect(screen.getByText('2026-08-15 08:05 UTC')).toBeInTheDocument();
    expect(screen.getByText('2026-08-15 13:50 NPT')).toBeInTheDocument();
    expect(screen.getByText(/Nothing has been signed/)).toBeInTheDocument();
  });

  it('shows the already-signed page and points to the emailed copy', async () => {
    openSignPage(MOCK_SIGNING_TOKENS.signed);
    expect(
      await screen.findByRole('heading', { name: 'This document has already been signed' }),
    ).toBeInTheDocument();
    expect(screen.getByText(/Check your inbox and spam folder/)).toBeInTheDocument();
    expect(screen.getByText('2026-09-28 14:22 UTC')).toBeInTheDocument();
  });

  it('shows the cancelled page', async () => {
    openSignPage(MOCK_SIGNING_TOKENS.cancelled);
    expect(
      await screen.findByRole('heading', { name: 'This contract has been cancelled' }),
    ).toBeInTheDocument();
  });

  it('expires a live link lazily when its expiry has passed', async () => {
    const row = contract(MOCK_SIGNING_CONTRACT_IDS.viewed);
    row.expires_at = new Date(Date.now() - 60_000).toISOString();
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    expect(
      await screen.findByRole('heading', { name: 'This signing link has expired' }),
    ).toBeInTheDocument();
    expect(row.status).toBe('expired');
    expect(row.events.at(-1)).toMatchObject({ event_type: 'contract.expired', actor_type: 'system' });
  });

  it('offers a retry when rate limited and recovers', async () => {
    const user = userEvent.setup();
    server.use(
      http.get(
        `${API_BASE_URL}/public/sign/:token`,
        () =>
          HttpResponse.json(
            { error: { code: 'rate_limited', message: 'Too many requests. Try again shortly.' } },
            { status: 429, headers: { 'Retry-After': '5' } },
          ),
        { once: true },
      ),
    );
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    expect(await screen.findByRole('heading', { name: 'Too many requests' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByRole('heading', { name: VIEWED_TITLE })).toBeInTheDocument();
  });

  it('shows the server message and a retry when the API is unavailable', async () => {
    server.use(
      http.get(`${API_BASE_URL}/public/sign/:token`, () =>
        HttpResponse.json(
          { error: { code: 'internal_error', message: 'Something went wrong. Reference id 7f3c1b2e.' } },
          { status: 500 },
        ),
      ),
    );
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    expect(
      await screen.findByRole('heading', { name: 'Could not load the document' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Reference id 7f3c1b2e');
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });
});

describe('SignPage: form gating', () => {
  it('enables submit only when name, signature, and consent are all present', async () => {
    const user = userEvent.setup();
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    await screen.findByRole('heading', { name: VIEWED_TITLE });
    const submit = screen.getByRole('button', { name: 'Sign document' });
    const consent = screen.getByRole('checkbox', { name: /I confirm that I am/ });
    const name = screen.getByLabelText('Full name');

    expect(submit).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Draw signature' }));
    expect(submit).toBeDisabled();
    await user.click(consent);
    expect(submit).toBeEnabled();

    await user.click(screen.getByRole('button', { name: 'Clear signature' }));
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Draw signature' }));
    expect(submit).toBeEnabled();

    await user.click(consent);
    expect(submit).toBeDisabled();
    await user.click(consent);
    expect(submit).toBeEnabled();

    await user.clear(name);
    await user.type(name, 'A');
    await user.tab();
    expect(submit).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('Enter your full name');
    await user.type(name, 'nita Gurung');
    expect(submit).toBeEnabled();
  });
});

describe('SignPage: submitting', () => {
  it('signs the document and shows the confirmation with hash and download', async () => {
    const user = userEvent.setup();
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    const submit = await completeForm(user);
    await user.click(submit);

    expect(await screen.findByRole('heading', { name: 'Document signed' })).toBeInTheDocument();
    const row = contract(MOCK_SIGNING_CONTRACT_IDS.viewed);
    expect(row.status).toBe('signed');
    expect(row.signer).toMatchObject({
      typed_name: 'Anita Gurung',
      consent_text_version: 'v0-draft',
      has_active_link: false,
    });
    expect(row.events.at(-1)).toMatchObject({
      event_type: 'contract.signed',
      actor_type: 'signer',
      metadata: { from_status: 'viewed', to_status: 'signed' },
    });
    expect(screen.getByText(row.final_pdf_sha256!)).toBeInTheDocument();
    expect(screen.getByText(/emailed to anita@lakesideresort.example/)).toBeInTheDocument();
    const download = screen.getByRole('link', { name: 'Download signed PDF' });
    expect(download).toHaveAttribute('href', expect.stringContaining('/signed.pdf'));
    expect(download).toHaveAttribute('rel', 'noopener noreferrer');
    expect(screen.queryByRole('button', { name: 'Sign document' })).not.toBeInTheDocument();
  });

  it('sends the typed name, PNG, consent, and consent version the API asked for', async () => {
    const user = userEvent.setup();
    let received: unknown = null;
    server.use(
      http.post(signatureUrl(MOCK_SIGNING_TOKENS.viewed), async ({ request }) => {
        received = await request.json();
        return HttpResponse.json(
          { error: { code: 'internal_error', message: 'Captured.' } },
          { status: 500 },
        );
      }),
    );
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    const submit = await completeForm(user);
    const name = screen.getByLabelText('Full name');
    await user.clear(name);
    await user.type(name, '  Anita B. Gurung  ');
    await user.click(submit);
    await screen.findByRole('alert');
    expect(received).toEqual({
      typed_name: 'Anita B. Gurung',
      signature_image: FAKE_PNG,
      consent: true,
      consent_text_version: 'v0-draft',
    });
  });

  it('switches to the already-signed page when the link was used meanwhile', async () => {
    const user = userEvent.setup();
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    const submit = await completeForm(user);
    const row = contract(MOCK_SIGNING_CONTRACT_IDS.viewed);
    row.status = 'signed';
    row.signed_at = '2026-09-26T10:00:00Z';
    await user.click(submit);
    expect(
      await screen.findByRole('heading', { name: 'This document has already been signed' }),
    ).toBeInTheDocument();
    expect(screen.getByText('2026-09-26 10:00 UTC')).toBeInTheDocument();
  });

  it('switches to the expired page when the link expired meanwhile', async () => {
    const user = userEvent.setup();
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    const submit = await completeForm(user);
    contract(MOCK_SIGNING_CONTRACT_IDS.viewed).expires_at = new Date(Date.now() - 1000).toISOString();
    await user.click(submit);
    expect(
      await screen.findByRole('heading', { name: 'This signing link has expired' }),
    ).toBeInTheDocument();
  });

  it('keeps the form intact and lets the signer retry after a server error', async () => {
    const user = userEvent.setup();
    server.use(
      http.post(
        signatureUrl(MOCK_SIGNING_TOKENS.viewed),
        () =>
          HttpResponse.json(
            { error: { code: 'internal_error', message: 'Something went wrong. Reference id 7f3c1b2e.' } },
            { status: 500 },
          ),
        { once: true },
      ),
    );
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    const submit = await completeForm(user);
    await user.click(submit);

    expect(await screen.findByRole('alert')).toHaveTextContent('Reference id 7f3c1b2e');
    expect(screen.getByText(/Your link is still valid, so you can try again/)).toBeInTheDocument();
    expect(screen.getByLabelText('Full name')).toHaveValue('Anita Gurung');
    expect(screen.getByRole('checkbox', { name: /I confirm/ })).toBeChecked();
    expect(contract(MOCK_SIGNING_CONTRACT_IDS.viewed).status).toBe('viewed');
    await waitFor(() => expect(submit).toBeEnabled());

    await user.click(submit);
    expect(await screen.findByRole('heading', { name: 'Document signed' })).toBeInTheDocument();
  });

  it('shows field errors from a 422 next to the fields', async () => {
    const user = userEvent.setup();
    server.use(
      http.post(signatureUrl(MOCK_SIGNING_TOKENS.viewed), () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation_error',
              message: 'One or more fields are invalid.',
              details: {
                fields: [
                  { field: 'typed_name', message: 'Name is not acceptable.' },
                  { field: 'signature_image', message: 'PNG could not be decoded.' },
                ],
              },
            },
          },
          { status: 422 },
        ),
      ),
    );
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    const submit = await completeForm(user);
    await user.click(submit);
    const alerts = await screen.findAllByRole('alert');
    const text = alerts.map((a) => a.textContent).join('\n');
    expect(text).toContain('One or more fields are invalid.');
    expect(text).toContain('Name is not acceptable.');
    expect(text).toContain('PNG could not be decoded.');
    expect(screen.queryByText(/Your link is still valid/)).not.toBeInTheDocument();
  });

  it('disables the form while the request is in flight', async () => {
    const user = userEvent.setup();
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    server.use(
      http.post(signatureUrl(MOCK_SIGNING_TOKENS.viewed), async () => {
        await gate;
        return HttpResponse.json(
          { error: { code: 'internal_error', message: 'Released.' } },
          { status: 500 },
        );
      }),
    );
    openSignPage(MOCK_SIGNING_TOKENS.viewed);
    const submit = await completeForm(user);
    await user.click(submit);
    expect(await screen.findByRole('button', { name: 'Signing…' })).toBeDisabled();
    expect(screen.getByLabelText('Full name')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Clear signature' })).toBeDisabled();
    release();
    expect(await screen.findByRole('alert')).toHaveTextContent('Released.');
  });
});
