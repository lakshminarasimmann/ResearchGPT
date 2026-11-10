import { readFile } from 'node:fs/promises';
import { test, expect, type Page } from '@playwright/test';
import { mockBackend, makeResult, makeSurveyResult } from './mockApi';

const topicInput = (page: Page) => page.getByPlaceholder('Enter a research topic…');
const generateBtn = (page: Page) => page.getByRole('button', { name: 'Generate', exact: true });

// History moved from the old sidebar into a dropdown in the top bar, so it has
// to be opened before its rows can be read or clicked.
async function openHistoryMenu(page: Page) {
  await page.getByRole('button', { name: /^History/ }).click();
  await expect(page.locator('.menu-panel')).toBeVisible();
}

async function generate(page: Page, topic: string) {
  await topicInput(page).fill(topic);
  await generateBtn(page).click();
}

test.describe('empty state', () => {
  test('renders header, input and disabled Generate button', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/');
    await expect(page.getByRole('heading', { name: 'ResearchGPT' })).toBeVisible();
    await expect(topicInput(page)).toBeVisible();
    await expect(generateBtn(page)).toBeDisabled();
    await topicInput(page).fill('   ');
    await expect(generateBtn(page)).toBeDisabled();
    await topicInput(page).fill('transformers');
    await expect(generateBtn(page)).toBeEnabled();
  });

  test('history list loads from the API', async ({ page }) => {
    await mockBackend(page, {
      history: [{ topic: 'Graph neural networks', saved_at: 1, fname: 'gnn.json', page_estimate: 4, strategy: 'auto' }],
    });
    await page.goto('/');
    await openHistoryMenu(page);
    await expect(page.locator('.history-item')).toHaveText(/Graph neural networks/);
  });
});

test.describe('settings', () => {
  test('changes persist and are sent with the requests', async ({ page }) => {
    const api = await mockBackend(page);
    await page.goto('/');

    await page.getByTitle('Settings').click();
    const panel = page.locator('.settings-panel');
    await expect(panel.getByRole('heading', { name: 'Settings' })).toBeVisible();

    await panel.getByPlaceholder('e.g. Jane Smith').fill('Ada Lovelace');
    await panel.getByPlaceholder('e.g. MIT').fill('Analytical Engines Ltd');
    await panel.getByPlaceholder('e.g. jsmith@mit.edu').fill('ada@example.com');
    await panel.locator('select').selectOption('complex');
    await expect(panel.getByText('Breaks your query into sub-questions')).toBeVisible();
    await panel.getByLabel('Refresh papers from arXiv').uncheck();
    await panel.getByLabel('Run quality evaluation').uncheck();
    await panel.locator('input[type=range]').nth(0).fill('5'); // survey papers
    await panel.locator('input[type=range]').nth(1).fill('9'); // top-k
    await expect(panel.getByText('Survey papers: 5')).toBeVisible();
    await expect(panel.getByText('Retrieval chunks (top-k): 9')).toBeVisible();

    await panel.getByRole('button', { name: /Save & return/ }).click();
    await expect(panel).toBeHidden();

    // Reopen: values kept
    await page.getByTitle('Settings').click();
    await expect(page.getByPlaceholder('e.g. Jane Smith')).toHaveValue('Ada Lovelace');
    await expect(page.locator('.settings-panel select')).toHaveValue('complex');
    // Clicking the overlay backdrop closes it
    await page.locator('.settings-overlay').click({ position: { x: 5, y: 5 } });
    await expect(page.locator('.settings-panel')).toBeHidden();

    await generate(page, 'quantum error correction');
    await expect(page.locator('.result-meta')).toBeVisible({ timeout: 15_000 });

    expect(api.bodiesFor('POST', '/api/survey')[0]).toEqual({ topic: 'quantum error correction', max_papers: 5 });
    expect(api.bodiesFor('POST', '/api/generate')[0]).toMatchObject({
      topic: 'quantum error correction',
      strategy: 'complex',
      retrieval_top_k: 9,
      force_refresh_sources: false,
      include_evaluation: false,
      author_name: 'Ada Lovelace',
      author_affiliation: 'Analytical Engines Ltd',
      author_email: 'ada@example.com',
    });
  });

  test('close button closes the panel', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/');
    await page.getByTitle('Settings').click();
    await page.locator('.settings-close').click();
    await expect(page.locator('.settings-panel')).toBeHidden();
  });
});

test.describe('generation flow', () => {
  test('survey then paper generation, then saved to history', async ({ page }) => {
    const api = await mockBackend(page);
    await page.goto('/');
    await generate(page, 'vision transformers');

    // Survey progress, input hidden while running
    await expect(page.getByText('Running literature survey…')).toBeVisible();
    await expect(topicInput(page)).toBeHidden();
    await expect(page.locator('.chat-tab.active .chat-tab-topic')).toHaveText('vision transformers');
    await expect(page.locator('.chat-tab-spinner')).toBeVisible();

    // Survey table
    const survey = page.locator('.survey-panel');
    await expect(survey).toContainText('analysed 2 papers on: vision transformers');
    await expect(survey.getByRole('link', { name: /arXiv/ })).toHaveAttribute('href', 'https://arxiv.org/abs/1706.03762');
    await expect(survey.getByRole('button', { name: /PDF \(IEEE\)/ })).toBeVisible();

    // Research gaps excludes "Not mentioned"
    await survey.getByRole('button', { name: /Research Gap Summary \(1 papers\)/ }).click();
    await expect(survey.locator('.gap-item')).toHaveCount(1);
    await expect(survey.locator('.gap-text')).toHaveText('Quadratic cost on long sequences');

    await survey.getByRole('button', { name: /Sample survey paper/ }).click();
    await expect(survey.getByText('SURVEY DRAFT TEXT')).toBeVisible();

    // Paper result
    const meta = page.locator('.result-meta');
    await expect(meta).toBeVisible({ timeout: 15_000 });
    await expect(meta).toContainText('4.5/5');
    await expect(meta).toContainText('3.2/5');
    await expect(meta).toContainText('7 papers');
    await expect(meta).toContainText('~5 pages');
    await expect(meta).toContainText('2 rewrite pass(es)');
    await expect(meta).toContainText('humanized');
    await expect(page.locator('.score-pill').nth(0)).toHaveClass(/score-good/);
    await expect(page.locator('.score-pill').nth(1)).toHaveClass(/score-fair/);
    await expect(page.locator('.result-panel .paper-text')).toContainText('Transformers changed NLP.');
    await expect(page.locator('.chat-tab-spinner')).toBeHidden();
    await expect(page.locator('.warning-banner')).toBeHidden();

    // Saved + history refreshed
    await expect.poll(() => api.bodiesFor('POST', '/api/history/save').length).toBe(1);
    expect(api.bodiesFor('POST', '/api/history/save')[0].topic).toBe('vision transformers');
    await openHistoryMenu(page);
    await expect(page.locator('.history-item')).toHaveText(/vision transformers/);
  });

  test('Enter key starts generation', async ({ page }) => {
    const api = await mockBackend(page);
    await page.goto('/');
    await topicInput(page).fill('diffusion models');
    await topicInput(page).press('Enter');
    await expect(page.getByText('Running literature survey…')).toBeVisible();
    expect(api.bodiesFor('POST', '/api/survey')[0].topic).toBe('diffusion models');
  });

  test('survey failure is shown but paper generation still runs', async ({ page }) => {
    await mockBackend(page, {
      surveyJob: [{ status: 'error', progress: [], result: null, error: 'arXiv timeout' }],
    });
    await page.goto('/');
    await generate(page, 'topic');
    await expect(page.getByText('Survey error: arXiv timeout')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('.result-meta')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('.survey-panel')).toBeHidden();
  });

  test('generation job error shows error and returns to input', async ({ page }) => {
    const api = await mockBackend(page, {
      generateJob: [{ status: 'error', progress: [], result: null, error: 'LLM quota exceeded' }],
    });
    await page.goto('/');
    await generate(page, 'topic');
    await expect(page.getByText('Error: LLM quota exceeded')).toBeVisible({ timeout: 15_000 });
    await expect(topicInput(page)).toBeVisible();
    expect(api.bodiesFor('POST', '/api/history/save')).toHaveLength(0);
  });

  test('result with non-ok status shows its error and is not saved', async ({ page }) => {
    const api = await mockBackend(page, {
      generateJob: [{ status: 'done', progress: [], result: makeResult({ status: 'error', error: 'No papers found' }), error: null }],
    });
    await page.goto('/');
    await generate(page, 'topic');
    await expect(page.locator('.result-panel .error-panel')).toHaveText('No papers found', { timeout: 15_000 });
    await expect(page.locator('.result-meta')).toBeHidden();
    expect(api.bodiesFor('POST', '/api/history/save')).toHaveLength(0);
  });

  test('empty survey rows hides the survey panel', async ({ page }) => {
    await mockBackend(page, {
      surveyJob: [{ status: 'done', progress: [], result: makeSurveyResult({ rows: [] }), error: null }],
    });
    await page.goto('/');
    await generate(page, 'topic');
    await expect(page.locator('.result-meta')).toBeVisible({ timeout: 15_000 });
    await expect(page.locator('.survey-panel')).toBeHidden();
  });

});

test.describe('backend failures', () => {
  const noSurvey = [{ status: 'done', progress: [], result: makeSurveyResult({ rows: [] }), error: null }];

  test('rejected /api/generate surfaces an error instead of hanging', async ({ page }) => {
    await mockBackend(page, { generateStartStatus: 500 });
    await page.goto('/');
    await generate(page, 'topic');
    // The user should get feedback and be able to try again.
    await expect(page.getByText('Error: Could not start paper generation: 500: boom')).toBeVisible({ timeout: 15_000 });
    await expect(topicInput(page)).toBeVisible();
    await expect(page.locator('.chat-tab-spinner')).toBeHidden();
  });

  test('rejected /api/survey is reported and paper generation still runs', async ({ page }) => {
    await mockBackend(page, { surveyStartStatus: 503 });
    await page.goto('/');
    await generate(page, 'topic');
    await expect(page.getByText('Survey error: Could not start survey: 503: boom')).toBeVisible();
    await expect(page.locator('.result-meta')).toBeVisible({ timeout: 15_000 });
  });

  test('a single failed status check is tolerated', async ({ page }) => {
    await mockBackend(page, {
      surveyJob: noSurvey,
      generateJob: [
        { httpStatus: 502 },
        { status: 'done', progress: [], result: makeResult(), error: null },
      ],
    });
    await page.goto('/');
    await generate(page, 'topic');
    await expect(page.locator('.result-meta')).toBeVisible({ timeout: 15_000 });
  });

  test('repeated failed status checks stop polling with an error', async ({ page }) => {
    const api = await mockBackend(page, { surveyJob: noSurvey, generateJob: [{ httpStatus: 502 }] });
    await page.goto('/');
    await generate(page, 'topic');
    await expect(page.getByText('Error: Lost contact with the server: 502: unavailable')).toBeVisible({ timeout: 15_000 });
    await expect(topicInput(page)).toBeVisible();
    const polls = api.requests.filter((r) => r.path === '/api/jobs/gen-1').length;
    await page.waitForTimeout(3_500);
    expect(api.requests.filter((r) => r.path === '/api/jobs/gen-1').length).toBe(polls);
  });

  test('failed history save still shows the paper', async ({ page }) => {
    const api = await mockBackend(page, { surveyJob: noSurvey, historySaveStatus: 500 });
    await page.goto('/');
    await generate(page, 'topic');
    await expect(page.locator('.result-meta')).toBeVisible({ timeout: 15_000 });
    await expect.poll(() => api.bodiesFor('POST', '/api/history/save').length).toBe(1);
    await expect(page.locator('.error-panel')).toHaveCount(0);
  });

  async function openResult(page: Page, opts = {}) {
    await mockBackend(page, { surveyJob: noSurvey, ...opts });
    await page.goto('/');
    await generate(page, 'topic');
    await expect(page.locator('.result-meta')).toBeVisible({ timeout: 15_000 });
    await page.getByPlaceholder(/Refine the paper/).fill('shorter please');
    await page.getByRole('button', { name: 'Apply' }).click();
  }

  test('rejected /api/refine re-enables the refine input with an error', async ({ page }) => {
    await openResult(page, { refineStartStatus: 500 });
    await expect(page.getByText('Refine error: Could not start refinement: 500: boom')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Apply' })).toBeEnabled();
    await expect(page.getByPlaceholder(/Refine the paper/)).toHaveValue('shorter please');
  });

  test('refine job error is shown and the paper is unchanged', async ({ page }) => {
    await openResult(page, {
      refineJob: [{ status: 'done', progress: [], result: { paper_text: '', status: 'error', error: 'LLM refused' }, error: null }],
    });
    await expect(page.getByText('Refine error: LLM refused')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('.result-panel .paper-text')).toContainText('Transformers changed NLP.');
    await expect(page.getByRole('button', { name: 'Apply' })).toBeEnabled();
  });
});

test.describe('result panel', () => {
  async function openResult(page: Page, resultOverrides = {}) {
    const api = await mockBackend(page, {
      surveyJob: [{ status: 'done', progress: [], result: makeSurveyResult({ rows: [] }), error: null }],
      generateJob: [{ status: 'done', progress: [], result: makeResult(resultOverrides), error: null }],
    });
    await page.goto('/');
    await generate(page, 'Large Language Models for Code');
    await expect(page.locator('.result-meta')).toBeVisible({ timeout: 15_000 });
    return api;
  }

  test('expanders show plagiarism, analysis table and chunks', async ({ page }) => {
    await openResult(page);

    await page.getByRole('button', { name: /Plagiarism report/ }).click();
    const grid = page.locator('.plagiarism-grid');
    await expect(grid).toContainText('4.2%');
    await expect(grid).toContainText('12.5%');
    await expect(grid).toContainText('1.1%');
    await expect(grid).toContainText('0.123');

    await page.getByRole('button', { name: /Comparative analysis table/ }).click();
    await expect(page.locator('.result-panel .analysis-table th')).toHaveText(['Method', 'Metric']);
    await expect(page.locator('.result-panel .analysis-table td').first()).toHaveText('Transformer');

    await page.getByRole('button', { name: /View 2 retrieved chunks/ }).click();
    await expect(page.locator('.chunk-item')).toHaveCount(2);
    await expect(page.locator('.chunk-title').first()).toHaveText('[1] Attention Is All You Need');
    await expect(page.locator('.chunk-score').first()).toHaveText('score: 0.87'); // rerank preferred
    await expect(page.locator('.chunk-score').nth(1)).toHaveText('score: 0.5'); // falls back to score
    await expect(page.locator('.contribution-row')).toHaveCount(2);
  });

  test('optional sections are hidden when data is absent', async ({ page }) => {
    await openResult(page, {
      plagiarism_report: null,
      analysis_table: [],
      retrieved_context: [],
      ai_rewrite_passes: 0,
      humanize_applied: false,
      faithfulness: null,
    });
    await expect(page.getByRole('button', { name: /Plagiarism report/ })).toBeHidden();
    await expect(page.getByRole('button', { name: /Comparative analysis/ })).toBeHidden();
    await expect(page.getByRole('button', { name: /retrieved chunks/ })).toBeHidden();
    await expect(page.locator('.result-meta')).not.toContainText('rewrite pass');
    await expect(page.locator('.result-meta')).not.toContainText('humanized');
    await expect(page.locator('.score-pill').first()).toHaveText('—');
  });

  test('low faithfulness banner, fix citations and dismiss', async ({ page }) => {
    const api = await openResult(page, { faithfulness: 2.1 });
    const banner = page.locator('.warning-banner');
    await expect(banner).toContainText('Low faithfulness score');
    await expect(page.locator('.score-pill').first()).toHaveClass(/score-poor/);

    await banner.getByRole('button', { name: /Fix Citations/ }).click();
    await expect(page.locator('.result-panel .paper-text')).toHaveText('CITATIONS FIXED TEXT');
    expect(api.bodiesFor('POST', '/api/fix-citations')[0].context).toHaveLength(2);

    await banner.locator('.banner-dismiss').click();
    await expect(banner).toBeHidden();
  });

  test('export buttons download files with topic-based names', async ({ page }) => {
    const api = await openResult(page);
    const cases: Array<[RegExp, string]> = [
      [/Word \(\.docx\)/, 'Large_Language_Models_for_Code.docx'],
      [/^↓ PDF$/, 'Large_Language_Models_for_Code.pdf'],
      [/LaTeX PDF/, 'Large_Language_Models_for_Code_latex.pdf'],
    ];
    for (const [name, file] of cases) {
      const download = page.waitForEvent('download');
      await page.locator('.result-meta').getByRole('button', { name }).click();
      expect((await download).suggestedFilename()).toBe(file);
    }
    const pdfBodies = api.bodiesFor('POST', '/api/export/pdf');
    expect(pdfBodies.map((b) => b.use_latex)).toEqual([false, true]);

    await page.getByRole('button', { name: /Comparative analysis table/ }).click();
    const xlsx = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download Excel' }).click();
    expect((await xlsx).suggestedFilename()).toBe('analysis_Large_Language_Models_for_Code.xlsx');
  });

  test('refine replaces paper text and re-saves', async ({ page }) => {
    const api = await openResult(page);
    const refineInput = page.getByPlaceholder(/Refine the paper/);
    const apply = page.getByRole('button', { name: 'Apply' });
    await expect(apply).toBeDisabled();
    await refineInput.fill('add more on limitations');
    await apply.click();
    await expect(page.locator('.result-panel .paper-text')).toHaveText('REFINED PAPER TEXT', { timeout: 10_000 });
    await expect(refineInput).toHaveValue('');
    expect(api.bodiesFor('POST', '/api/refine')[0]).toMatchObject({
      topic: 'Large Language Models for Code',
      instruction: 'add more on limitations',
    });
    await expect.poll(() => api.bodiesFor('POST', '/api/history/save').length).toBe(2);
  });
});

test.describe('survey exports', () => {
  test('CSV, Excel, Word and PDF downloads', async ({ page }) => {
    const api = await mockBackend(page);
    await page.goto('/');
    await generate(page, 'speech recognition');
    const survey = page.locator('.survey-panel');
    await expect(survey).toBeVisible({ timeout: 10_000 });

    const csvDl = page.waitForEvent('download');
    await survey.getByRole('button', { name: '↓ CSV' }).click();
    const csv = await csvDl;
    expect(csv.suggestedFilename()).toBe('survey_speech_recognition.csv');
    const csvText = await readFile(await csv.path(), 'utf8');
    expect(csvText.split('\n')[0]).toContain('"Title"');
    expect(csvText).toContain('"Attention Is All You Need"');

    const exports: Array<[string, string]> = [
      ['↓ Excel', 'survey_speech_recognition.xlsx'],
      ['↓ Word (.docx)', 'survey_speech_recognition.docx'],
      ['↓ PDF (IEEE)', 'survey_speech_recognition_ieee.pdf'],
    ];
    for (const [name, file] of exports) {
      const dl = page.waitForEvent('download');
      await survey.getByRole('button', { name, exact: true }).click();
      expect((await dl).suggestedFilename()).toBe(file);
    }
    expect(api.requests.some((r) => r.path === '/api/download')).toBe(true);
  });
});

test.describe('archived runs', () => {
  test('Runs menu opens an archived record with its metrics', async ({ page }) => {
    await mockBackend(page);
    await page.goto('/');

    const runs = page.getByRole('button', { name: /^Runs/ });
    await expect(runs).toContainText('1');
    await runs.click();
    await expect(page.locator('.menu-panel')).toBeVisible();

    await page.locator('.menu-panel .history-item', { hasText: 'Vision transformers' }).click();
    await expect(page.locator('.menu-panel')).toBeHidden();

    // The record shows its headline scores and the committed file it came from.
    const panel = page.locator('.archive-panel');
    await expect(panel).toBeVisible();
    await expect(panel.locator('.score-pill').first()).toHaveText('4.5 / 5');
    await expect(panel.locator('.archive-note')).toContainText('2026-01-02-vision-transformers.md');
    await expect(panel.locator('.paper-text')).toContainText('ARCHIVED PAPER BODY');

    // An archived record replaces the composer rather than sitting beside it.
    await expect(page.getByPlaceholder('Enter a research topic…')).toBeHidden();
  });

  test('an empty archive says so', async ({ page }) => {
    await mockBackend(page, { archive: [] });
    await page.goto('/');
    await page.getByRole('button', { name: /^Runs/ }).click();
    await expect(page.locator('.menu-empty')).toHaveText(/No runs archived yet/);
  });
});

test.describe('chats and history', () => {
  test('new chat, switch between chats, close chat', async ({ page }) => {
    await mockBackend(page, {
      surveyJob: [{ status: 'done', progress: [], result: makeSurveyResult({ rows: [] }), error: null }],
    });
    await page.goto('/');
    await generate(page, 'first topic');
    await expect(page.locator('.result-meta')).toBeVisible({ timeout: 15_000 });

    await page.getByRole('button', { name: '+ New Research' }).click();
    await expect(page.locator('.chat-tab')).toHaveCount(2);
    await expect(page.locator('.chat-tab.active')).toHaveText(/New chat/);
    await expect(topicInput(page)).toHaveValue('');

    await page.locator('.chat-tab', { hasText: 'first topic' }).click();
    await expect(page.locator('.result-meta')).toBeVisible();

    await page.locator('.chat-tab', { hasText: 'first topic' }).locator('.history-delete').click();
    await expect(page.locator('.chat-tab')).toHaveCount(1);
    await expect(page.locator('.chat-tab.active')).toHaveText(/New chat/);
    // Last remaining tab can't be closed
    await expect(page.locator('.chat-tab .history-delete')).toHaveCount(0);
  });

  test('open and delete a history item', async ({ page }) => {
    const api = await mockBackend(page, {
      history: [{ topic: 'Graph neural networks', saved_at: 1, fname: 'gnn.json', page_estimate: 4, strategy: 'auto' }],
      historyItems: { 'gnn.json': { ...makeResult({ paper_text: 'GNN PAPER' }), topic: 'Graph neural networks' } },
    });
    await page.goto('/');
    await openHistoryMenu(page);
    await page.locator('.history-item', { hasText: 'Graph neural networks' }).click();
    // Picking an entry closes the menu and opens it as a session.
    await expect(page.locator('.menu-panel')).toBeHidden();
    await expect(page.locator('.result-panel .paper-text')).toHaveText('GNN PAPER');
    await expect(page.locator('.chat-tab.active')).toHaveText(/Graph neural networks/);

    await openHistoryMenu(page);
    await page.locator('.history-item .history-delete').click();
    await expect(page.locator('.history-item')).toHaveCount(0);
    expect(api.requests.some((r) => r.method === 'DELETE' && r.path === '/api/history/gnn.json')).toBe(true);
    // Deleting from history doesn't close the open chat
    await expect(page.locator('.result-panel .paper-text')).toHaveText('GNN PAPER');
  });
});
