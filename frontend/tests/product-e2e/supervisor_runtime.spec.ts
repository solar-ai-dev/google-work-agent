import { expect, test, type Page } from "@playwright/test";
import {
  BrowserProductHarness,
  type ProductRow,
  type ProductState,
} from "./support/browser_product_harness";

let harness: BrowserProductHarness;
let page: Page;

test.describe.configure({ mode: "serial", timeout: 180_000 });

test.beforeAll(async ({ browser }, testInfo) => {
  harness = await BrowserProductHarness.create(browser, testInfo);
  page = harness.page;
});

test.afterAll(async () => {
  if (harness) await harness.close();
});

test("SUPERVISOR_E2E_001_SIMPLE_READ_SKIPS_ANALYSIS", async () => {
  const { runId, requestPayload } = await harness.startNewRun(
    "E2E:TASKS_READ 태스크를 간단히 알려줘",
  );
  expect(requestPayload.requested_mode).toBe("API_LLM");
  const completed = await harness.waitForRunStatus(runId, "COMPLETED");
  const decisions = supervisorDecisions(completed);

  await harness.assertCompletedUi(
    "Google Tasks에서 확인된 현재 할 일은 1개입니다. - E2E task",
  );
  expect(targets(decisions)).toEqual(expect.arrayContaining([
    "CONTEXT_RETRIEVAL",
    "SOLUTION_PLANNING",
    "RESPONSE_SYNTHESIS",
  ]));
  expect(targets(decisions)).not.toContain("WORK_ANALYSIS");
  expect(decisions.some((item) => item.transition_kind === "SKIP")).toBe(true);
  expect(promptIds(completed, "TASKS_READ")).not.toContain(
    "work_analysis.extract_work_facts",
  );
  expect(harness.assistantMessages(completed)).toHaveLength(1);
});

test("SUPERVISOR_E2E_002_ANALYTICAL_READ_RUNS_ANALYSIS", async () => {
  const { runId } = await harness.startNewRun(
    "E2E:ANALYTICAL_READ 메일 내용을 분석해줘",
  );
  const completed = await harness.waitForRunStatus(runId, "COMPLETED");
  const decisions = supervisorDecisions(completed);

  await harness.assertCompletedUi("E2E 결과를 정리했습니다: ANALYTICAL_READ");
  expect(targets(decisions)).toContain("WORK_ANALYSIS");
  expect(promptIds(completed, "ANALYTICAL_READ")).toEqual(expect.arrayContaining([
    "work_analysis.extract_work_facts",
    "work_analysis.assess_information_gaps",
  ]));
  expect(harness.assistantMessages(completed)).toHaveLength(1);
});

test("SUPERVISOR_E2E_003_EVIDENCE_GAP_REVISES_RETRIEVAL", async () => {
  const baseline = await harness.productState("missing-run");
  const { runId } = await harness.startNewRun(
    "E2E:EVIDENCE_BACK_EDGE 근거를 확인하고 태스크 생성안을 준비해줘",
  );
  const blocked = await harness.waitForRunStatus(runId, "BLOCKED");
  const decisions = supervisorDecisions(blocked);
  const retrievalDecisions = decisions.filter(
    (item) => item.target === "CONTEXT_RETRIEVAL",
  );

  expect(retrievalDecisions.length).toBeGreaterThanOrEqual(2);
  expect(retrievalDecisions.some((item) => item.transition_kind === "BACK_EDGE")).toBe(true);
  expect(artifactRevisions(blocked).retrieval_result).toBeGreaterThanOrEqual(2);
  expect(harness.writeCount(blocked) - harness.writeCount(baseline)).toBe(0);
  await harness.assertCompletedUi();
  await expect(page.getByText("PROFILE_LLM_LIMIT_EXHAUSTED", { exact: true })).toHaveCount(0);
  expect(harness.assistantMessages(blocked)).toHaveLength(1);
});

test("SUPERVISOR_E2E_004_CREATE_SUSPENDS_BEFORE_WRITE", async () => {
  const baseline = await harness.productState("missing-run");
  const { runId } = await harness.startNewRun(
    "E2E:CALENDAR_WRITE 검토할 일정을 만들어줘",
  );
  const waiting = await harness.waitForRunStatus(runId, "WAITING_APPROVAL");
  const decisions = supervisorDecisions(waiting);

  expect(targets(decisions)).toContain("WAITING_APPROVAL");
  expect(decisions.some((item) => (
    item.target === "WAITING_APPROVAL" && item.transition_kind === "SUSPEND"
  ))).toBe(true);
  expect(harness.writeCount(waiting) - harness.writeCount(baseline)).toBe(0);
  const card = await harness.actionCard("calendar_create_event");
  await expect(card).toContainText("E2E CALENDAR_WRITE");
  await expect(card).toContainText("실행 후 Google에서 다시 확인");
});

test("SUPERVISOR_E2E_005_REAUTH_PREEMPTS_NEW_WORK", async () => {
  const baseline = await harness.productState("missing-run");
  const { runId } = await harness.startNewRun(
    "E2E:REAUTH 재인증이 필요하면 멈추고 태스크를 만들어줘",
  );
  const waiting = await harness.waitForRunStatus(runId, "WAITING_APPROVAL");
  const planId = waiting.plans[0].id;
  const planningCalls = promptIds(waiting, "REAUTH")
    .filter((id) => id.startsWith("planning.")).length;

  await harness.approve(await harness.actionCard("tasks_create_task"));
  const reauth = await harness.waitForRunStatus(runId, "REAUTH_REQUIRED");

  expect(reauth.plans).toHaveLength(1);
  expect(reauth.plans[0].id).toBe(planId);
  expect(
    promptIds(reauth, "REAUTH").filter((id) => id.startsWith("planning.")).length,
  ).toBe(planningCalls);
  expect(harness.writeCount(reauth) - harness.writeCount(baseline)).toBe(1);
  expect(harness.effectCount(reauth) - harness.effectCount(baseline)).toBe(0);
  await expect(page.getByText(/재인증이 필요합니다/)).toBeVisible();
  await expect(page.getByText("REAUTH_REQUIRED", { exact: true })).toHaveCount(0);
});

function supervisorDecisions(state: ProductState): ProductRow[] {
  const value = state.checkpoint.supervisor_decisions;
  if (!Array.isArray(value)) throw new Error("Supervisor trace is missing");
  return value as ProductRow[];
}

function artifactRevisions(state: ProductState): Record<string, number> {
  const value = state.checkpoint.artifact_revisions;
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Artifact revision trace is missing");
  }
  return value as Record<string, number>;
}

function targets(decisions: ProductRow[]): unknown[] {
  return decisions.map((item) => item.target);
}

function promptIds(state: ProductState, scenario: string): string[] {
  return state.llm_invocations
    .filter((item) => item.scenario === scenario)
    .map((item) => item.prompt_id)
    .filter((value): value is string => typeof value === "string");
}
