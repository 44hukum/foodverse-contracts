import { useCallback, useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import * as api from '../api/client';
import { CONTRACT_STATUSES } from '../api/types';
import type { ContractStatus, ContractSummary, ListContractsQuery } from '../api/types';
import { DualTime } from '../components/DualTime';
import { ErrorBanner } from '../components/ErrorBanner';
import { StatusBadge } from '../components/StatusBadge';
import { statusLabel } from '../lib/status';

const PAGE_SIZE = 25;

function isStatus(value: string): value is ContractStatus {
  return (CONTRACT_STATUSES as readonly string[]).includes(value);
}

export function SignerCell({ contract }: { contract: Pick<ContractSummary, 'signer_name' | 'signer_email' | 'anonymized_at'> }) {
  if (contract.anonymized_at || (contract.signer_name === null && contract.signer_email === null)) {
    return <span className="muted">Redacted</span>;
  }
  return (
    <span className="signer">
      <span>{contract.signer_name ?? '—'}</span>
      <span className="muted">{contract.signer_email ?? '—'}</span>
    </span>
  );
}

/** The date that best tells the admin where the contract is in its life. */
function progressDate(contract: ContractSummary): { label: string; iso: string | null | undefined } {
  switch (contract.status) {
    case 'signed':
      return { label: 'Signed', iso: contract.signed_at };
    case 'cancelled':
      return { label: 'Cancelled', iso: contract.cancelled_at };
    case 'expired':
      return { label: 'Expired', iso: contract.expires_at };
    case 'sent':
    case 'viewed':
      return { label: 'Expires', iso: contract.expires_at };
    case 'draft':
      return { label: 'Not sent', iso: null };
  }
}

export function ContractListPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = searchParams.getAll('status').filter(isStatus);
  const q = searchParams.get('q') ?? '';
  const [search, setSearch] = useState(q);

  const [items, setItems] = useState<ContractSummary[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const selectedKey = selected.join(',');

  const load = useCallback(
    async (cursor: string | null) => {
      const statuses = selectedKey ? (selectedKey.split(',') as ContractStatus[]) : [];
      const query: ListContractsQuery = { limit: PAGE_SIZE };
      if (statuses.length) query.status = statuses;
      if (q) query.q = q;
      if (cursor) query.cursor = cursor;
      return api.listContracts(query);
    },
    [selectedKey, q],
  );

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    load(null)
      .then((page) => {
        if (cancelled) return;
        setItems(page.items);
        setNextCursor(page.next_cursor);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [load]);

  function toggleStatus(status: ContractStatus): void {
    const next = new URLSearchParams(searchParams);
    const current = new Set(next.getAll('status'));
    if (current.has(status)) current.delete(status);
    else current.add(status);
    next.delete('status');
    for (const s of CONTRACT_STATUSES) if (current.has(s)) next.append('status', s);
    setSearchParams(next, { replace: true });
  }

  function clearFilters(): void {
    const next = new URLSearchParams(searchParams);
    next.delete('status');
    setSearchParams(next, { replace: true });
  }

  function onSearch(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const next = new URLSearchParams(searchParams);
    if (search.trim()) next.set('q', search.trim());
    else next.delete('q');
    setSearchParams(next, { replace: true });
  }

  async function loadMore(): Promise<void> {
    if (!nextCursor) return;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await load(nextCursor);
      setItems((prev) => [...prev, ...page.items]);
      setNextCursor(page.next_cursor);
    } catch (err) {
      setError(err);
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1>Contracts</h1>
        <Link to="/contracts/new" className="button">
          New contract
        </Link>
      </div>

      <div className="toolbar">
        <fieldset className="status-filter">
          <legend>Filter by status</legend>
          {CONTRACT_STATUSES.map((status) => {
            const active = selected.includes(status);
            return (
              <button
                key={status}
                type="button"
                className={`chip${active ? ' chip-active' : ''}`}
                aria-pressed={active}
                onClick={() => toggleStatus(status)}
              >
                {statusLabel(status)}
              </button>
            );
          })}
          {selected.length > 0 && (
            <button type="button" className="link-button" onClick={clearFilters}>
              Clear
            </button>
          )}
        </fieldset>
        <form className="search" onSubmit={onSearch} role="search">
          <input
            type="search"
            aria-label="Search contracts"
            placeholder="Search title, signer name or email"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            maxLength={200}
          />
          <button type="submit">Search</button>
        </form>
      </div>

      <ErrorBanner error={error} />

      {loading ? (
        <p role="status">Loading contracts…</p>
      ) : items.length === 0 ? (
        <p className="empty" role="status">
          No contracts{selected.length || q ? ' match these filters' : ' yet'}.
        </p>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th scope="col">Title</th>
              <th scope="col">Status</th>
              <th scope="col">Signer</th>
              <th scope="col">Created</th>
              <th scope="col">Sent</th>
              <th scope="col">Progress</th>
              <th scope="col">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((contract) => {
              const progress = progressDate(contract);
              return (
                <tr key={contract.id} data-testid="contract-row">
                  <td>
                    <Link to={`/contracts/${contract.id}`}>{contract.title}</Link>
                  </td>
                  <td>
                    <StatusBadge status={contract.status} />
                  </td>
                  <td>
                    <SignerCell contract={contract} />
                  </td>
                  <td>
                    <DualTime iso={contract.created_at} />
                  </td>
                  <td>
                    <DualTime iso={contract.sent_at} />
                  </td>
                  <td>
                    <span className="muted small">{progress.label}</span>
                    <DualTime iso={progress.iso} emptyText="" />
                  </td>
                  <td>
                    <Link to={`/contracts/${contract.id}`} aria-label={`Open ${contract.title}`}>
                      Open
                    </Link>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {nextCursor && !loading && (
        <div className="load-more">
          <button type="button" onClick={() => void loadMore()} disabled={loadingMore}>
            {loadingMore ? 'Loading…' : 'Load more'}
          </button>
        </div>
      )}
    </div>
  );
}
