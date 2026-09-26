/**
 * Pure helpers for the public signing page. The limits mirror openapi.yaml
 * (`SigningToken` pattern, `SubmitSignatureRequest`) and SPEC.md §7 so the
 * form can fail fast; the API remains the authority.
 */
import { ApiError } from '../api/client';

/** 32 CSPRNG bytes as unpadded base64url: exactly 43 characters. */
export const SIGNING_TOKEN_RE = /^[A-Za-z0-9_-]{43}$/;

export const TYPED_NAME_MIN_LENGTH = 2;
export const TYPED_NAME_MAX_LENGTH = 200;

/** Decoded PNG limit (MAX_SIGNATURE_PNG_BYTES, "500 KB" in SPEC.md §7). */
export const MAX_SIGNATURE_PNG_BYTES = 512_000;
export const MAX_SIGNATURE_WIDTH_PX = 2000;
export const MAX_SIGNATURE_HEIGHT_PX = 1000;

const PNG_DATA_URL_RE = /^data:image\/png;base64,[A-Za-z0-9+/=]+$/;

export function isSigningTokenShape(token: string): boolean {
  return SIGNING_TOKEN_RE.test(token);
}

export function validateTypedName(value: string): string | null {
  const name = value.trim();
  if (name.length < TYPED_NAME_MIN_LENGTH) {
    return `Enter your full name (at least ${TYPED_NAME_MIN_LENGTH} characters).`;
  }
  if (name.length > TYPED_NAME_MAX_LENGTH) {
    return `Your name must be ${TYPED_NAME_MAX_LENGTH} characters or fewer.`;
  }
  return null;
}

/** Decoded byte length of the base64 payload of a data URL. */
export function pngDataUrlBytes(dataUrl: string): number {
  const comma = dataUrl.indexOf(',');
  const b64 = comma === -1 ? '' : dataUrl.slice(comma + 1);
  const padding = b64.endsWith('==') ? 2 : b64.endsWith('=') ? 1 : 0;
  return Math.max(0, Math.floor((b64.length * 3) / 4) - padding);
}

export function validateSignatureImage(dataUrl: string | null): string | null {
  if (!dataUrl) return 'Draw your signature.';
  if (!PNG_DATA_URL_RE.test(dataUrl)) {
    return 'The signature could not be captured. Clear it and sign again.';
  }
  if (pngDataUrlBytes(dataUrl) > MAX_SIGNATURE_PNG_BYTES) {
    return 'The signature image is too large. Clear it and sign again with fewer strokes.';
  }
  return null;
}

/**
 * Copies the pad's canvas to a PNG data URL, scaled down when a high-density
 * screen would push it past the API's 2000×1000 pixel limit.
 */
export function exportSignaturePng(canvas: HTMLCanvasElement): string {
  const scale = Math.min(
    1,
    MAX_SIGNATURE_WIDTH_PX / Math.max(canvas.width, 1),
    MAX_SIGNATURE_HEIGHT_PX / Math.max(canvas.height, 1),
  );
  if (scale >= 1) return canvas.toDataURL('image/png');
  const copy = document.createElement('canvas');
  copy.width = Math.max(1, Math.floor(canvas.width * scale));
  copy.height = Math.max(1, Math.floor(canvas.height * scale));
  const ctx = copy.getContext('2d');
  if (!ctx) return canvas.toDataURL('image/png');
  ctx.drawImage(canvas, 0, 0, copy.width, copy.height);
  return copy.toDataURL('image/png');
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export type LinkProblemKind =
  | 'invalid'
  | 'expired'
  | 'used'
  | 'cancelled'
  | 'rate_limited'
  | 'unavailable';

export interface LinkProblem {
  kind: LinkProblemKind;
  /** `expired_at` or `signed_at` from the 410 body, when the API sent one. */
  at: string | null;
  /** Server message, shown only for the generic cases. */
  message: string | null;
}

function detailTimestamp(err: ApiError, key: string): string | null {
  const value = err.details?.[key];
  return typeof value === 'string' ? value : null;
}

/** Maps a failed public request to the page the signer should see. */
export function classifyLinkError(err: unknown): LinkProblem {
  if (err instanceof ApiError) {
    switch (err.code) {
      case 'not_found':
        return { kind: 'invalid', at: null, message: null };
      case 'link_expired':
        return { kind: 'expired', at: detailTimestamp(err, 'expired_at'), message: null };
      case 'link_used':
        return { kind: 'used', at: detailTimestamp(err, 'signed_at'), message: null };
      case 'contract_cancelled':
        return { kind: 'cancelled', at: null, message: null };
      case 'rate_limited':
        return { kind: 'rate_limited', at: null, message: err.message };
      default:
        return { kind: 'unavailable', at: null, message: err.message };
    }
  }
  return { kind: 'unavailable', at: null, message: err instanceof Error ? err.message : null };
}

/**
 * True when a failed submit means the link itself is dead (404 or 410), so the
 * signer should see the problem page instead of a retryable form error.
 */
export function isTerminalLinkError(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 404 || err.status === 410);
}
