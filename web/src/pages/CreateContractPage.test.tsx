import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HttpResponse, http } from 'msw';
import { describe, expect, it } from 'vitest';
import { API_BASE_URL, MAX_PDF_BYTES } from '../config';
import { db } from '../mocks/data';
import { server } from '../mocks/server';
import { pdfFile, renderApp } from '../test/utils';

async function fillValidForm(user: ReturnType<typeof userEvent.setup>, file: File = pdfFile()) {
  await user.type(screen.getByLabelText('Title'), 'Hotel Aurora — Onboarding Agreement 2026');
  await user.upload(screen.getByLabelText('Contract PDF'), file);
  await user.type(screen.getByLabelText('Full name'), 'Maria Petrova');
  await user.type(screen.getByLabelText('Email'), 'maria@hotelaurora.example');
}

describe('CreateContractPage', () => {
  it('renders the fields the contract requires and no phone field', async () => {
    renderApp('/contracts/new');
    expect(await screen.findByRole('heading', { name: 'New contract' })).toBeInTheDocument();
    expect(screen.getByLabelText('Title')).toBeRequired();
    expect(screen.getByLabelText('Contract PDF')).toHaveAttribute('accept', 'application/pdf,.pdf');
    expect(screen.getByLabelText('Full name')).toBeRequired();
    expect(screen.getByLabelText('Email')).toHaveAttribute('type', 'email');
    expect(screen.getByLabelText(/Contract term end date/)).toHaveAttribute('type', 'date');
    expect(screen.queryByLabelText(/phone/i)).not.toBeInTheDocument();
  });

  it('validates locally and makes no request when fields are missing', async () => {
    let requests = 0;
    server.use(
      http.post(`${API_BASE_URL}/admin/contracts`, () => {
        requests += 1;
        return HttpResponse.json({}, { status: 500 });
      }),
    );
    const user = userEvent.setup();
    renderApp('/contracts/new');
    await user.click(await screen.findByRole('button', { name: 'Create contract' }));

    const alerts = await screen.findAllByRole('alert');
    const texts = alerts.map((a) => a.textContent);
    expect(texts).toEqual(
      expect.arrayContaining([
        'Title is required.',
        'Choose a PDF file.',
        'Signer name is required.',
        'Signer email is required.',
      ]),
    );
    expect(requests).toBe(0);
  });

  it('rejects a non-PDF file before upload', async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderApp('/contracts/new');
    await screen.findByRole('heading', { name: 'New contract' });
    const png = new File([new Uint8Array(16)], 'photo.png', { type: 'image/png' });
    await user.upload(screen.getByLabelText('Contract PDF'), png);
    await user.click(screen.getByRole('button', { name: 'Create contract' }));
    expect(await screen.findByText('Only PDF files are accepted.')).toBeInTheDocument();
  });

  it('rejects a PDF over 20 MB before upload', async () => {
    const user = userEvent.setup();
    renderApp('/contracts/new');
    await screen.findByRole('heading', { name: 'New contract' });
    const big = pdfFile('big.pdf', 16);
    Object.defineProperty(big, 'size', { value: MAX_PDF_BYTES + 1 });
    await fillValidForm(user, big);
    await user.click(screen.getByRole('button', { name: 'Create contract' }));
    expect(await screen.findByText('PDF must be 20 MB or smaller.')).toBeInTheDocument();
  });

  it('posts multipart/form-data matching CreateContractRequest and opens the new contract', async () => {
    let received: FormData | null = null;
    let contentType: string | null = null;
    server.use(
      http.post(`${API_BASE_URL}/admin/contracts`, async ({ request }) => {
        contentType = request.headers.get('content-type');
        received = await request.formData();
        const created = { ...db.contracts[0]!, id: 'c0000009-0000-4000-8000-000000000009', title: 'Created' };
        db.contracts.push(created);
        return HttpResponse.json(created, { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp('/contracts/new');
    await screen.findByRole('heading', { name: 'New contract' });
    await fillValidForm(user);
    await user.type(screen.getByLabelText(/Contract term end date/), '2028-12-31');
    await user.click(screen.getByRole('button', { name: 'Create contract' }));

    expect(await screen.findByRole('heading', { name: 'Created' })).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Contract created.');

    expect(contentType).toMatch(/^multipart\/form-data; boundary=/);
    const form = received!;
    expect(form.get('title')).toBe('Hotel Aurora — Onboarding Agreement 2026');
    expect(form.get('signer_name')).toBe('Maria Petrova');
    expect(form.get('signer_email')).toBe('maria@hotelaurora.example');
    expect(form.get('term_end_date')).toBe('2028-12-31');
    const file = form.get('file') as File;
    expect(file.name).toBe('contract.pdf');
    expect(file.type).toBe('application/pdf');
    expect(file.size).toBe(1024);
    expect([...form.keys()].sort()).toEqual(['file', 'signer_email', 'signer_name', 'term_end_date', 'title']);
  });

  it('omits term_end_date when left blank', async () => {
    let keys: string[] = [];
    server.use(
      http.post(`${API_BASE_URL}/admin/contracts`, async ({ request }) => {
        keys = [...(await request.formData()).keys()];
        return HttpResponse.json(db.contracts[0], { status: 201 });
      }),
    );
    const user = userEvent.setup();
    renderApp('/contracts/new');
    await screen.findByRole('heading', { name: 'New contract' });
    await fillValidForm(user);
    await user.click(screen.getByRole('button', { name: 'Create contract' }));
    await screen.findByRole('heading', { name: db.contracts[0]!.title });
    expect(keys).not.toContain('term_end_date');
  });

  it('creates a draft through the mock API end to end', async () => {
    const user = userEvent.setup();
    renderApp('/contracts/new');
    await screen.findByRole('heading', { name: 'New contract' });
    await fillValidForm(user);
    await user.click(screen.getByRole('button', { name: 'Create contract' }));
    expect(
      await screen.findByRole('heading', { name: 'Hotel Aurora — Onboarding Agreement 2026' }),
    ).toBeInTheDocument();
    expect(screen.getByText('Draft', { selector: '.badge' })).toHaveAttribute('data-status', 'draft');
    expect(screen.getByRole('button', { name: 'Send signing link' })).toBeInTheDocument();
  });

  it('maps a 422 validation_error onto the offending field', async () => {
    server.use(
      http.post(`${API_BASE_URL}/admin/contracts`, () =>
        HttpResponse.json(
          {
            error: {
              code: 'validation_error',
              message: 'One or more fields are invalid.',
              details: { fields: [{ field: 'signer_email', message: 'Not a valid email address.' }] },
            },
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp('/contracts/new');
    await screen.findByRole('heading', { name: 'New contract' });
    await fillValidForm(user);
    await user.click(screen.getByRole('button', { name: 'Create contract' }));
    expect(await screen.findByText('Not a valid email address.')).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true');
  });

  it('shows unsupported_media_type and payload_too_large messages from the API', async () => {
    server.use(
      http.post(`${API_BASE_URL}/admin/contracts`, () =>
        HttpResponse.json(
          { error: { code: 'unsupported_media_type', message: 'Only PDF files are accepted.' } },
          { status: 415 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp('/contracts/new');
    await screen.findByRole('heading', { name: 'New contract' });
    await fillValidForm(user);
    await user.click(screen.getByRole('button', { name: 'Create contract' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Only PDF files are accepted.');
  });
});
