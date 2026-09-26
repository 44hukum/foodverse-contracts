import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import * as api from '../api/client';
import { SENDABLE_STATUSES } from '../api/types';
import type {
  ContractDetail,
  SendContractRequest,
  SendContractResponse,
  SigningLink,
} from '../api/types';
import {
  SIGNING_LINK_TTL_DAYS_DEFAULT,
  SIGNING_LINK_TTL_DAYS_MAX,
  SIGNING_LINK_TTL_DAYS_MIN,
} from '../config';
import { CopyBox } from '../components/CopyBox';
import { DualTime } from '../components/DualTime';
import { ErrorBanner } from '../components/ErrorBanner';
import { StatusBadge } from '../components/StatusBadge';
import { formatDate } from '../util/dates';
import { SignerCell } from './ContractListPage';

interface IssuedLink {
  link: SigningLink;
  emailSent: boolean;
}

function SendPanel({
  contract,
  onSent,
}: {
  contract: ContractDetail;
  onSent: (result: SendContractResponse) => void;
}) {
  const [sendEmail, setSendEmail] = useState(true);
  const [days, setDays] = useState(String(SIGNING_LINK_TTL_DAYS_DEFAULT));
  const [message, setMessage] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [daysError, setDaysError] = useState<string | null>(null);

  const sendable = SENDABLE_STATUSES.includes(contract.status) && !contract.anonymized_at;
  const isResend = contract.status === 'sent' || contract.status === 'viewed';

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setError(null);
    const parsed = Number(days);
    if (
      !Number.isInteger(parsed) ||
      parsed < SIGNING_LINK_TTL_DAYS_MIN ||
      parsed > SIGNING_LINK_TTL_DAYS_MAX
    ) {
      setDaysError(
        `Link lifetime must be between ${SIGNING_LINK_TTL_DAYS_MIN} and ${SIGNING_LINK_TTL_DAYS_MAX} days.`,
      );
      return;
    }
    setDaysError(null);
    const body: SendContractRequest = { send_email: sendEmail, expires_in_days: parsed };
    if (sendEmail && message.trim()) body.message = message.trim();
    setSubmitting(true);
    try {
      onSent(await api.sendContractLink(contract.id, body));
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  if (!sendable) {
    return (
      <p className="muted">
        {contract.anonymized_at
          ? 'Signer data was removed by the retention policy; this contract cannot be sent.'
          : `A contract in status “${contract.status}” cannot be sent.`}
      </p>
    );
  }

  return (
    <form className="form" onSubmit={(event) => void onSubmit(event)} noValidate>
      <ErrorBanner error={error} />
      {isResend && (
        <p className="hint">
          Re-sending issues a new link and immediately invalidates the previous one.
        </p>
      )}
      <label className="checkbox">
        <input
          type="checkbox"
          name="send_email"
          checked={sendEmail}
          onChange={(event) => setSendEmail(event.target.checked)}
        />
        Also email the link to the signer
      </label>
      <label>
        Link lifetime (days)
        <input
          type="number"
          name="expires_in_days"
          min={SIGNING_LINK_TTL_DAYS_MIN}
          max={SIGNING_LINK_TTL_DAYS_MAX}
          value={days}
          onChange={(event) => setDays(event.target.value)}
          aria-invalid={Boolean(daysError)}
          aria-describedby="days-error"
        />
        {daysError && (
          <span id="days-error" className="field-error" role="alert">
            {daysError}
          </span>
        )}
      </label>
      {sendEmail && (
        <label>
          Personal note <span className="muted">(optional, included in the email)</span>
          <textarea
            name="message"
            maxLength={1000}
            rows={3}
            value={message}
            onChange={(event) => setMessage(event.target.value)}
          />
        </label>
      )}
      <div className="actions">
        <button type="submit" disabled={submitting}>
          {submitting ? 'Sending…' : isResend ? 'Re-send signing link' : 'Send signing link'}
        </button>
      </div>
    </form>
  );
}

export function ContractDetailPage() {
  const { contractId = '' } = useParams();
  const location = useLocation();
  const justCreated = Boolean((location.state as { justCreated?: boolean } | null)?.justCreated);

  const [contract, setContract] = useState<ContractDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [issued, setIssued] = useState<IssuedLink | null>(null);

  const reload = useCallback(async () => {
    setError(null);
    try {
      setContract(await api.getContract(contractId));
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [contractId]);

  useEffect(() => {
    void reload();
  }, [reload]);

  function onSent(result: SendContractResponse): void {
    setContract(result.contract);
    setIssued({ link: result.signing_link, emailSent: result.email_sent });
  }

  if (loading) return <p role="status">Loading contract…</p>;
  if (!contract) {
    return (
      <div>
        <ErrorBanner error={error ?? new Error('Contract not found.')} />
        <Link to="/contracts">Back to contracts</Link>
      </div>
    );
  }

  return (
    <div>
      <p>
        <Link to="/contracts">← All contracts</Link>
      </p>
      <div className="page-header">
        <h1>{contract.title}</h1>
        <StatusBadge status={contract.status} />
      </div>
      {justCreated && !issued && (
        <div role="status" className="banner banner-info">
          Contract created. Send the signing link when you are ready.
        </div>
      )}
      <ErrorBanner error={error} />

      {issued && (
        <section className="card link-issued" aria-labelledby="link-issued-heading">
          <h2 id="link-issued-heading">Signing link issued</h2>
          <p>
            {issued.emailSent
              ? 'The link was emailed to the signer. You can also copy it and share it directly.'
              : 'The link was not emailed. Copy it and share it with the signer.'}{' '}
            It is shown once; re-send to get a new one.
          </p>
          <CopyBox value={issued.link.url} label="Signing link" />
          <p className="small">
            Expires <DualTime iso={issued.link.expires_at} />
          </p>
        </section>
      )}

      <div className="grid-2">
        <section className="card" aria-labelledby="details-heading">
          <h2 id="details-heading">Details</h2>
          <dl className="details">
            <dt>Signer</dt>
            <dd>
              <SignerCell contract={contract} />
            </dd>
            <dt>Created</dt>
            <dd>
              <DualTime iso={contract.created_at} />
            </dd>
            <dt>Sent</dt>
            <dd>
              <DualTime iso={contract.sent_at} />
            </dd>
            <dt>First viewed</dt>
            <dd>
              <DualTime iso={contract.first_viewed_at} />
            </dd>
            <dt>Link expires</dt>
            <dd>
              <DualTime iso={contract.expires_at} />
            </dd>
            <dt>Signed</dt>
            <dd>
              <DualTime iso={contract.signed_at} />
            </dd>
            <dt>Term end date</dt>
            <dd>{formatDate(contract.term_end_date)}</dd>
            <dt>Retain until</dt>
            <dd>{formatDate(contract.retain_until)}</dd>
            <dt>Original PDF</dt>
            <dd>
              {contract.original_pdf_size.toLocaleString()} bytes
              <br />
              <code className="hash">{contract.original_pdf_sha256}</code>
            </dd>
            {contract.final_pdf_sha256 && (
              <>
                <dt>Signed PDF SHA-256</dt>
                <dd>
                  <code className="hash">{contract.final_pdf_sha256}</code>
                </dd>
              </>
            )}
          </dl>
        </section>

        <section className="card" aria-labelledby="send-heading">
          <h2 id="send-heading">Signing link</h2>
          <SendPanel key={contract.updated_at} contract={contract} onSent={onSent} />
        </section>
      </div>

      <section className="card" aria-labelledby="events-heading">
        <h2 id="events-heading">Audit trail</h2>
        {contract.events.length === 0 ? (
          <p className="muted">No events.</p>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Event</th>
                <th scope="col">Actor</th>
                <th scope="col">When</th>
              </tr>
            </thead>
            <tbody>
              {contract.events.map((event) => (
                <tr key={event.id}>
                  <td>
                    <code>{event.event_type}</code>
                  </td>
                  <td>{event.actor_type}</td>
                  <td>
                    <DualTime iso={event.occurred_at} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
