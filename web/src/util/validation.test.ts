import { describe, expect, it } from 'vitest';
import { MAX_PDF_BYTES } from '../config';
import { validateCreateContract, validatePdfFile } from './validation';

function file(name: string, type: string, size: number): File {
  const f = new File(['x'], name, { type });
  Object.defineProperty(f, 'size', { value: size });
  return f;
}

describe('validatePdfFile', () => {
  it('requires a file', () => {
    expect(validatePdfFile(null)).toBe('Choose a PDF file.');
  });

  it('rejects non-PDF files by type and extension', () => {
    expect(validatePdfFile(file('photo.png', 'image/png', 10))).toBe('Only PDF files are accepted.');
  });

  it('accepts a .pdf extension when the browser reports no type', () => {
    expect(validatePdfFile(file('contract.pdf', '', 10))).toBeNull();
  });

  it('enforces the 20 MB limit without weakening it', () => {
    expect(validatePdfFile(file('a.pdf', 'application/pdf', MAX_PDF_BYTES))).toBeNull();
    expect(validatePdfFile(file('a.pdf', 'application/pdf', MAX_PDF_BYTES + 1))).toBe(
      'PDF must be 20 MB or smaller.',
    );
    expect(MAX_PDF_BYTES).toBe(20971520);
  });

  it('rejects empty files', () => {
    expect(validatePdfFile(file('a.pdf', 'application/pdf', 0))).toBe('The selected file is empty.');
  });
});

describe('validateCreateContract', () => {
  const valid = {
    title: 'Hotel Aurora — Onboarding Agreement 2026',
    signer_name: 'Maria Petrova',
    signer_email: 'maria@hotelaurora.example',
    term_end_date: '',
    file: file('contract.pdf', 'application/pdf', 100),
  };

  it('passes a complete form', () => {
    expect(validateCreateContract(valid)).toEqual({});
  });

  it('flags every missing required field at once', () => {
    const errors = validateCreateContract({
      title: '  ',
      signer_name: '',
      signer_email: '',
      term_end_date: '',
      file: null,
    });
    expect(Object.keys(errors).sort()).toEqual(['file', 'signer_email', 'signer_name', 'title']);
  });

  it('checks email shape, length limits, and the optional date format', () => {
    expect(validateCreateContract({ ...valid, signer_email: 'not-an-email' }).signer_email).toMatch(
      /valid email/,
    );
    expect(validateCreateContract({ ...valid, title: 'x'.repeat(201) }).title).toMatch(/200/);
    expect(validateCreateContract({ ...valid, term_end_date: '31/12/2028' }).term_end_date).toMatch(
      /YYYY-MM-DD/,
    );
    expect(validateCreateContract({ ...valid, term_end_date: '2028-12-31' })).toEqual({});
  });
});
