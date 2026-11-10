import { test, expect } from '@playwright/test';

const APP = 'http://localhost:8501';

test('page loads with ResearchGPT title', async ({ page }) => {
  await page.goto(APP);
  await page.waitForSelector('[data-testid="stApp"]', { timeout: 30_000 });
  await expect(page).toHaveTitle(/ResearchGPT/);
  await expect(page.getByText('ResearchGPT').first()).toBeVisible();
});

test('sidebar has New Chat button', async ({ page }) => {
  await page.goto(APP);
  await page.waitForSelector('[data-testid="stApp"]', { timeout: 30_000 });
  await expect(page.getByRole('button', { name: '+ New Chat' })).toBeVisible();
});

test('generation settings expander opens', async ({ page }) => {
  await page.goto(APP);
  await page.waitForSelector('[data-testid="stApp"]', { timeout: 30_000 });
  // Click the Generation settings expander
  const expander = page.getByText(/Generation settings/i);
  await expect(expander).toBeVisible();
  await expander.click();
  // After opening, the strategy selectbox should be visible
  await expect(page.getByText('Retrieval Strategy')).toBeVisible();
});

test('chat input shows correct placeholder on empty state', async ({ page }) => {
  await page.goto(APP);
  await page.waitForSelector('[data-testid="stApp"]', { timeout: 30_000 });
  const input = page.locator('[data-testid="stChatInput"] textarea');
  await expect(input).toHaveAttribute('placeholder', /research topic/i);
});

test('author profile expander is present in sidebar', async ({ page }) => {
  await page.goto(APP);
  await page.waitForSelector('[data-testid="stApp"]', { timeout: 30_000 });
  await expect(page.getByText(/Author Profile/i)).toBeVisible();
});
