import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';

/** Browser service worker for `npm run dev:mock`. Never bundled in normal builds. */
export const worker = setupWorker(...handlers);
