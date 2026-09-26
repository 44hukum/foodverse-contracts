import { useState } from 'react';
import type { ChangeEvent, FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import * as api from '../api/client';
import { ApiError } from '../api/client';
import { MAX_PDF_BYTES } from '../config';
import { ErrorBanner } from '../components/ErrorBanner';
import { validateCreateContract } from '../lib/validation';
import type { CreateContractFields, FieldErrors } from '../lib/validation';

const EMPTY: CreateContractFields = {
  title: '',
  signer_name: '',
  signer_email: '',
  term_end_date: '',
  file: null,
};

function FieldError({ id, message }: { id: string; message: string | undefined }) {
  if (!message) return null;
  return (
    <span id={id} className="field-error" role="alert">
      {message}
    </span>
  );
}

export function CreateContractPage() {
  const navigate = useNavigate();
  const [fields, setFields] = useState<CreateContractFields>(EMPTY);
  const [errors, setErrors] = useState<FieldErrors<CreateContractFields>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);

  function update<K extends keyof CreateContractFields>(key: K, value: CreateContractFields[K]): void {
    setFields((prev) => ({ ...prev, [key]: value }));
    setErrors((prev) => ({ ...prev, [key]: undefined }));
  }

  function onFile(event: ChangeEvent<HTMLInputElement>): void {
    update('file', event.target.files?.[0] ?? null);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    const nextErrors = validateCreateContract(fields);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0 || !fields.file) return;

    setSubmitting(true);
    try {
      const input: api.CreateContractInput = {
        file: fields.file,
        title: fields.title.trim(),
        signer_name: fields.signer_name.trim(),
        signer_email: fields.signer_email.trim(),
      };
      if (fields.term_end_date) input.term_end_date = fields.term_end_date;
      const created = await api.createContract(input);
      navigate(`/contracts/${created.id}`, { state: { justCreated: true } });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'validation_error') {
        const serverErrors = err.fieldErrors();
        setErrors((prev) => ({ ...prev, ...serverErrors }));
        if (Object.keys(serverErrors).length === 0) setError(err);
      } else {
        setError(err);
      }
    } finally {
      setSubmitting(false);
    }
  }

  const maxMb = Math.round(MAX_PDF_BYTES / (1024 * 1024));

  return (
    <div className="narrow">
      <h1>New contract</h1>
      <p className="muted">
        Upload the finished PDF and add the signer. Nothing is sent until you press
        “Send signing link” on the next screen.
      </p>
      <ErrorBanner error={error} />
      <form className="card form" onSubmit={(event) => void onSubmit(event)} noValidate>
        <div className="field">
          <label htmlFor="title">Title</label>
          <input
            id="title"
            type="text"
            name="title"
            value={fields.title}
            maxLength={200}
            onChange={(event) => update('title', event.target.value)}
            aria-invalid={Boolean(errors.title)}
            aria-describedby="title-error"
            required
          />
          <FieldError id="title-error" message={errors.title} />
        </div>

        <div className="field">
          <label htmlFor="file">Contract PDF</label>
          <input
            id="file"
            type="file"
            name="file"
            accept="application/pdf,.pdf"
            onChange={onFile}
            aria-invalid={Boolean(errors.file)}
            aria-describedby="file-error file-hint"
            required
          />
          <span id="file-hint" className="hint">
            PDF only, up to {maxMb} MB.
          </span>
          <FieldError id="file-error" message={errors.file} />
        </div>

        <fieldset>
          <legend>Signer</legend>
          <div className="field">
            <label htmlFor="signer_name">Full name</label>
            <input
              id="signer_name"
              type="text"
              name="signer_name"
              value={fields.signer_name}
              maxLength={200}
              onChange={(event) => update('signer_name', event.target.value)}
              aria-invalid={Boolean(errors.signer_name)}
              aria-describedby="signer-name-error"
              required
            />
            <FieldError id="signer-name-error" message={errors.signer_name} />
          </div>
          <div className="field">
            <label htmlFor="signer_email">Email</label>
            <input
              id="signer_email"
              type="email"
              name="signer_email"
              value={fields.signer_email}
              maxLength={320}
              onChange={(event) => update('signer_email', event.target.value)}
              aria-invalid={Boolean(errors.signer_email)}
              aria-describedby="signer-email-error"
              required
            />
            <FieldError id="signer-email-error" message={errors.signer_email} />
          </div>
        </fieldset>

        <div className="field">
          <label htmlFor="term_end_date">
            Contract term end date <span className="muted">(optional)</span>
          </label>
          <input
            id="term_end_date"
            type="date"
            name="term_end_date"
            value={fields.term_end_date}
            onChange={(event) => update('term_end_date', event.target.value)}
            aria-invalid={Boolean(errors.term_end_date)}
            aria-describedby="term-end-error term-end-hint"
          />
          <span id="term-end-hint" className="hint">
            Used for the retention date (term end + 7 years). Falls back to the signing date.
          </span>
          <FieldError id="term-end-error" message={errors.term_end_date} />
        </div>

        <div className="actions">
          <button type="submit" disabled={submitting}>
            {submitting ? 'Creating…' : 'Create contract'}
          </button>
        </div>
      </form>
    </div>
  );
}
