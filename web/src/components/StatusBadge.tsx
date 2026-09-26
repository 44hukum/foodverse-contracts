import type { ContractStatus } from '../api/types';
import { statusLabel } from '../lib/status';

export function StatusBadge({ status }: { status: ContractStatus }) {
  return (
    <span className={`badge badge-${status}`} data-status={status}>
      {statusLabel(status)}
    </span>
  );
}
