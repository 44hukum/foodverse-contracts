import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { describe, expect, it } from 'vitest';
import { API_BASE_URL } from '../config';
import { db } from '../mocks/data';
import { server } from '../mocks/server';
import { renderApp } from '../test/utils';

async function rows(): Promise<HTMLElement[]> {
  await screen.findByRole('table');
  return screen.getAllByTestId('contract-row');
}

describe('ContractListPage', () => {
  it('lists every contract newest first with a status badge, signer, and dates in NPT and UTC', async () => {
    renderApp('/contracts');
    const list = await rows();
    expect(list).toHaveLength(db.contracts.length);

    const first = list[0]!;
    expect(within(first).getByRole('link', { name: 'Hotel Aurora — Onboarding Agreement 2026' })).toBeInTheDocument();
    expect(within(first).getByText('Draft', { selector: '.badge' })).toHaveAttribute('data-status', 'draft');
    expect(within(first).getByText('Maria Petrova')).toBeInTheDocument();
    expect(within(first).getByText('maria@hotelaurora.example')).toBeInTheDocument();
    // created_at 2026-09-25T09:15:00Z -> 15:00 in Kathmandu
    expect(within(first).getByText('2026-09-25 15:00 NPT')).toBeInTheDocument();
    expect(within(first).getByText('2026-09-25 09:15 UTC')).toBeInTheDocument();

    const statuses = list.map((row) => within(row).getByText(/^(Draft|Sent|Viewed|Signed|Expired|Cancelled)$/, { selector: '.badge' }).getAttribute('data-status'));
    expect(statuses).toEqual(['draft', 'sent', 'viewed', 'signed', 'expired', 'cancelled', 'expired']);
  });

  it('shows "Redacted" for a contract whose signer was anonymized', async () => {
    renderApp('/contracts');
    const list = await rows();
    const anonymized = list.find((row) => within(row).queryByText('Sunrise Homestay — Onboarding Agreement'));
    expect(anonymized).toBeDefined();
    expect(within(anonymized!).getByText('Redacted')).toBeInTheDocument();
  });

  it('filters by status with repeated status query params and reflects the filter in the URL', async () => {
    const seen: string[][] = [];
    server.use(
      http.get(`${API_BASE_URL}/admin/contracts`, ({ request }) => {
        const params = new URL(request.url).searchParams;
        seen.push(params.getAll('status'));
        const statuses = params.getAll('status');
        const items = db.contracts.filter((c) => !statuses.length || statuses.includes(c.status));
        return HttpResponse.json({ items, next_cursor: null });
      }),
    );
    const user = userEvent.setup();
    renderApp('/contracts');
    await rows();

    await user.click(screen.getByRole('button', { name: 'Signed' }));
    expect(await screen.findByRole('button', { name: 'Signed', pressed: true })).toBeInTheDocument();
    const signedOnly = await rows();
    expect(signedOnly).toHaveLength(1);
    expect(within(signedOnly[0]!).getByText('Everest Bakery — Supplier Agreement')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Expired' }));
    await screen.findByRole('button', { name: 'Expired', pressed: true });
    expect(await rows()).toHaveLength(3);

    expect(seen).toEqual([[], ['signed'], ['signed', 'expired']]);

    await user.click(screen.getByRole('button', { name: 'Clear' }));
    expect(await rows()).toHaveLength(db.contracts.length);
  });

  it('starts from a status filter present in the URL', async () => {
    renderApp('/contracts?status=draft');
    const list = await rows();
    expect(list).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Draft', pressed: true })).toBeInTheDocument();
  });

  it('searches by title, signer name, or signer email', async () => {
    const user = userEvent.setup();
    renderApp('/contracts');
    await rows();
    await user.type(screen.getByLabelText('Search contracts'), 'lakeside');
    await user.click(screen.getByRole('button', { name: 'Search' }));
    const list = await rows();
    expect(list).toHaveLength(1);
    expect(within(list[0]!).getByText('Anita Gurung')).toBeInTheDocument();
  });

  it('shows an empty state when nothing matches', async () => {
    server.use(
      http.get(`${API_BASE_URL}/admin/contracts`, () => HttpResponse.json({ items: [], next_cursor: null })),
    );
    renderApp('/contracts?status=cancelled');
    expect(await screen.findByText('No contracts match these filters.')).toBeInTheDocument();
  });

  it('loads the next page with the cursor', async () => {
    const user = userEvent.setup();
    server.use(
      http.get(`${API_BASE_URL}/admin/contracts`, ({ request }) => {
        const cursor = new URL(request.url).searchParams.get('cursor');
        if (!cursor) return HttpResponse.json({ items: db.contracts.slice(0, 2), next_cursor: 'page-2' });
        expect(cursor).toBe('page-2');
        return HttpResponse.json({ items: db.contracts.slice(2, 4), next_cursor: null });
      }),
    );
    renderApp('/contracts');
    expect(await rows()).toHaveLength(2);
    await user.click(screen.getByRole('button', { name: 'Load more' }));
    expect(await screen.findAllByTestId('contract-row')).toHaveLength(4);
    expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument();
  });

  it('shows the API error message when the list fails', async () => {
    server.use(
      http.get(`${API_BASE_URL}/admin/contracts`, () =>
        HttpResponse.json(
          { error: { code: 'internal_error', message: 'Something went wrong. Reference id 7f3c1b2e.' } },
          { status: 500 },
        ),
      ),
    );
    renderApp('/contracts');
    expect(await screen.findByRole('alert')).toHaveTextContent('Reference id 7f3c1b2e');
  });
});
