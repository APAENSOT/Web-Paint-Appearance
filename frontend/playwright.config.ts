import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/browser",
  outputDir: "./test-results/playwright",
  workers: 1,
  use: {
    baseURL: process.env.FRONTEND_URL ?? "http://localhost:5173",
    channel: "chrome",
    headless: true,
    viewport: { width: 1440, height: 1000 },
  },
});
