import {
  expect,
  type Browser,
  type BrowserContext,
  type Locator,
  type Page,
  type TestInfo,
} from "@playwright/test";
import { existsSync } from "node:fs";

export type ProductRow = Record<string, unknown>;

export type ProductState = {
  run: ProductRow;
  plans: ProductRow[];
  actions: ProductRow[];
  action_dependencies: ProductRow[];
  approvals: ProductRow[];
  execution_attempts: ProductRow[];
  verifications: ProductRow[];
  messages: ProductRow[];
  workflow_binding: ProductRow;
  workflow_handoffs: ProductRow[];
  checkpoint: ProductRow;
  recovery: ProductRow;
  audit_events: ProductRow[];
  run_count: number;
  command_count: number;
  command_receipts: ProductRow[];
  mcp_events: ProductRow[];
  mcp_state: ProductRow;
  mcp_runtime_events: ProductRow[];
  llm_invocations: ProductRow[];
};

export type StartedRun = {
  runId: string;
  requestPayload: Record<string, unknown>;
};

export type RunSnapshot = ProductRow & {
  run: ProductRow;
  actions: ProductRow[];
  pending_interrupt?: ProductRow | null;
  recovery?: ProductRow | null;
};

export const baseURL = "http://127.0.0.1:18765";
const controlURL = "http://127.0.0.1:18766";
const requestHeaders = {
  Origin: baseURL,
  "Sec-Fetch-Site": "same-origin",
  "Sec-Fetch-Mode": "cors",
  "Sec-Fetch-Dest": "empty",
};
const writeTools = new Set([
  "calendar_create_event",
  "gmail_create_draft",
  "gmail_send_message",
  "tasks_create_task",
]);

export class BrowserProductHarness {
  readonly context: BrowserContext;
  readonly page: Page;
  private restartCredentialSequence = 0;

  private constructor(context: BrowserContext, page: Page) {
    this.context = context;
    this.page = page;
  }

  static async create(browser: Browser, testInfo: TestInfo): Promise<BrowserProductHarness> {
    testInfo.setTimeout(120_000);
    const storageStatePath = process.env.GWA_BROWSER_E2E_STORAGE_STATE_PATH;
    const hasStorageState = storageStatePath !== undefined && existsSync(storageStatePath);
    const context = await browser.newContext(
      hasStorageState ? { storageState: storageStatePath } : undefined,
    );
    const page = await context.newPage();
    const harness = new BrowserProductHarness(context, page);
    await harness.openAndBootstrap(!hasStorageState);
    if (storageStatePath !== undefined) {
      await context.storageState({ path: storageStatePath });
    }
    return harness;
  }

  async close(): Promise<void> {
    const storageStatePath = process.env.GWA_BROWSER_E2E_STORAGE_STATE_PATH;
    if (storageStatePath !== undefined) {
      await this.context.storageState({ path: storageStatePath });
    }
    await this.context.close();
  }

  async openAndBootstrap(useBootstrapSecret = true): Promise<void> {
    const entryPath = useBootstrapSecret
      ? "/#bootstrap_secret=browser-product-e2e-bootstrap-secret"
        + "&service_instance_id=browser-product-e2e-service"
      : "/";
    await this.page.goto(entryPath);
    const onboarding = this.page
      .getByRole("main")
      .getByRole("heading", { name: "Google Work Agent 시작하기" });
    const composer = this.page.getByRole("textbox", {
      name: /선택한 .*업무를 요청하세요/,
    });
    await expect.poll(async () => (
      await onboarding.count() + await composer.count()
    )).toBeGreaterThan(0);
    if (await composer.isVisible()) {
      await this.expectMainUi();
      return;
    }
    await expect(onboarding).toBeVisible();
    await expect(
      this.page.getByText("설정 상태를 확인하고 있습니다.", { exact: true }),
    ).toHaveCount(0);
    const consent = this.page.getByLabel(
      "외부 LLM으로 요청 컨텍스트를 전송하는 데 동의합니다.",
    );
    if (await consent.isVisible()) {
      await consent.check();
      await this.page.getByRole("button", { name: "동의 저장" }).click();
    }
    await expect(this.page.getByText("완료 · 개인정보·외부 LLM 전송 동의")).toBeVisible();
    const apiKey = this.page.getByLabel("API Key");
    if (await apiKey.isVisible()) {
      await apiKey.fill("browser-product-e2e-gemini-key");
      await this.page.getByLabel("저장 방식").selectOption("SESSION_ONLY");
      await this.page.getByRole("button", { name: "저장하고 연결 검사" }).click();
    }
    await expect(this.page.getByText("완료 · API LLM 연결")).toBeVisible();
    const completeSetup = this.page.getByRole("button", { name: "설정 완료하고 시작" });
    await expect(completeSetup).toBeEnabled();
    await completeSetup.click();
    await this.expectMainUi();
  }

  async beginNewConversation(): Promise<void> {
    await this.page.getByRole("button", { name: /새 대화/ }).click();
    await expect(this.page.getByRole("region", { name: "Action Plan" })).toHaveCount(0);
  }

  async startNewRun(requestText: string): Promise<StartedRun> {
    await this.beginNewConversation();
    return this.startRun(requestText);
  }

  async startRun(requestText: string): Promise<StartedRun> {
    const composer = this.page.getByRole("textbox", {
      name: /선택한 .*업무를 요청하세요/,
    });
    await composer.fill(requestText);
    const responsePromise = this.page.waitForResponse((response) => (
      response.request().method() === "POST"
        && new URL(response.url()).pathname === "/api/v1/runs"
    ));
    await this.page.getByRole("button", { name: "보내기", exact: true }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(202);
    const payload = await response.json() as { run_id: string };
    return {
      runId: payload.run_id,
      requestPayload: response.request().postDataJSON() as Record<string, unknown>,
    };
  }

  async productState(runId: string): Promise<ProductState> {
    const response = await this.context.request.get(
      `${baseURL}/__e2e__/state/${encodeURIComponent(runId)}`,
    );
    expect(response.ok()).toBe(true);
    return await response.json() as ProductState;
  }

  async runSnapshot(runId: string): Promise<RunSnapshot> {
    const response = await this.context.request.get(
      `${baseURL}/api/v1/runs/${encodeURIComponent(runId)}`,
      { headers: { ...requestHeaders, "X-API-Contract-Version": "1" } },
    );
    expect(response.ok()).toBe(true);
    return await response.json() as RunSnapshot;
  }

  async waitForRunStatus(runId: string, status: string): Promise<ProductState> {
    let current = await this.productState(runId);
    await expect.poll(async () => {
      current = await this.productState(runId);
      return current.run.status;
    }).toBe(status);
    return current;
  }

  async waitForActionStatus(runId: string, status: string): Promise<ProductState> {
    let current = await this.productState(runId);
    await expect.poll(async () => {
      current = await this.productState(runId);
      return current.actions.some((action) => action.status === status);
    }).toBe(true);
    return current;
  }

  async waitForActionCommand(runId: string, command: string): Promise<ProductState> {
    await expect.poll(async () => {
      const snapshot = await this.runSnapshot(runId);
      return snapshot.actions.some((action) => (
        Array.isArray(action.next_allowed_commands)
          && action.next_allowed_commands.includes(command)
      ));
    }).toBe(true);
    return this.productState(runId);
  }

  async waitForPrompt(runId: string, promptId: string): Promise<ProductState> {
    let current = await this.productState(runId);
    await expect.poll(async () => {
      current = await this.productState(runId);
      return current.llm_invocations.some((item) => item.prompt_id === promptId);
    }).toBe(true);
    return current;
  }

  async actionCard(toolName: string): Promise<Locator> {
    const card = this.page
      .getByRole("region", { name: "Action Plan" })
      .getByRole("article")
      .filter({ hasText: toolName });
    await expect(card).toBeVisible();
    return card;
  }

  async approve(card: Locator): Promise<void> {
    const acknowledgements = card.getByRole("checkbox");
    for (let index = 0; index < await acknowledgements.count(); index += 1) {
      await acknowledgements.nth(index).check();
    }
    await card.getByRole("button", {
      name: /^(네, 실행해 주세요|위험을 확인하고 실행해 주세요|충돌을 알고도 실행해 주세요|그래도 새로 만들어 주세요)$/,
    }).click();
  }

  async assertCompletedUi(answer?: string): Promise<void> {
    await expect(this.page.getByText("메인 에이전트 · 작업을 완료했습니다.", { exact: true })).toBeVisible();
    let assistantMessage = this.page.getByRole("article", { name: "에이전트 응답" });
    if (answer) assistantMessage = assistantMessage.filter({ hasText: answer });
    await expect(assistantMessage).toBeVisible();
  }

  async restartBackend(): Promise<Record<string, unknown>> {
    const response = await this.context.request.post(`${controlURL}/restart`, {
      data: { disable_crash: true },
    });
    expect(response.ok()).toBe(true);
    return await response.json() as Record<string, unknown>;
  }

  async restoreSessionAfterRestart(): Promise<void> {
    const bootstrap = await this.context.request.post(`${baseURL}/api/v1/session/bootstrap`, {
      headers: requestHeaders,
      data: {
        schema_version: 1,
        bootstrap_secret: "browser-product-e2e-bootstrap-secret",
        frontend_api_contract_version: "1",
      },
    });
    expect(bootstrap.ok()).toBe(true);
    this.restartCredentialSequence += 1;
    const credential = await this.context.request.put(
      `${baseURL}/api/v1/credentials/llm/gemini`,
      {
        headers: requestHeaders,
        data: {
          schema_version: 1,
          command_id: `browser-e2e-restart-credential-${this.restartCredentialSequence}`,
          api_key: "browser-product-e2e-gemini-key",
          storage_mode: "SESSION_ONLY",
        },
      },
    );
    expect(credential.ok()).toBe(true);
    await this.page.reload();
    await this.expectMainUi();
  }

  async completeReauthFault(): Promise<void> {
    const response = await this.context.request.post(
      `${baseURL}/__e2e__/fault/reauth-complete`,
    );
    expect(response.ok()).toBe(true);
    await this.page.reload();
    await this.expectMainUi();
  }

  toolCount(state: ProductState, toolName: string): number {
    return state.mcp_events.filter((event) => event.tool_name === toolName).length;
  }

  writeCount(state: ProductState): number {
    return state.mcp_events.filter((event) => writeTools.has(String(event.tool_name))).length;
  }

  effectCount(state: ProductState): number {
    const resources = state.mcp_state.resources;
    return resources && typeof resources === "object"
      ? Object.keys(resources).length
      : 0;
  }

  mcpProcessStartCount(state: ProductState): number {
    return state.mcp_runtime_events.filter(
      (event) => event.event_type === "PROCESS_STARTED",
    ).length;
  }

  auditTypes(state: ProductState): unknown[] {
    return state.audit_events.map((event) => event.event_type);
  }

  assistantMessages(state: ProductState): ProductRow[] {
    return state.messages.filter((message) => message.role === "ASSISTANT");
  }

  private async expectMainUi(): Promise<void> {
    await expect(this.page.getByRole("textbox", {
      name: /선택한 .*업무를 요청하세요/,
    })).toBeVisible();
    await expect(this.page.getByRole("button", { name: /새 대화/ })).toBeVisible();
  }
}
