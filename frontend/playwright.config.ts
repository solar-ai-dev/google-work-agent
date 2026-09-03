import { defineConfig, devices } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const port = 18765;
const baseURL = `http://127.0.0.1:${port}`;
const runtimeRoot = mkdtempSync(join(tmpdir(), "gwa-product-e2e-"));
const python = process.platform === "win32"
  ? ".\\.venv\\Scripts\\python.exe"
  : "./.venv/bin/python";

export default defineConfig({
  testDir: "./tests/product-e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  outputDir: "test-results/product-e2e",
  use: {
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chrome",
      use: { ...devices["Desktop Chrome"], channel: "chrome" },
    },
  ],
  webServer: {
    command: `${python} -m tests.e2e.browser_product_server`,
    cwd: "..",
    env: {
      ...process.env,
      GWA_ARCHITECTURE_FINAL_CUTOVER: "1",
      GWA_BROWSER_E2E_PORT: String(port),
      GWA_BROWSER_E2E_RUNTIME_ROOT: runtimeRoot,
    },
    url: `${baseURL}/health/live`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
