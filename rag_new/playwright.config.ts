import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  timeout: 60_000,
  expect: {
    timeout: 30_000,
  },
  use: {
    baseURL: 'http://localhost:8501',
    headless: true,
  },
  webServer: {
    command: 'C:/Users/vvrag/NexusRAG/rag_new/venv/Scripts/python.exe -m streamlit run ui.py --server.headless true',
    url: 'http://localhost:8501',
    reuseExistingServer: true,
    timeout: 90_000,
  },
});