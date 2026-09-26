/**
 * Named aliases over the generated OpenAPI types. Never hand-write shapes here;
 * regenerate `schema.d.ts` with `npm run generate:api` when openapi.yaml changes.
 */
import type { components, paths } from './schema';

export type Schemas = components['schemas'];

export type ContractStatus = Schemas['ContractStatus'];
export type ContractSummary = Schemas['ContractSummary'];
export type ContractDetail = Schemas['ContractDetail'];
export type ContractList = Schemas['ContractList'];
export type ContractEvent = Schemas['ContractEvent'];
export type Signer = Schemas['Signer'];
export type AdminUser = Schemas['AdminUser'];
export type LoginRequest = Schemas['LoginRequest'];
export type LoginResponse = Schemas['LoginResponse'];
export type CreateContractRequest = Schemas['CreateContractRequest'];
export type SendContractRequest = Schemas['SendContractRequest'];
export type SendContractResponse = Schemas['SendContractResponse'];
export type SigningLink = Schemas['SigningLink'];
export type ApiErrorBody = Schemas['Error'];
export type ErrorCode = Schemas['ErrorCode'];

export type ListContractsQuery = NonNullable<paths['/admin/contracts']['get']['parameters']['query']>;

export const CONTRACT_STATUSES: readonly ContractStatus[] = [
  'draft',
  'sent',
  'viewed',
  'signed',
  'expired',
  'cancelled',
] as const;

/** Statuses from which `POST /send` is allowed (SPEC.md §5). */
export const SENDABLE_STATUSES: readonly ContractStatus[] = ['draft', 'sent', 'viewed', 'expired'];
