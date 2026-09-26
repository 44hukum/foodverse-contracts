/** Runtime configuration. Everything comes from Vite env; nothing is secret. */

const DEFAULT_API_BASE_URL = 'http://localhost:8000/api/v1';

/** API origin + `/api/v1`, no trailing slash. */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL).replace(
  /\/+$/,
  '',
);

/** Human-facing timezone shown next to UTC (CLAUDE.md rule 14). */
export const DISPLAY_TIMEZONE = 'Asia/Kathmandu';
export const DISPLAY_TIMEZONE_LABEL = 'NPT';

/** Upload limit mirrored from SPEC.md §7 so the form can fail fast. The API enforces it too. */
export const MAX_PDF_BYTES = 20 * 1024 * 1024;

/** Link lifetime bounds from SendContractRequest.expires_in_days. */
export const SIGNING_LINK_TTL_DAYS_DEFAULT = 14;
export const SIGNING_LINK_TTL_DAYS_MIN = 1;
export const SIGNING_LINK_TTL_DAYS_MAX = 30;
