import { render } from '@testing-library/react';
import type { RenderResult } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { App } from '../App';
import { session } from '../auth/session';
import { MOCK_ACCESS_TOKEN, MOCK_ADMIN } from '../mocks/data';

/** Puts a valid mock session in memory, as if the admin had just logged in. */
export function signIn(): void {
  session.set({ token: MOCK_ACCESS_TOKEN, admin: MOCK_ADMIN });
}

/** Renders the whole app at `path` inside a memory router. */
export function renderApp(path: string, options: { authed?: boolean } = {}): RenderResult {
  if (options.authed ?? true) signIn();
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

export function pdfFile(name = 'contract.pdf', bytes = 1024): File {
  const content = new Uint8Array(bytes);
  content.set([0x25, 0x50, 0x44, 0x46, 0x2d]); // "%PDF-"
  return new File([content], name, { type: 'application/pdf' });
}
