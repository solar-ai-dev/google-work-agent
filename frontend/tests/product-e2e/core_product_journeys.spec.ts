import { expect, test, type Page } from "@playwright/test";
import {
  BrowserProductHarness,
  type ProductRow,
  type ProductState,
  type StartedRun,
} from "./support/browser_product_harness";

let harness: BrowserProductHarness;
let page: Page;

test.describe.configure({ mode: "serial" });

test.beforeAll(async ({ browser }, testInfo) => {
  harness = await BrowserProductHarness.create(browser, testInfo);
  page = harness.page;
});

test.afterAll(async () => {
  if (harness) await harness.close();
});

test("E2E_001_ANSWER_ONLY_PASS", async () => {
  const baseline = await productState("missing-run");
  const { runId } = await startNewRun("E2E:ANSWER_ONLY 현재 상태를 설명해줘");
  const completed = await waitForRunStatus(runId, "COMPLETED");

  await assertCompletedUi("현재 요청을 처리할 준비가 되어 있습니다.");
  expect(completed.run.terminal_result_kind).toBe("SUCCESS");
  expect(completed.plans).toHaveLength(0);
  expect(completed.actions).toHaveLength(0);
  expect(completed.approvals).toHaveLength(0);
  expect(completed.messages.filter((message) => message.role === "ASSISTANT")).toHaveLength(1);
  expect(writeCount(completed) - writeCount(baseline)).toBe(0);
  expect(auditTypes(completed)).toContain("RUN_COMPLETED");
});

test("E2E_002_GMAIL_READ_PASS", async () => {
  await beginNewConversation();
  const resourceCheckbox = page.getByRole("checkbox", { name: "E2E mail 선택" });
  await expect(resourceCheckbox).toBeVisible();
  await resourceCheckbox.check();
  await expect(page.getByText("요청에 사용할 자료 1개")).toBeVisible();
  await expect(page.getByText("E2E mail", { exact: true }).last()).toBeVisible();
  const baseline = await productState("missing-run");

  const { runId, requestPayload } = await startRun(
    "E2E:GMAIL_READ 선택한 메일의 핵심 내용을 알려줘",
  );
  expect(requestPayload.entry_mode).toBe("RESOURCE_SELECTED");
  expect(requestPayload.selected_resource_handles).toEqual([expect.any(String)]);
  const completed = await waitForRunStatus(runId, "COMPLETED");

  await assertCompletedUi("선택한 메일의 핵심 내용은 deterministic Gmail evidence입니다.");
  expect(completed.run.terminal_result_kind).toBe("SUCCESS");
  expect(completed.actions).toHaveLength(0);
  expect(toolCount(completed, "gmail_search_threads") - toolCount(baseline, "gmail_search_threads")).toBe(0);
  expect(toolCount(completed, "gmail_get_thread") - toolCount(baseline, "gmail_get_thread")).toBe(1);
  expect(writeCount(completed) - writeCount(baseline)).toBe(0);
  expect(completed.messages.filter((message) => message.role === "ASSISTANT")).toHaveLength(1);

  await resourceCheckbox.uncheck();
  await expect(page.getByText("요청에 사용할 자료 1개")).toHaveCount(0);
});

test("E2E_003_TASK_CREATE_APPROVE_VERIFY_PASS", async () => {
  await beginNewConversation();
  const baseline = await productState("missing-run");
  const { runId } = await startRun("E2E:APPROVED_WRITE 새 태스크를 만들어줘");
  const waiting = await waitForRunStatus(runId, "WAITING_APPROVAL");

  const card = await actionCard("tasks_create_task");
  await expect(card).toContainText("E2E APPROVED_WRITE");
  await expect(card).toContainText("실행 후 Google에서 다시 확인");
  expect(toolCount(waiting, "tasks_create_task") - toolCount(baseline, "tasks_create_task")).toBe(0);
  await approve(card);
  const completed = await waitForRunStatus(runId, "COMPLETED");

  await assertCompletedUi();
  await expect(page.getByRole("article", { name: "에이전트 응답" })).toContainText(
    "Google에서 결과를 다시 확인했습니다",
  );
  expect(completed.run.terminal_result_kind).toBe("SUCCESS");
  expect(completed.actions.map((action) => action.status)).toEqual(["VERIFIED"]);
  expect(completed.execution_attempts.map((attempt) => attempt.status)).toEqual(["SUCCEEDED"]);
  expect(completed.verifications.map((verification) => verification.status)).toEqual(["VERIFIED"]);
  expect(assistantMessages(completed)).toHaveLength(1);
  expect(toolCount(completed, "tasks_create_task") - toolCount(baseline, "tasks_create_task")).toBe(1);
  expect(toolCount(completed, "tasks_get_task") - toolCount(baseline, "tasks_get_task")).toBe(1);
  expect(auditTypes(completed)).toEqual(expect.arrayContaining(["ACTION_APPROVED", "RUN_COMPLETED"]));
});

test("E2E_004_CALENDAR_CREATE_APPROVE_VERIFY_PASS", async () => {
  await beginNewConversation();
  const baseline = await productState("missing-run");
  const { runId } = await startRun("E2E:CALENDAR_WRITE 새 일정을 만들어줘");
  const waiting = await waitForRunStatus(runId, "WAITING_APPROVAL");

  const card = await actionCard("calendar_create_event");
  expect(toolCount(waiting, "calendar_create_event") - toolCount(baseline, "calendar_create_event")).toBe(0);
  await approve(card);
  const completed = await waitForRunStatus(runId, "COMPLETED");

  await assertCompletedUi();
  expect(completed.run.terminal_result_kind).toBe("SUCCESS");
  expect(completed.actions.map((action) => action.status)).toEqual(["VERIFIED"]);
  expect(completed.verifications.map((verification) => verification.status)).toEqual(["VERIFIED"]);
  expect(assistantMessages(completed)).toHaveLength(1);
  expect(toolCount(completed, "calendar_create_event") - toolCount(baseline, "calendar_create_event")).toBe(1);
  expect(toolCount(completed, "calendar_get_event") - toolCount(baseline, "calendar_get_event")).toBe(1);
});

test("E2E_005_REJECT_WRITE_ZERO_PASS", async () => {
  await beginNewConversation();
  const baseline = await productState("missing-run");
  const { runId } = await startRun("E2E:REJECTION 태스크 생성 계획을 준비해줘");
  const waiting = await waitForRunStatus(runId, "WAITING_APPROVAL");

  const card = await actionCard("tasks_create_task");
  expect(writeCount(waiting) - writeCount(baseline)).toBe(0);
  await card.getByRole("button", { name: "이번에는 실행하지 않을게요", exact: true }).click();
  const completed = await waitForRunStatus(runId, "COMPLETED");

  await assertCompletedUi();
  await expect(page.getByRole("article", { name: "에이전트 응답" })).toContainText(
    "사용자 선택에 따라 실행하지 않았습니다",
  );
  expect(completed.run.terminal_result_kind).toBe("PARTIAL");
  expect(completed.actions.map((action) => action.status)).toEqual(["REJECTED"]);
  expect(completed.execution_attempts).toHaveLength(0);
  expect(completed.verifications).toHaveLength(0);
  expect(assistantMessages(completed)).toHaveLength(1);
  expect(writeCount(completed) - writeCount(baseline)).toBe(0);
  expect(auditTypes(completed)).toEqual(expect.arrayContaining(["ACTION_REJECTED", "RUN_COMPLETED"]));
});

test("E2E_006_CONFIRMATION_RESUME_PASS", async () => {
  await beginNewConversation();
  const baseline = await productState("missing-run");
  const { runId } = await startRun("E2E:RESTART_RESUME 모호한 대상을 처리해줘");
  const interrupted = await waitForRunStatus(runId, "WAITING_CONFIRMATION");

  const confirmation = page.getByRole("article").filter({ hasText: "추가 확인" });
  await expect(confirmation).toBeVisible();
  const originalThreadId = interrupted.workflow_binding.langgraph_thread_id;
  const originalRunCount = interrupted.run_count;
  await confirmation.getByRole("textbox", { name: "확인 응답" }).fill("E2E Tasks 목록을 사용해줘.");
  await confirmation.getByRole("button", { name: "응답 보내기" }).click();
  const waiting = await waitForRunStatus(runId, "WAITING_APPROVAL");

  expect(waiting.run_count).toBe(originalRunCount);
  expect(waiting.run_count - baseline.run_count).toBe(1);
  expect(waiting.workflow_binding.langgraph_thread_id).toBe(originalThreadId);
  const identifyGoalCalls = waiting.llm_invocations.filter(
    (invocation) => invocation.scenario === "RESTART_RESUME"
      && invocation.prompt_id === "request_understanding.identify_goal",
  );
  // LangGraph re-enters only the interrupted semantic-owner subgraph and
  // injects the response there; the Main workflow, Run, and thread stay intact.
  expect(
    identifyGoalCalls.map((invocation) => Boolean(invocation.has_confirmation_response)),
  ).toEqual([false, true]);
  expect(auditTypes(waiting)).toEqual(expect.arrayContaining(["CONFIRMATION_REQUESTED", "CONFIRMATION_RESUMED"]));

  await approve(await actionCard("tasks_create_task"));
  const completed = await waitForRunStatus(runId, "COMPLETED");
  await assertCompletedUi();
  expect(completed.workflow_binding.langgraph_thread_id).toBe(originalThreadId);
  expect(assistantMessages(completed)).toHaveLength(1);
  expect(toolCount(completed, "tasks_create_task") - toolCount(baseline, "tasks_create_task")).toBe(1);
});

test("E2E_007_PARTIAL_APPROVAL_PASS", async () => {
  await beginNewConversation();
  const baseline = await productState("missing-run");
  const { runId } = await startRun("E2E:PARTIAL_APPROVAL 태스크와 일정을 준비해줘");
  const waiting = await waitForRunStatus(runId, "WAITING_APPROVAL");

  expect(waiting.actions).toHaveLength(2);
  expect(waiting.action_dependencies).toHaveLength(0);
  const taskCard = await actionCard("tasks_create_task");
  const calendarCard = await actionCard("calendar_create_event");
  const rejectCalendar = calendarCard.getByRole("button", { name: "이번에는 실행하지 않을게요", exact: true });
  await approve(taskCard);
  await expect(rejectCalendar).toBeEnabled();
  await rejectCalendar.click();
  const completed = await waitForRunStatus(runId, "COMPLETED");

  await assertCompletedUi();
  await expect(page.getByRole("article", { name: "에이전트 응답" })).toContainText(
    "사용자 선택에 따라 실행하지 않았습니다",
  );
  const statusByTool = Object.fromEntries(completed.actions.map((action) => [action.tool_name, action.status]));
  expect(statusByTool).toEqual({ calendar_create_event: "REJECTED", tasks_create_task: "VERIFIED" });
  expect(completed.run.terminal_result_kind).toBe("PARTIAL");
  expect(toolCount(completed, "tasks_create_task") - toolCount(baseline, "tasks_create_task")).toBe(1);
  expect(toolCount(completed, "calendar_create_event") - toolCount(baseline, "calendar_create_event")).toBe(0);
  expect(completed.verifications).toHaveLength(1);
  expect(completed.verifications[0].status).toBe("VERIFIED");
  expect(assistantMessages(completed)).toHaveLength(1);
});

test("E2E_008_REFRESH_SSE_RECOVERY_PASS", async () => {
  await beginNewConversation();
  const baseline = await productState("missing-run");
  const { runId } = await startRun("E2E:APPROVED_WRITE 새로고침 후 태스크를 만들어줘");
  const waiting = await waitForRunStatus(runId, "WAITING_APPROVAL");
  await expect(await actionCard("tasks_create_task")).toBeVisible();
  const originalRunCount = waiting.run_count;
  const originalCommandCount = waiting.command_count;
  const originalThreadId = waiting.workflow_binding.langgraph_thread_id;

  await page.reload();
  await expect(page.getByRole("region", { name: "에이전트 대화" })).toBeVisible();
  await expect(await actionCard("tasks_create_task")).toBeVisible();
  const restored = await waitForRunStatus(runId, "WAITING_APPROVAL");
  expect(restored.run_count).toBe(originalRunCount);
  expect(restored.command_count).toBe(originalCommandCount);
  expect(restored.workflow_binding.langgraph_thread_id).toBe(originalThreadId);
  expect(writeCount(restored) - writeCount(baseline)).toBe(0);

  await approve(await actionCard("tasks_create_task"));
  const completed = await waitForRunStatus(runId, "COMPLETED");
  await assertCompletedUi();
  expect(completed.run_count).toBe(originalRunCount);
  expect(completed.workflow_binding.langgraph_thread_id).toBe(originalThreadId);
  expect(toolCount(completed, "tasks_create_task") - toolCount(baseline, "tasks_create_task")).toBe(1);
  expect(completed.actions.map((action) => action.status)).toEqual(["VERIFIED"]);
  expect(assistantMessages(completed)).toHaveLength(1);
});

async function beginNewConversation(): Promise<void> {
  await harness.beginNewConversation();
}

async function startNewRun(requestText: string): Promise<StartedRun> {
  return harness.startNewRun(requestText);
}

async function startRun(requestText: string): Promise<StartedRun> {
  return harness.startRun(requestText);
}

async function productState(runId: string): Promise<ProductState> {
  return harness.productState(runId);
}

async function waitForRunStatus(runId: string, status: string): Promise<ProductState> {
  return harness.waitForRunStatus(runId, status);
}

async function actionCard(toolName: string) {
  return harness.actionCard(toolName);
}

async function approve(card: Awaited<ReturnType<typeof actionCard>>): Promise<void> {
  await harness.approve(card);
}

async function assertCompletedUi(answer?: string): Promise<void> {
  await harness.assertCompletedUi(answer);
}

function toolCount(state: ProductState, toolName: string): number {
  return harness.toolCount(state, toolName);
}

function writeCount(state: ProductState): number {
  return harness.writeCount(state);
}

function auditTypes(state: ProductState): unknown[] {
  return harness.auditTypes(state);
}

function assistantMessages(state: ProductState): ProductRow[] {
  return harness.assistantMessages(state);
}
