import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterAll, afterEach, beforeAll } from 'vitest';
import { session } from '../auth/session';
import { resetMockDb } from '../mocks/data';
import { server } from '../mocks/server';

// jsdom's Blob/File/FormData are not the ones Node's fetch (undici) knows, so a
// multipart upload built from them is serialised as an anonymous "blob" without
// its filename or content. Tests exercise real multipart bodies through MSW, so
// swap in Node's implementations, which is what a browser would give the app.
// Node's classes are reached through fetch's own multipart parser so that this
// file stays free of Node type dependencies.
const probe = await new Response(
  '--b\r\nContent-Disposition: form-data; name="f"; filename="p.txt"\r\n' +
    'Content-Type: text/plain\r\n\r\nx\r\n--b--\r\n',
  { headers: { 'content-type': 'multipart/form-data; boundary=b' } },
).formData();
const NodeFormData = probe.constructor as typeof FormData;
const NodeFile = (probe.get('f') as File).constructor as typeof File;
const NodeBlob = Object.getPrototypeOf(NodeFile.prototype).constructor as typeof Blob;
Object.assign(globalThis, { Blob: NodeBlob, File: NodeFile, FormData: NodeFormData });

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));

afterEach(() => {
  server.resetHandlers();
  resetMockDb();
  session.clear();
  cleanup();
});

afterAll(() => server.close());
