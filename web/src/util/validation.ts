import { MAX_PDF_BYTES } from '../config';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isEmail(value: string): boolean {
  return value.length <= 320 && EMAIL_RE.test(value);
}

/** Client-side mirror of the upload rules in SPEC.md §7. The API is the authority. */
export function validatePdfFile(file: File | null | undefined): string | null {
  if (!file) return 'Choose a PDF file.';
  const looksLikePdf = file.type === 'application/pdf' || /\.pdf$/i.test(file.name);
  if (!looksLikePdf) return 'Only PDF files are accepted.';
  if (file.size === 0) return 'The selected file is empty.';
  if (file.size > MAX_PDF_BYTES) return 'PDF must be 20 MB or smaller.';
  return null;
}

export interface CreateContractFields {
  title: string;
  signer_name: string;
  signer_email: string;
  term_end_date: string;
  file: File | null;
}

export type FieldErrors<T> = Partial<Record<keyof T, string>>;

export function validateCreateContract(fields: CreateContractFields): FieldErrors<CreateContractFields> {
  const errors: FieldErrors<CreateContractFields> = {};
  const title = fields.title.trim();
  if (title.length === 0) errors.title = 'Title is required.';
  else if (title.length > 200) errors.title = 'Title must be 200 characters or fewer.';

  const name = fields.signer_name.trim();
  if (name.length === 0) errors.signer_name = 'Signer name is required.';
  else if (name.length > 200) errors.signer_name = 'Signer name must be 200 characters or fewer.';

  const email = fields.signer_email.trim();
  if (email.length === 0) errors.signer_email = 'Signer email is required.';
  else if (!isEmail(email)) errors.signer_email = 'Enter a valid email address.';

  if (fields.term_end_date && !/^\d{4}-\d{2}-\d{2}$/.test(fields.term_end_date)) {
    errors.term_end_date = 'Enter a date as YYYY-MM-DD.';
  }

  const fileError = validatePdfFile(fields.file);
  if (fileError) errors.file = fileError;
  return errors;
}
