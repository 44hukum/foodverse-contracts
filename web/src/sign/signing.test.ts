import { describe, expect, it } from 'vitest';
import { ApiError } from '../api/client';
import {
  MAX_SIGNATURE_PNG_BYTES,
  classifyLinkError,
  formatBytes,
  isSigningTokenShape,
  isTerminalLinkError,
  pngDataUrlBytes,
  validateSignatureImage,
  validateTypedName,
} from './signing';

const TINY_PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';

describe('isSigningTokenShape', () => {
  it('accepts exactly 43 base64url characters', () => {
    expect(isSigningTokenShape('a'.repeat(43))).toBe(true);
    expect(isSigningTokenShape('9Xk2m_VbT4qLw8ZpR1nYc3sDf6hJg0aEu5iOo7tQyWv')).toBe(true);
  });

  it('rejects other lengths and characters', () => {
    expect(isSigningTokenShape('')).toBe(false);
    expect(isSigningTokenShape('a'.repeat(42))).toBe(false);
    expect(isSigningTokenShape('a'.repeat(44))).toBe(false);
    expect(isSigningTokenShape(`${'a'.repeat(42)}=`)).toBe(false);
    expect(isSigningTokenShape(`${'a'.repeat(42)}/`)).toBe(false);
  });
});

describe('validateTypedName', () => {
  it('requires 2 to 200 characters after trimming', () => {
    expect(validateTypedName('')).toMatch(/full name/);
    expect(validateTypedName(' A ')).toMatch(/full name/);
    expect(validateTypedName('Al')).toBeNull();
    expect(validateTypedName('x'.repeat(200))).toBeNull();
    expect(validateTypedName('x'.repeat(201))).toMatch(/200 characters/);
  });
});

describe('signature image validation', () => {
  it('computes the decoded byte length of a data URL', () => {
    expect(pngDataUrlBytes('data:image/png;base64,')).toBe(0);
    expect(pngDataUrlBytes('data:image/png;base64,QUJD')).toBe(3);
    expect(pngDataUrlBytes('data:image/png;base64,QUI=')).toBe(2);
    expect(pngDataUrlBytes('data:image/png;base64,QQ==')).toBe(1);
  });

  it('accepts a small PNG data URL', () => {
    expect(validateSignatureImage(TINY_PNG)).toBeNull();
  });

  it('rejects empty, non-PNG, and oversized images', () => {
    expect(validateSignatureImage(null)).toMatch(/Draw your signature/);
    expect(validateSignatureImage('data:image/jpeg;base64,QUJD')).toMatch(/could not be captured/);
    const oversized = `data:image/png;base64,${'A'.repeat(Math.ceil((MAX_SIGNATURE_PNG_BYTES + 3) / 3) * 4)}`;
    expect(validateSignatureImage(oversized)).toMatch(/too large/);
  });
});

describe('classifyLinkError', () => {
  it('maps each public error code to a page', () => {
    expect(classifyLinkError(new ApiError(404, 'not_found', 'Not found.'))).toEqual({
      kind: 'invalid',
      at: null,
      message: null,
    });
    expect(
      classifyLinkError(
        new ApiError(410, 'link_expired', 'Expired.', { expired_at: '2026-10-10T09:00:00Z' }),
      ),
    ).toEqual({ kind: 'expired', at: '2026-10-10T09:00:00Z', message: null });
    expect(
      classifyLinkError(new ApiError(410, 'link_used', 'Used.', { signed_at: '2026-09-28T14:22:10Z' })),
    ).toEqual({ kind: 'used', at: '2026-09-28T14:22:10Z', message: null });
    expect(classifyLinkError(new ApiError(410, 'contract_cancelled', 'Cancelled.')).kind).toBe(
      'cancelled',
    );
    expect(classifyLinkError(new ApiError(429, 'rate_limited', 'Slow down.')).kind).toBe(
      'rate_limited',
    );
  });

  it('treats server and network failures as retryable', () => {
    expect(classifyLinkError(new ApiError(500, 'internal_error', 'Boom.'))).toEqual({
      kind: 'unavailable',
      at: null,
      message: 'Boom.',
    });
    expect(classifyLinkError(new ApiError(0, 'network_error', 'Offline.')).kind).toBe('unavailable');
    expect(classifyLinkError('weird').kind).toBe('unavailable');
  });

  it('ignores non-string timestamps in details', () => {
    expect(classifyLinkError(new ApiError(410, 'link_used', 'Used.', { signed_at: 42 })).at).toBeNull();
  });
});

describe('isTerminalLinkError', () => {
  it('is true only for 404 and 410 API errors', () => {
    expect(isTerminalLinkError(new ApiError(404, 'not_found', 'x'))).toBe(true);
    expect(isTerminalLinkError(new ApiError(410, 'link_used', 'x'))).toBe(true);
    expect(isTerminalLinkError(new ApiError(422, 'validation_error', 'x'))).toBe(false);
    expect(isTerminalLinkError(new ApiError(500, 'internal_error', 'x'))).toBe(false);
    expect(isTerminalLinkError(new Error('x'))).toBe(false);
  });
});

describe('formatBytes', () => {
  it('picks a readable unit', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(184_320)).toBe('180 KB');
    expect(formatBytes(2.5 * 1024 * 1024)).toBe('2.5 MB');
  });
});
