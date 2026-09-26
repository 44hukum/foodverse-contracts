import { formatDual } from '../util/dates';

/** Renders a UTC instant as Kathmandu time with UTC underneath (rule 14). */
export function DualTime({ iso, emptyText = '—' }: { iso: string | null | undefined; emptyText?: string }) {
  const dual = formatDual(iso);
  if (!dual) return <span className="muted">{emptyText}</span>;
  return (
    <time dateTime={iso ?? undefined} className="dual-time">
      <span className="dual-time-local">{dual.local}</span>
      <span className="dual-time-utc">{dual.utc}</span>
    </time>
  );
}
