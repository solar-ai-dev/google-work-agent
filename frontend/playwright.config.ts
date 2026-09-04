import { defineConfig, devices } from "@playwright/test";
import { existsSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join, resolve } from "node:path";

const port = 18765;
const controlPort = 18766;
const baseURL = `http://127.0.0.1:${port}`;
const runtimeRoot = mkdtempSync(join(tmpdir(), "gwa-product-e2e-"));
process.env.GWA_BROWSER_E2E_STORAGE_STATE_PATH = join(
  runtimeRoot,
  "browser-storage-state.json",
);
const defaultPython = process.platform === "win32"
  ? (existsSync(join("..", ".venv", "Scripts", "python.exe"))
      ? ".\\.venv\\Scripts\\python.exe"
      : ".\\.venv-cpu\\Scripts\\python.exe")
  : (existsSync(join("..", ".venv", "bin", "python"))
      ? "./.venv/bin/python"
      : "./.venv-cpu/bin/python");
const python = process.env.GWA_E2E_PYTHON ?? defaultPython;

export default defineConfig({
  testDir: "./tests/product-e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  outputDir: "test-results/product-e2e",
  globalTeardown: "./tests/product-e2e/global_teardown.ts",
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
    command: `${python} -m tests.e2e.browser_product_supervisor`,
    cwd: "..",
    env: {
      ...process.env,
      GWA_ARCHITECTURE_FINAL_CUTOVER: "1",
      GWA_BROWSER_E2E_PORT: String(port),
      GWA_BROWSER_E2E_CONTROL_PORT: String(controlPort),
      GWA_BROWSER_E2E_RUNTIME_ROOT: runtimeRoot,
      PYTHONPATH: [resolve("..", "src"), process.env.PYTHONPATH]
        .filter((value): value is string => Boolean(value))
        .join(delimiter),
    },
    url: `http://127.0.0.1:${controlPort}/health/live`,
    reuseExistingServer: false,
    timeout: 120_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
