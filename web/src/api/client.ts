/**
 * Thin fetch client implemented against openapi.yaml (CLAUDE.md rule 5).
 * Request and response shapes come from the generated types; nothing here is
 * hand-modelled. Bodies on the send and public endpoints are never logged
 * (rule 6).
 */
import { API_BASE_URL } from '../config';
import { session } from '../auth/session';
import type {
  AdminUser,
  ApiErrorBody,
  ContractDetail,
  ContractList,
  ErrorCode,
  ListContractsQuery,
  LoginRequest,
  LoginResponse,
  PublicContract,
  SendContractRequest,
  SendContractResponse,
  SignatureResult,
  SubmitSignatureRequest,
} from './types';

export class ApiError extends Error {
  readonly status: number;
  readonly code: ErrorCode | 'network_error';
  readonly details: Record<string, unknown> | undefined;

  constructor(
    status: number,
    code: ErrorCode | 'network_error',
    message: string,
    details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.details = details;
  }

  /** Field-level messages from a `validation_error` response, keyed by field name. */
  fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    const fields = this.details?.['fields'];
    if (!Array.isArray(fields)) return out;
    for (const entry of fields) {
      if (
        typeof entry === 'object' &&
        entry !== null &&
        typeof (entry as { field?: unknown }).field === 'string' &&
        typeof (entry as { message?: unknown }).message === 'string'
      ) {
        out[(entry as { field: string }).field] = (entry as { message: string }).message;
      }
    }
    return out;
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== 'object' || value === null) return false;
  const err = (value as { error?: unknown }).error;
  return (
    typeof err === 'object' &&
    err !== null &&
    typeof (err as { code?: unknown }).code === 'string' &&
    typeof (err as { message?: unknown }).message === 'string'
  );
}

interface RequestOptions {
  method?: 'GET' | 'POST';
  body?: BodyInit | null;
  json?: unknown;
  query?: URLSearchParams;
  auth?: boolean;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', auth = true } = options;
  const headers = new Headers({ Accept: 'application/json' });
  let body: BodyInit | null | undefined = options.body;
  if (options.json !== undefined) {
    headers.set('Content-Type', 'application/json');
    body = JSON.stringify(options.json);
  }
  if (auth) {
    const token = session.token();
    if (token) headers.set('Authorization', `Bearer ${token}`);
  }
  const qs = options.query?.toString();
  const url = `${API_BASE_URL}${path}${qs ? `?${qs}` : ''}`;

  let response: Response;
  try {
    response = await fetch(url, { method, headers, body: body ?? null });
  } catch {
    throw new ApiError(0, 'network_error', 'Could not reach the server. Check your connection.');
  }

  if (response.status === 204) return undefined as T;

  let payload: unknown = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = null;
    }
  }

  if (!response.ok) {
    if (response.status === 401 && auth) session.clear();
    if (isErrorBody(payload)) {
      const { code, message, details } = payload.error;
      throw new ApiError(response.status, code, message, details);
    }
    throw new ApiError(response.status, 'internal_error', `Request failed (${response.status}).`);
  }
  return payload as T;
}

// ------------------------------------------------------------------ admin auth

export function login(body: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>('/admin/auth/login', { method: 'POST', json: body, auth: false });
}

export function getCurrentAdmin(): Promise<AdminUser> {
  return request<AdminUser>('/admin/auth/me');
}

// -------------------------------------------------------------- admin contracts

export function listContracts(query: ListContractsQuery = {}): Promise<ContractList> {
  const params = new URLSearchParams();
  for (const status of query.status ?? []) params.append('status', status);
  if (query.q) params.set('q', query.q);
  if (query.limit !== undefined) params.set('limit', String(query.limit));
  if (query.cursor) params.set('cursor', query.cursor);
  return request<ContractList>('/admin/contracts', { query: params });
}

export function getContract(contractId: string): Promise<ContractDetail> {
  return request<ContractDetail>(`/admin/contracts/${encodeURIComponent(contractId)}`);
}

export interface CreateContractInput {
  file: File;
  title: string;
  signer_name: string;
  signer_email: string;
  term_end_date?: string;
}

/** `multipart/form-data` per CreateContractRequest. The browser sets the boundary. */
export function createContract(input: CreateContractInput): Promise<ContractDetail> {
  const form = new FormData();
  form.append('file', input.file, input.file.name);
  form.append('title', input.title);
  form.append('signer_name', input.signer_name);
  form.append('signer_email', input.signer_email);
  if (input.term_end_date) form.append('term_end_date', input.term_end_date);
  return request<ContractDetail>('/admin/contracts', { method: 'POST', body: form });
}

/**
 * Issues (or rotates) the signing link. The returned `signing_link.url` is shown
 * once in a copy box and never logged, stored, or sent anywhere else (rule 6).
 */
export function sendContractLink(
  contractId: string,
  body: SendContractRequest,
): Promise<SendContractResponse> {
  return request<SendContractResponse>(`/admin/contracts/${encodeURIComponent(contractId)}/send`, {
    method: 'POST',
    json: body,
  });
}

// ------------------------------------------------------------- public signing

/**
 * Loads the contract for the signer. The token travels only in the request
 * path and is never logged or stored (rule 6). Side effect on the server:
 * `sent` becomes `viewed` and a `link.viewed` event is written.
 */
export function getContractByToken(token: string): Promise<PublicContract> {
  return request<PublicContract>(`/public/sign/${encodeURIComponent(token)}`, { auth: false });
}

/** Submits typed name, drawn signature (PNG data URL), and consent. Single use. */
export function submitSignature(
  token: string,
  body: SubmitSignatureRequest,
): Promise<SignatureResult> {
  return request<SignatureResult>(`/public/sign/${encodeURIComponent(token)}/signature`, {
    method: 'POST',
    json: body,
    auth: false,
  });
}
