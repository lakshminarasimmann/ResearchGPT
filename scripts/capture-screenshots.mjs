/**
 * Capture the screenshots embedded in README.md.
 *
 * Shoots the running development server, so start both processes first:
 *
 *     python -m uvicorn api.main:app --port 8001
 *     npm --prefix frontend run dev
 *
 * then:
 *
 *     node scripts/capture-screenshots.mjs            # all shots
 *     node scripts/capture-screenshots.mjs landing    # a subset, by name
 *
 * Images are written to docs/screenshots/.
 */
import { chromium } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = resolve(ROOT, 'docs/screenshots');
const APP = process.env.APP_URL ?? 'http://localhost:5173';

const VIEWPORT = { width: 1440, height: 900 };

/** Apply a theme before the app boots, so there is no flash of the other one. */
async function newPage(browser, theme) {
  const context = await browser.newContext({
    viewport: VIEWPORT,
    deviceScaleFactor: 2, // crisp on high-density displays
    colorScheme: theme,
  });
  await context.addInitScript((t) => {
    try {
      localStorage.setItem('researchgpt.theme', t);
    } catch {
      /* storage blocked - the markup default applies */
    }
  }, theme);
  const page = await context.newPage();
  return page;
}

/** Wait for the health badge to settle so no shot shows "checking…". */
async function waitForHealth(page) {
  await page
    .waitForFunction(
      () => !document.querySelector('.health-badge.health-loading'),
      { timeout: 15_000 }
    )
    .catch(() => {});
}

const shots = {
  /** Landing page, dark theme - the default view. */
  async landing(browser) {
    const page = await newPage(browser, 'dark');
    await page.goto(APP);
    await waitForHealth(page);
    await page.screenshot({ path: `${OUT}/landing-dark.png` });
    await page.context().close();
  },

  /** Landing page, light theme. */
  async landingLight(browser) {
    const page = await newPage(browser, 'light');
    await page.goto(APP);
    await waitForHealth(page);
    await page.screenshot({ path: `${OUT}/landing-light.png` });
    await page.context().close();
  },

  /** Settings drawer. */
  async settings(browser) {
    const page = await newPage(browser, 'dark');
    await page.goto(APP);
    await waitForHealth(page);
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.waitForSelector('.settings-panel');
    await page.waitForTimeout(400); // let the slide-in finish
    await page.screenshot({ path: `${OUT}/settings.png` });
    await page.context().close();
  },

  /** History dropdown in the top bar. Needs at least one saved paper. */
  async history(browser) {
    const page = await newPage(browser, 'dark');
    await page.goto(APP);
    await waitForHealth(page);
    await page.getByRole('button', { name: /^History/ }).click();
    await page.waitForSelector('.menu-panel');
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${OUT}/history.png` });
    await page.context().close();
  },

  /**
   * The literature survey table.
   *
   * Survey rows are not persisted with a saved paper, so unlike the other
   * shots this one runs a real survey and therefore costs real inference
   * time - several minutes against a local 7B model. Keep SURVEY_PAPERS low.
   */
  async survey(browser) {
    const papers = Number(process.env.SURVEY_PAPERS ?? 3);
    const page = await newPage(browser, 'dark');
    await page.goto(APP);
    await waitForHealth(page);

    // Dial the survey down before starting, so this stays affordable.
    await page.getByRole('button', { name: 'Settings' }).click();
    await page.waitForSelector('.settings-panel');
    await page.locator('.settings-panel input[type=range]').first().fill(String(papers));
    await page.locator('.settings-close').click();

    await page.getByPlaceholder('Enter a research topic…').fill(
      process.env.SURVEY_TOPIC ?? 'Hallucination mitigation in RAG'
    );
    await page.getByRole('button', { name: 'Generate', exact: true }).click();

    // The survey finishes well before the paper does; shoot as soon as the
    // table appears rather than waiting for the whole pipeline.
    await page.waitForSelector('.survey-panel tbody tr', { timeout: 30 * 60_000 });
    await page.waitForTimeout(500);
    await page.locator('.survey-panel').scrollIntoViewIfNeeded();
    await page.screenshot({ path: `${OUT}/survey.png` });
    await page.context().close();
  },

  /**
   * A finished paper, opened from history: metrics, exports, the draft and
   * the expandable evaluation / plagiarism / sources sections.
   */
  async result(browser) {
    const page = await newPage(browser, 'dark');
    await page.goto(APP);
    await waitForHealth(page);
    await page.getByRole('button', { name: /^History/ }).click();
    await page.waitForSelector('.menu-panel .history-item');
    await page.locator('.history-item').first().click();
    await page.waitForSelector('.result-meta', { timeout: 30_000 });

    // Scroll the draft past its title block. A generated title page can carry
    // author names and e-mail addresses lifted from a source paper, and these
    // images are published - so frame on the body text, not the front matter.
    await page.evaluate(() => {
      const paper = document.querySelector('.paper-text');
      if (paper) paper.scrollTop = 520;
    });
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${OUT}/result.png` });

    // Second shot: where the text came from.
    const chunks = page.getByRole('button', { name: /retrieved chunks/ });
    if (await chunks.count()) {
      await chunks.click();
      await page.waitForSelector('.chunk-item');
      await chunks.scrollIntoViewIfNeeded();
      await page.waitForTimeout(600);
      await page.screenshot({ path: `${OUT}/sources.png` });
    }
    await page.context().close();
  },
};

const requested = process.argv.slice(2);
const names = requested.length
  ? Object.keys(shots).filter((n) => requested.some((r) => n.toLowerCase().includes(r.toLowerCase())))
  : Object.keys(shots);

await mkdir(OUT, { recursive: true });
const browser = await chromium.launch();

let failed = 0;
for (const name of names) {
  try {
    await shots[name](browser);
    console.log(`  ok    ${name}`);
  } catch (e) {
    failed++;
    console.error(`  FAIL  ${name}: ${e.message.split('\n')[0]}`);
  }
}

await browser.close();
console.log(failed ? `${failed} shot(s) failed` : `${names.length} shot(s) written to docs/screenshots/`);
process.exit(failed ? 1 : 0);
