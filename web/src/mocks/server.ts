import { setupServer } from 'msw/node';
import { handlers } from './handlers';

/** Node interceptor for the Vitest suite; shares the browser handlers. */
export const server = setupServer(...handlers);
