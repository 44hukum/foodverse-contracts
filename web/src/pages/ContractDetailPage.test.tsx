import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { API_BASE_URL } from '../config';
import { db } from '../mocks/data';
import { server } from '../mocks/server';
import { renderApp } from '../test/utils';

const DRAFT_ID = 'c0000001-0000-4000-8000-000000000001';
const SENT_ID = 'c0000002-0000-4000-8000-000000000002';
const SIGNED_ID = 'c0000004-0000-4000-8000-000000000004';
const ANONYMIZED_ID = 'c0000007-0000-4000-8000-000000000007';

const SIGNING_URL = /\/sign\/[A-Za-z0-9_-]{43}$/;

describe('ContractDetailPage', () => {
  it('shows the contract, signer, hash, and events with both timezones', async () => {
    renderApp(`/contracts/${SIGNED_ID}`);
    expect(await screen.findByRole('heading', { name: 'Everest Bakery — Supplier Agreement' })).toBeInTheDocument();
    expect(screen.getByText('Signed', { selector: '.badge' })).toHaveAttribute('data-status', 'signed');
    expect(screen.getByText('Dawa Sherpa')).toBeInTheDocument();
    // signed_at 2026-09-28T14:22:10Z
    expect(screen.getAllByText('2026-09-28 20:07 NPT').length).toBeGreaterThan(0);
    expect(screen.getAllByText('2026-09-28 14:22 UTC').length).toBeGreaterThan(0);
    expect(screen.getByText(db.contracts[3]!.original_pdf_sha256)).toBeInTheDocument();
    expect(screen.getByText(db.contracts[3]!.final_pdf_sha256!)).toBeInTheDocument();
    const trail = screen.getByRole('region', { name: 'Audit trail' });
    expect(within(trail).getByText('contract.signed')).toBeInTheDocument();
    expect(screen.getByText('A contract in status “signed” cannot be sent.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /signing link/i })).not.toBeInTheDocument();
  });

  it('sends the link, moves the contract to Sent, and shows the link in a copy box, never as an anchor', async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue(undefined);
    renderApp(`/contracts/${DRAFT_ID}`);
    await screen.findByRole('heading', { name: 'Hotel Aurora — Onboarding Agreement 2026' });
    expect(screen.getByText('Draft', { selector: '.badge' })).toHaveAttribute('data-status', 'draft');

    await user.click(screen.getByRole('button', { name: 'Send signing link' }));

    const panel = await screen.findByRole('region', { name: 'Signing link issued' });
    const box = within(panel).getByLabelText('Signing link') as HTMLInputElement;
    expect(box).toHaveAttribute('readonly');
    expect(box.value).toMatch(SIGNING_URL);
    expect(within(panel).queryByRole('link')).not.toBeInTheDocument();
    expect(document.querySelector(`a[href="${box.value}"]`)).toBeNull();
    expect(within(panel).getByText(/was emailed to the signer/)).toBeInTheDocument();
    expect(screen.getByText('Sent', { selector: '.badge' })).toHaveAttribute('data-status', 'sent');
    expect(screen.getByRole('button', { name: 'Re-send signing link' })).toBeInTheDocument();

    await user.click(within(panel).getByRole('button', { name: 'Copy link' }));
    expect(await within(panel).findByRole('status')).toHaveTextContent('Copied to clipboard');
    expect(writeText).toHaveBeenCalledWith(box.value);
  });

  it('posts send_email=false and expires_in_days from the form', async () => {
    let body: unknown = null;
    server.use(
      http.post(`${API_BASE_URL}/admin/contracts/${DRAFT_ID}/send`, async ({ request }) => {
        body = await request.json();
        const contract = { ...db.contracts[0]!, status: 'sent' as const, sent_at: '2026-09-26T10:00:00Z' };
        return HttpResponse.json({
          contract,
          signing_link: { url: 'http://localhost/sign/' + 'a'.repeat(43), expires_at: '2026-09-29T10:00:00Z' },
          email_sent: false,
        });
      }),
    );
    const user = userEvent.setup();
    renderApp(`/contracts/${DRAFT_ID}`);
    await screen.findByRole('button', { name: 'Send signing link' });
    await user.click(screen.getByLabelText('Also email the link to the signer'));
    expect(screen.queryByLabelText(/Personal note/)).not.toBeInTheDocument();
    const days = screen.getByLabelText('Link lifetime (days)');
    await user.clear(days);
    await user.type(days, '3');
    await user.click(screen.getByRole('button', { name: 'Send signing link' }));

    const panel = await screen.findByRole('region', { name: 'Signing link issued' });
    expect(body).toEqual({ send_email: false, expires_in_days: 3 });
    expect(within(panel).getByText(/was not emailed/)).toBeInTheDocument();
    expect(within(panel).getByText('2026-09-29 15:45 NPT')).toBeInTheDocument();
    expect(within(panel).getByText('2026-09-29 10:00 UTC')).toBeInTheDocument();
  });

  it('includes the personal note only when emailing', async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.post(`${API_BASE_URL}/admin/contracts/${SENT_ID}/send`, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          contract: db.contracts[1],
          signing_link: { url: 'http://localhost/sign/' + 'b'.repeat(43), expires_at: '2026-10-10T10:00:00Z' },
          email_sent: true,
        });
      }),
    );
    const user = userEvent.setup();
    renderApp(`/contracts/${SENT_ID}`);
    const button = await screen.findByRole('button', { name: 'Re-send signing link' });
    expect(screen.getByText(/immediately invalidates the previous one/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Personal note/), 'Please sign by Friday.');
    await user.click(button);
    await screen.findByRole('region', { name: 'Signing link issued' });
    expect(body).toEqual({ send_email: true, expires_in_days: 14, message: 'Please sign by Friday.' });
  });

  it('rejects an out-of-range link lifetime locally', async () => {
    const user = userEvent.setup();
    renderApp(`/contracts/${DRAFT_ID}`);
    await screen.findByRole('button', { name: 'Send signing link' });
    const days = screen.getByLabelText('Link lifetime (days)');
    await user.clear(days);
    await user.type(days, '31');
    await user.click(screen.getByRole('button', { name: 'Send signing link' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('between 1 and 30 days');
    expect(screen.queryByRole('region', { name: 'Signing link issued' })).not.toBeInTheDocument();
  });

  it('shows the 409 invalid_state message from the API', async () => {
    server.use(
      http.post(`${API_BASE_URL}/admin/contracts/${DRAFT_ID}/send`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'invalid_state',
              message: "Contract cannot be sent from status 'signed'.",
              details: { status: 'signed', allowed_from: ['draft', 'sent', 'viewed', 'expired'] },
            },
          },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp(`/contracts/${DRAFT_ID}`);
    await user.click(await screen.findByRole('button', { name: 'Send signing link' }));
    expect(await screen.findByRole('alert')).toHaveTextContent("Contract cannot be sent from status 'signed'.");
  });

  it('explains why an anonymized contract cannot be sent and shows the signer as Redacted', async () => {
    renderApp(`/contracts/${ANONYMIZED_ID}`);
    await screen.findByRole('heading', { name: 'Sunrise Homestay — Onboarding Agreement' });
    expect(screen.getByText('Redacted')).toBeInTheDocument();
    expect(screen.getByText(/removed by the retention policy/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /signing link/i })).not.toBeInTheDocument();
  });

  it('shows not found for an unknown id', async () => {
    renderApp('/contracts/00000000-0000-4000-8000-000000000000');
    expect(await screen.findByRole('alert')).toHaveTextContent('Not found.');
    expect(screen.getByRole('link', { name: 'Back to contracts' })).toBeInTheDocument();
  });
});
