import type { Page, Route } from '@playwright/test';

// Must match VITE_API_URL in frontend/.env.development
export const API = 'http://127.0.0.1:8001';

export const sampleChunk = {
  title: 'Attention Is All You Need',
  authors: 'Vaswani et al.',
  published: '2017',
  filepath: '/papers/attention.pdf',
  source: 'arxiv',
  score: 0.91,
  rerank_score: 0.87,
  text: 'The Transformer relies entirely on self-attention to compute representations.',
};

export function makeResult(overrides: Record<string, unknown> = {}) {
  return {
    paper_text: 'I. INTRODUCTION\nTransformers changed NLP.',
    num_papers: 7,
    strategy: 'hyde',
    faithfulness: 4.5,
    relevance: 3.2,
    page_estimate: 5,
    status: 'ok',
    error: null,
    retrieved_context: [sampleChunk, { ...sampleChunk, title: 'BERT', score: 0.5, rerank_score: null }],
    timings: {},
    plagiarism_report: { overall_similarity_pct: 4.2, max_sentence_similarity_pct: 12.5, ngram_overlap_pct: 1.1 },
    rouge_l: { avg_rouge_l: 0.1234 },
    ai_rewrite_passes: 2,
    humanize_applied: true,
    analysis_table: [{ Method: 'Transformer', Metric: 'BLEU 28.4' }],
    ...overrides,
  };
}

export const surveyRows = [
  {
    'No.': 1,
    Title: 'Attention Is All You Need',
    Authors: 'Vaswani et al.',
    'Journal Details (DOI / Year / Citation)': 'arXiv:1706.03762. 2017',
    'Research Gap': 'Quadratic cost on long sequences',
  },
  {
    'No.': 2,
    Title: 'Some Paper Without Link',
    Authors: 'Doe',
    'Journal Details (DOI / Year / Citation)': 'NeurIPS 2020',
    'Research Gap': 'Not mentioned',
  },
];

export function makeSurveyResult(overrides: Record<string, unknown> = {}) {
  return {
    rows: surveyRows,
    survey_paper_text: 'SURVEY DRAFT TEXT',
    pdf_path: '/out/survey.pdf',
    status: 'ok',
    ...overrides,
  };
}

type JobState =
  | { status: string; progress: unknown[]; result: unknown; error: string | null }
  /** Makes that poll of /api/jobs/:id fail with this HTTP status. */
  | { httpStatus: number };

export interface MockOptions {
  history?: Array<{ topic: string; saved_at: number; fname: string; page_estimate: number; strategy: string }>;
  historyItems?: Record<string, unknown>;
  /** Sequence of states returned on successive polls of the survey job. Last one repeats. */
  surveyJob?: JobState[];
  generateJob?: JobState[];
  refineJob?: JobState[];
  /** Status codes to return from the job-start endpoints (default 200). */
  generateStartStatus?: number;
  surveyStartStatus?: number;
  refineStartStatus?: number;
  historySaveStatus?: number;
}

export interface MockBackend {
  requests: Array<{ method: string; path: string; body: any }>;
  history: NonNullable<MockOptions['history']>;
  bodiesFor(method: string, path: string): any[];
}

export async function mockBackend(page: Page, opts: MockOptions = {}): Promise<MockBackend> {
  const history = [...(opts.history ?? [])];
  const requests: MockBackend['requests'] = [];
  const jobs: Record<string, { states: JobState[]; polls: number }> = {
    'survey-1': {
      states: opts.surveyJob ?? [
        { status: 'running', progress: [{ step: 'fetch', detail: 'Fetching arXiv papers', at: 0 }], result: null, error: null },
        { status: 'done', progress: [], result: makeSurveyResult(), error: null },
      ],
      polls: 0,
    },
    'gen-1': {
      states: opts.generateJob ?? [
        { status: 'running', progress: [{ step: 'retrieve', detail: 'Retrieving chunks', at: 0 }], result: null, error: null },
        { status: 'done', progress: [], result: makeResult(), error: null },
      ],
      polls: 0,
    },
    'refine-1': {
      states: opts.refineJob ?? [
        { status: 'done', progress: [], result: { paper_text: 'REFINED PAPER TEXT', status: 'ok', error: null }, error: null },
      ],
      polls: 0,
    },
  };

  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

  await page.route(`${API}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;
    const method = req.method();
    let body: any = null;
    try {
      body = req.postDataJSON();
    } catch {
      body = req.postData();
    }
    requests.push({ method, path, body });

    if (method === 'OPTIONS') return route.fulfill({ status: 204 });

    const startJob = (status: number | undefined, jobId: string) =>
      status && status !== 200 ? route.fulfill({ status, body: 'boom' }) : json(route, { job_id: jobId });
    if (path === '/api/survey' && method === 'POST') return startJob(opts.surveyStartStatus, 'survey-1');
    if (path === '/api/generate' && method === 'POST') return startJob(opts.generateStartStatus, 'gen-1');
    if (path === '/api/refine' && method === 'POST') return startJob(opts.refineStartStatus, 'refine-1');

    const jobMatch = path.match(/^\/api\/jobs\/(.+)$/);
    if (jobMatch) {
      const job = jobs[jobMatch[1]];
      if (!job) return json(route, { detail: 'not found' }, 404);
      const state = job.states[Math.min(job.polls, job.states.length - 1)];
      job.polls++;
      if ('httpStatus' in state) return route.fulfill({ status: state.httpStatus, body: 'unavailable' });
      return json(route, state);
    }

    if (path === '/api/history' && method === 'GET') return json(route, history);
    if (path === '/api/history/save' && method === 'POST') {
      if (opts.historySaveStatus && opts.historySaveStatus !== 200) {
        return route.fulfill({ status: opts.historySaveStatus, body: 'disk full' });
      }
      const fname = `saved_${history.length}.json`;
      history.unshift({ topic: body.topic, saved_at: Date.now(), fname, page_estimate: 5, strategy: 'hyde' });
      return json(route, { saved: true });
    }
    const histMatch = path.match(/^\/api\/history\/(.+)$/);
    if (histMatch) {
      const fname = histMatch[1];
      if (method === 'DELETE') {
        const idx = history.findIndex((h) => h.fname === fname);
        if (idx >= 0) history.splice(idx, 1);
        return json(route, { deleted: true });
      }
      return json(route, opts.historyItems?.[fname] ?? { ...makeResult(), topic: 'from history' });
    }

    if (path === '/api/fix-citations') return json(route, { paper_text: 'CITATIONS FIXED TEXT' });

    if (path.startsWith('/api/export/') || path === '/api/download') {
      return route.fulfill({ status: 200, contentType: 'application/octet-stream', body: 'FILE' });
    }

    return json(route, { detail: `unmocked ${method} ${path}` }, 500);
  });

  return {
    requests,
    history,
    bodiesFor: (m, p) => requests.filter((r) => r.method === m && r.path === p).map((r) => r.body),
  };
}
