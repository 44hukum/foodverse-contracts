import type { ContractStatus } from '../api/types';

const LABELS: Record<ContractStatus, string> = {
  draft: 'Draft',
  sent: 'Sent',
  viewed: 'Viewed',
  signed: 'Signed',
  expired: 'Expired',
  cancelled: 'Cancelled',
};

export function statusLabel(status: ContractStatus): string {
  return LABELS[status];
}
