/**
 * In-memory admin session. SPEC.md §4: the web app keeps the JWT in memory
 * and sends it as a bearer token; nothing is written to storage, so a page
 * reload means logging in again.
 */
import type { AdminUser } from '../api/types';

export interface Session {
  token: string;
  admin: AdminUser;
}

type Listener = () => void;

let current: Session | null = null;
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of listeners) listener();
}

export const session = {
  get(): Session | null {
    return current;
  },
  token(): string | null {
    return current?.token ?? null;
  },
  set(next: Session): void {
    current = next;
    emit();
  },
  clear(): void {
    if (current === null) return;
    current = null;
    emit();
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};
