/**
 * Human-facing timestamps show Asia/Kathmandu and UTC side by side
 * (CLAUDE.md rule 14). The API and storage stay UTC; conversion happens here,
 * at the rendering edge only.
 */
import { DISPLAY_TIMEZONE, DISPLAY_TIMEZONE_LABEL } from '../config';

export interface DualTimestamp {
  /** e.g. `2026-09-28 20:07 NPT` */
  local: string;
  /** e.g. `2026-09-28 14:22 UTC` */
  utc: string;
}

function parts(date: Date, timeZone: string): string {
  const fmt = new Intl.DateTimeFormat('en-GB', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  });
  const map: Record<string, string> = {};
  for (const part of fmt.formatToParts(date)) {
    if (part.type !== 'literal') map[part.type] = part.value;
  }
  return `${map['year']}-${map['month']}-${map['day']} ${map['hour']}:${map['minute']}`;
}

/** Returns null for null/undefined/unparseable input so callers can render a dash. */
export function formatDual(iso: string | null | undefined): DualTimestamp | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return {
    local: `${parts(date, DISPLAY_TIMEZONE)} ${DISPLAY_TIMEZONE_LABEL}`,
    utc: `${parts(date, 'UTC')} UTC`,
  };
}

/** Plain calendar dates (term end, retain until) carry no timezone; show as-is. */
export function formatDate(isoDate: string | null | undefined): string {
  return isoDate ? isoDate : '—';
}
