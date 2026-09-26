/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the API including the `/api/v1` prefix. Set by scripts/worktree-init.sh. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

/** True only under `npm run dev:mock` (Vite mode "mock"); see vite.config.ts. */
declare const __API_MOCK__: boolean;
