/**
 * Signer-facing page at `/sign/:token` (SPEC.md §4 steps 4–7). Unauthenticated:
 * the token in the path is the signer's only credential. The token is read
 * from the route, sent in the request path, and never rendered as a link,
 * stored, or logged (CLAUDE.md rule 6).
 */
import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useParams } from 'react-router-dom';
import * as api from '../api/client';
import { ApiError } from '../api/client';
import type { PublicContract, SignatureResult, SubmitSignatureRequest } from '../api/types';
import { DualTime } from '../components/DualTime';
import { ErrorBanner } from '../components/ErrorBanner';
import { LinkProblemPage } from './LinkProblemPage';
import { SignaturePad } from './SignaturePad';
import {
  TYPED_NAME_MAX_LENGTH,
  classifyLinkError,
  formatBytes,
  isSigningTokenShape,
  isTerminalLinkError,
  validateSignatureImage,
  validateTypedName,
} from './signing';
import type { LinkProblem } from './signing';
import './sign.css';

type PageState =
  | { kind: 'loading' }
  | { kind: 'ready'; contract: PublicContract }
  | { kind: 'signed'; contract: PublicContract; result: SignatureResult }
  | { kind: 'problem'; problem: LinkProblem };

function DocumentPanel({ contract }: { contract: PublicContract }) {
  return (
    <section className="card" aria-labelledby="document-heading">
      <h2 id="document-heading">1. Review the document</h2>
      <iframe className="pdf-frame" src={contract.pdf.url} title={`${contract.title} (PDF)`} />
      <p className="small">
        If the preview does not load on your device,{' '}
        <a href={contract.pdf.url} target="_blank" rel="noopener noreferrer">
          open the PDF in a new tab
        </a>
        .
      </p>
      <dl className="details">
        <dt>Size</dt>
        <dd>{formatBytes(contract.pdf.size)}</dd>
        <dt>SHA-256</dt>
        <dd>
          <code className="hash">{contract.pdf.sha256}</code>
        </dd>
        <dt>Preview link valid until</dt>
        <dd>
          <DualTime iso={contract.pdf.expires_at} />
        </dd>
      </dl>
    </section>
  );
}

interface SignFormProps {
  token: string;
  contract: PublicContract;
  onSigned: (result: SignatureResult) => void;
  onLinkProblem: (problem: LinkProblem) => void;
}

function SignForm({ token, contract, onSigned, onLinkProblem }: SignFormProps) {
  const [typedName, setTypedName] = useState(contract.signer.name);
  const [nameTouched, setNameTouched] = useState(false);
  const [signature, setSignature] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const nameError = validateTypedName(typedName);
  const signatureError = validateSignatureImage(signature);
  const ready = !nameError && !signatureError && consent;

  const shownNameError = fieldErrors['typed_name'] ?? (nameTouched ? nameError : null);
  const shownSignatureError = fieldErrors['signature_image'] ?? (signature ? signatureError : null);
  const shownConsentError = fieldErrors['consent'] ?? null;
  const retryable = Boolean(error) && !(error instanceof ApiError && error.code === 'validation_error');

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (!ready || !signature) return;
    setError(null);
    setFieldErrors({});
    setSubmitting(true);
    const body: SubmitSignatureRequest = {
      typed_name: typedName.trim(),
      signature_image: signature,
      consent: true,
      consent_text_version: contract.consent_text_version,
    };
    try {
      onSigned(await api.submitSignature(token, body));
    } catch (err) {
      if (isTerminalLinkError(err)) {
        onLinkProblem(classifyLinkError(err));
        return;
      }
      if (err instanceof ApiError && err.code === 'validation_error') {
        setFieldErrors(err.fieldErrors());
      }
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      className="form sign-form"
      onSubmit={(event) => void onSubmit(event)}
      noValidate
      aria-labelledby="sign-heading"
    >
      <h2 id="sign-heading">2. Sign</h2>
      <ErrorBanner error={error} />
      {retryable && (
        <p className="hint">Nothing was signed. Your link is still valid, so you can try again.</p>
      )}

      <div className="field">
        <label htmlFor="typed-name">Full name</label>
        <input
          id="typed-name"
          type="text"
          name="typed_name"
          value={typedName}
          maxLength={TYPED_NAME_MAX_LENGTH}
          autoComplete="name"
          disabled={submitting}
          onChange={(event) => setTypedName(event.target.value)}
          onBlur={() => setNameTouched(true)}
          aria-invalid={Boolean(shownNameError)}
          aria-describedby="typed-name-hint typed-name-error"
        />
        <span id="typed-name-hint" className="hint">
          Type your name as it should appear on the document.
        </span>
        {shownNameError && (
          <span id="typed-name-error" className="field-error" role="alert">
            {shownNameError}
          </span>
        )}
      </div>

      <div className="field">
        <span className="field-label">Signature</span>
        <SignaturePad onChange={setSignature} disabled={submitting} />
        <span className="hint">Draw your signature with your finger or mouse.</span>
        {shownSignatureError && (
          <span className="field-error" role="alert">
            {shownSignatureError}
          </span>
        )}
      </div>

      <div className="field">
        <label className="consent">
          <input
            type="checkbox"
            name="consent"
            checked={consent}
            disabled={submitting}
            onChange={(event) => setConsent(event.target.checked)}
          />
          <span>{contract.consent_text}</span>
        </label>
        {shownConsentError && (
          <span className="field-error" role="alert">
            {shownConsentError}
          </span>
        )}
        <span className="hint">Consent text version {contract.consent_text_version}.</span>
      </div>

      <div className="sign-actions">
        <button type="submit" disabled={!ready || submitting}>
          {submitting ? 'Signing…' : 'Sign document'}
        </button>
        {!ready && (
          <span className="hint">
            Enter your name, draw your signature, and tick the box to enable signing.
          </span>
        )}
      </div>
    </form>
  );
}

function SignedPanel({ contract, result }: { contract: PublicContract; result: SignatureResult }) {
  return (
    <section className="card sign-done" aria-labelledby="signed-heading">
      <h1 id="signed-heading">Document signed</h1>
      <p>
        Thank you. “{contract.title}” has been signed and a copy has been emailed to{' '}
        {contract.signer.email}.
      </p>
      <dl className="details">
        <dt>Signed</dt>
        <dd>
          <DualTime iso={result.signed_at} />
        </dd>
        <dt>Signed PDF SHA-256</dt>
        <dd>
          <code className="hash">{result.final_pdf_sha256}</code>
        </dd>
      </dl>
      <p>
        <a
          className="button"
          href={result.download.url}
          target="_blank"
          rel="noopener noreferrer"
          download={result.download.filename}
        >
          Download signed PDF
        </a>
      </p>
      <p className="small">
        This download link is valid until <DualTime iso={result.download.expires_at} />
        The emailed copy does not expire.
      </p>
    </section>
  );
}

export function SignPage() {
  const { token = '' } = useParams();
  const [state, setState] = useState<PageState>({ kind: 'loading' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!isSigningTokenShape(token)) {
      setState({ kind: 'problem', problem: { kind: 'invalid', at: null, message: null } });
      return;
    }
    let cancelled = false;
    setState({ kind: 'loading' });
    api.getContractByToken(token).then(
      (contract) => {
        if (!cancelled) setState({ kind: 'ready', contract });
      },
      (err: unknown) => {
        if (!cancelled) setState({ kind: 'problem', problem: classifyLinkError(err) });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [token, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  let content;
  switch (state.kind) {
    case 'loading':
      content = <p role="status">Loading your document…</p>;
      break;
    case 'problem':
      content = <LinkProblemPage problem={state.problem} onRetry={retry} />;
      break;
    case 'signed':
      content = <SignedPanel contract={state.contract} result={state.result} />;
      break;
    case 'ready': {
      const { contract } = state;
      content = (
        <>
          <div className="sign-intro">
            <h1>{contract.title}</h1>
            <p className="muted">
              Sent by {contract.sent_by ?? 'Foodverse'} to {contract.signer.name} (
              {contract.signer.email}).
            </p>
            <p className="small">
              Sign before <DualTime iso={contract.expires_at} />
            </p>
          </div>
          <DocumentPanel contract={contract} />
          <section className="card">
            <SignForm
              token={token}
              contract={contract}
              onSigned={(result) => setState({ kind: 'signed', contract, result })}
              onLinkProblem={(problem) => setState({ kind: 'problem', problem })}
            />
          </section>
        </>
      );
      break;
    }
  }

  return (
    <div className="sign-page">
      <header className="sign-header">
        <span className="brand">Foodverse Contracts</span>
      </header>
      <main className="sign-main">{content}</main>
      <footer className="sign-footer small">
        Foodverse Contract Signing. Questions about this document? Contact the person who sent it.
      </footer>
    </div>
  );
}
