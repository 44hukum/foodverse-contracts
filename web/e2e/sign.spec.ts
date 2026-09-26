import { expect, test } from '@playwright/test';
import { MOCK_SIGNING_TOKENS } from '../src/sign/mocks/data';

/**
 * Happy path for the public signing page at 375px, against the MSW browser
 * mocks (see playwright.config.ts). Exercises the real react-signature-canvas
 * pad, which the Vitest suite replaces because jsdom has no canvas.
 */
test('signer opens the link, reviews, signs, and sees the confirmation', async ({ page }) => {
  await page.goto(`/sign/${MOCK_SIGNING_TOKENS.viewed}`);

  await expect(
    page.getByRole('heading', { name: 'Lakeside Resort — Onboarding Agreement' }),
  ).toBeVisible();
  await expect(page.locator('iframe.pdf-frame')).toBeVisible();

  const submit = page.getByRole('button', { name: 'Sign document' });
  await expect(submit).toBeDisabled();

  // Fits the phone viewport: no horizontal scrolling.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);

  // The token never appears in a navigable link.
  for (const href of await page.locator('a[href]').evaluateAll((as) => as.map((a) => a.getAttribute('href') ?? ''))) {
    expect(href).not.toContain(MOCK_SIGNING_TOKENS.viewed);
  }

  const name = page.getByLabel('Full name');
  await expect(name).toHaveValue('Anita Gurung');
  await name.fill('Anita Gurung');

  const canvas = page.locator('canvas.signature-canvas');
  await canvas.scrollIntoViewIfNeeded();
  const box = await canvas.boundingBox();
  if (!box) throw new Error('signature canvas has no bounding box');
  await page.mouse.move(box.x + 30, box.y + 90);
  await page.mouse.down();
  await page.mouse.move(box.x + 120, box.y + 40, { steps: 12 });
  await page.mouse.move(box.x + 220, box.y + 130, { steps: 12 });
  await page.mouse.move(box.x + 320, box.y + 70, { steps: 12 });
  await page.mouse.up();

  await expect(submit).toBeDisabled();
  await page.getByRole('checkbox', { name: /I confirm that I am Anita Gurung/ }).check();
  await expect(submit).toBeEnabled();

  await submit.click();

  await expect(page.getByRole('heading', { name: 'Document signed' })).toBeVisible();
  await expect(page.getByText(/emailed to anita@lakesideresort\.example/)).toBeVisible();
  await expect(page.locator('code.hash')).toHaveText(/^[a-f0-9]{64}$/);
  await expect(page.getByRole('link', { name: 'Download signed PDF' })).toHaveAttribute(
    'href',
    /\/signed\.pdf/,
  );
  await expect(page.getByText(/UTC$/).first()).toBeVisible();
  await expect(submit).toHaveCount(0);
});
