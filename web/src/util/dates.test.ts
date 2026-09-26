import { describe, expect, it } from 'vitest';
import { formatDate, formatDual } from './dates';

describe('formatDual', () => {
  it('renders Asia/Kathmandu (UTC+05:45) and UTC for the same instant', () => {
    expect(formatDual('2026-09-28T14:22:10Z')).toEqual({
      local: '2026-09-28 20:07 NPT',
      utc: '2026-09-28 14:22 UTC',
    });
  });

  it('rolls the local date forward when the offset crosses midnight', () => {
    expect(formatDual('2026-10-10T19:00:00Z')).toEqual({
      local: '2026-10-11 00:45 NPT',
      utc: '2026-10-10 19:00 UTC',
    });
  });

  it('returns null for missing or unparseable values', () => {
    expect(formatDual(null)).toBeNull();
    expect(formatDual(undefined)).toBeNull();
    expect(formatDual('')).toBeNull();
    expect(formatDual('not a date')).toBeNull();
  });
});

describe('formatDate', () => {
  it('passes calendar dates through and dashes nulls', () => {
    expect(formatDate('2028-12-31')).toBe('2028-12-31');
    expect(formatDate(null)).toBe('—');
  });
});
