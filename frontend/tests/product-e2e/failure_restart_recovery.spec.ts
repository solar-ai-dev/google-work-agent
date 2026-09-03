import { expect, test, type Page } from "@playwright/test";
import {
  BrowserProductHarness,
  type ProductRow,
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

test("F_E2E_001_UNKNOWN_RESULT_PASS", async () => {
  const baseline = await harness.productState("missing-run");
  const { runId } = await harness.startNewRun(
    "E2E:UNKNOWN_RESULT_RECOVERY 외부 응답 유실 태스크를 만들어줘",
  );
  const waiting = await harness.waitForRunStatus(runId, "WAITING_APPROVAL");
  await harness.approve(await harness.actionCard("tasks_create_task"));
  const completed = await harness.waitForRunStatus(runId, "COMPLETED");

  // Canonical recovery performs the bounded existing-result lookup before it
  // promotes the Run to RECOVERY_REQUIRED. A single durable match therefore
  // recovers and verifies in the same workflow continuation.
  await harness.assertCompletedUi();
  expect(completed.run.terminal_result_kind).toBe("SUCCESS");
  expect(completed.actions.map((action) => action.status)).toEqual(["VERIFIED"]);
  expect(completed.execution_attempts.map((attempt) => attempt.status)).toEqual([
    "SUCCEEDED",
  ]);
  expect(harness.writeCount(completed) - harness.writeCount(baseline)).toBe(1);
  expect(harness.effectCount(completed) - harness.effectCount(baseline)).toBe(1);
  expect(
    harness.toolCount(completed, "search_by_recovery_fingerprint")
      - harness.toolCount(baseline, "search_by_recovery_fingerprint"),
  ).toBe(1);
  expect(harness.auditTypes(completed)).toEqual(
    expect.arrayContaining(["WRITE_UNKNOWN_RESULT", "WRITE_RECOVERED"]),
  );
  expect(waiting.actions[0].id).toBe(completed.actions[0].id);
});

test("F_E2E_002_RESPONSE_LOSS_PASS", async () => {
  const baseline = await harness.productState("missing-run");
  const { runId } = await harness.startNewRun(
    "E2E:RESPONSE_LOSS 성공 응답이 유실되는 태스크를 만들어줘",
  );
  await harness.waitForRunStatus(runId, "WAITING_APPROVAL");
  await harness.approve(await harness.actionCard("tasks_create_task"));
  const completed = await harness.waitForRunStatus(runId, "COMPLETED");

  expect(completed.run.terminal_result_kind).toBe("SUCCESS");
  expect(harness.writeCount(completed) - harness.writeCount(baseline)).toBe(1);
  expect(harness.effectCount(completed) - harness.effectCount(baseline)).toBe(1);
  expect(
    harness.toolCount(completed, "search_by_recovery_fingerprint")
      - harness.toolCount(baseline, "search_by_recovery_fingerprint"),
  ).toBe(1);
  expect(completed.execution_attempts.map((attempt) => attempt.status)).toEqual([
    "SUCCEEDED",
  ]);
});

test("F_E2E_003_PROCESS_RESTART_PASS", async () => {
  const baseline = await harness.productState("missing-run");
  const started = await harness.startNewRun(
    "E2E:PROCESS_RESTART durable checkpoint 이후 태스크를 만들어줘",
  );
  await harness.waitForPrompt(started.runId, "retrieval.select_evidence");
  const interrupted = await harness.waitForRunStatus(started.runId, "RETRIEVING");
  const originalThreadId = interrupted.workflow_binding.langgraph_thread_id;
  const originalCheckpointGeneration = Number(interrupted.checkpoint.checkpoint_generation);
  const originalRunCount = interrupted.run_count;
  const startCommandId = String(started.requestPayload.command_id);

  await harness.restartBackend();
  await harness.restoreSessionAfterRestart();
  const restored = await harness.waitForRunStatus(started.runId, "WAITING_APPROVAL");

  expect(restored.run_count).toBe(originalRunCount);
  expect(restored.workflow_binding.langgraph_thread_id).toBe(originalThreadId);
  expect(restored.checkpoint.langgraph_thread_id).toBe(originalThreadId);
  expect(Number(restored.checkpoint.checkpoint_generation)).toBeGreaterThanOrEqual(
    originalCheckpointGeneration,
  );
  expect(
    restored.command_receipts.filter((receipt) => receipt.command_id === startCommandId),
  ).toHaveLength(1);
  expect(uniqueValues(restored.workflow_handoffs, "handoff_id")).toHaveLength(
    restored.workflow_handoffs.length,
  );
  expect(harness.writeCount(restored) - harness.writeCount(baseline)).toBe(0);

  await harness.approve(await harness.actionCard("tasks_create_task"));
  const completed = await harness.waitForRunStatus(started.runId, "COMPLETED");
  expect(completed.run.terminal_result_kind).toBe("SUCCESS");
  expect(harness.writeCount(completed) - harness.writeCount(baseline)).toBe(1);
  expect(harness.effectCount(completed) - harness.effectCount(baseline)).toBe(1);
  expect(completed.verifications.map((verification) => verification.status)).toEqual([
    "VERIFIED",
  ]);
});

test("F_E2E_004_CONFIRMATION_RESTART_PASS", async () => {
  const started = await harness.startNewRun(
    "E2E:RESTART_RESUME restart 후 모호한 태스크를 처리해줘",
  );
  const interrupted = await harness.waitForRunStatus(started.runId, "WAITING_CONFIRMATION");
  const originalSnapshot = await harness.runSnapshot(started.runId);
  const originalInterrupt = requiredRow(originalSnapshot.pending_interrupt);
  const originalThreadId = interrupted.workflow_binding.langgraph_thread_id;
  const originalRunCount = interrupted.run_count;

  await harness.restartBackend();
  await harness.restoreSessionAfterRestart();
  const restored = await harness.waitForRunStatus(started.runId, "WAITING_CONFIRMATION");
  const restoredSnapshot = await harness.runSnapshot(started.runId);
  const restoredInterrupt = requiredRow(restoredSnapshot.pending_interrupt);

  expect(restored.run_count).toBe(originalRunCount);
  expect(restored.workflow_binding.langgraph_thread_id).toBe(originalThreadId);
  expect(restoredInterrupt.interrupt_id).toBe(originalInterrupt.interrupt_id);
  await expect(confirmationCard()).toBeVisible();
  await confirmationCard().getByRole("textbox", { name: "확인 응답" }).fill(
    "E2E Tasks 목록을 사용해줘.",
  );
  await confirmationCard().getByRole("button", { name: "응답 보내기" }).click();
  const waiting = await harness.waitForRunStatus(started.runId, "WAITING_APPROVAL");
  expect(
    harness.auditTypes(waiting).filter((eventType) => eventType === "RUN_ANALYSIS_STARTED"),
  ).toHaveLength(1);

  await harness.approve(await harness.actionCard("tasks_create_task"));
  const completed = await harness.waitForRunStatus(started.runId, "COMPLETED");
  expect(completed.workflow_binding.langgraph_thread_id).toBe(originalThreadId);
  expect(completed.run.terminal_result_kind).toBe("SUCCESS");
});

test("F_E2E_005_APPROVAL_RESTART_PASS", async () => {
  const baseline = await harness.productState("missing-run");
  const { runId } = await harness.startNewRun(
    "E2E:APPROVED_WRITE approval restart 태스크를 만들어줘",
  );
  const waiting = await harness.waitForRunStatus(runId, "WAITING_APPROVAL");
  const originalPlanId = waiting.plans[0].id;
  const originalActionId = waiting.actions[0].id;
  const originalThreadId = waiting.workflow_binding.langgraph_thread_id;
  expect(harness.writeCount(waiting) - harness.writeCount(baseline)).toBe(0);

  await harness.restartBackend();
  await harness.restoreSessionAfterRestart();
  const restored = await harness.waitForRunStatus(runId, "WAITING_APPROVAL");

  expect(restored.plans[0].id).toBe(originalPlanId);
  expect(restored.actions[0].id).toBe(originalActionId);
  expect(restored.workflow_binding.langgraph_thread_id).toBe(originalThreadId);
  expect(harness.writeCount(restored) - harness.writeCount(baseline)).toBe(0);
  await harness.approve(await harness.actionCard("tasks_create_task"));
  const completed = await harness.waitForRunStatus(runId, "COMPLETED");
  expect(completed.actions[0].id).toBe(originalActionId);
  expect(harness.writeCount(completed) - harness.writeCount(baseline)).toBe(1);
  expect(harness.effectCount(completed) - harness.effectCount(baseline)).toBe(1);
  expect(completed.verifications.map((verification) => verification.status)).toEqual([
    "VERIFIED",
  ]);
});

test("F_E2E_006_REAUTH_PASS", async () => {
  const baseline = await harness.productState("missing-run");
  const { runId } = await harness.startNewRun(
    "E2E:REAUTH 재인증 후 태스크를 만들어줘",
  );
  const waiting = await harness.waitForRunStatus(runId, "WAITING_APPROVAL");
  const originalPlanId = waiting.plans[0].id;
  const originalActionId = waiting.actions[0].id;
  await harness.approve(await harness.actionCard("tasks_create_task"));
  const reauth = await harness.waitForRunStatus(runId, "REAUTH_REQUIRED");

  expect(reauth.plans[0].id).toBe(originalPlanId);
  expect(reauth.actions[0].id).toBe(originalActionId);
  expect(harness.effectCount(reauth) - harness.effectCount(baseline)).toBe(0);
  await expect(page.getByText("REAUTH_REQUIRED", { exact: true })).toBeVisible();

  await harness.completeReauthFault();
  const resumed = await harness.waitForRunStatus(runId, "WAITING_APPROVAL");
  expect(resumed.plans[0].id).toBe(originalPlanId);
  expect(resumed.actions[0].id).toBe(originalActionId);
  expect(resumed.actions[0].status).toBe("FAILED");
  await (await harness.actionCard("tasks_create_task"))
    .getByRole("button", { name: "다시 준비" })
    .click();
  await harness.waitForActionCommand(runId, "APPROVE_ACTION");
  await harness.approve(await harness.actionCard("tasks_create_task"));
  const completed = await harness.waitForRunStatus(runId, "COMPLETED");

  expect(completed.run.terminal_result_kind).toBe("SUCCESS");
  expect(completed.actions[0].id).toBe(originalActionId);
  expect(harness.effectCount(completed) - harness.effectCount(baseline)).toBe(1);
  expect(harness.writeCount(completed) - harness.writeCount(baseline)).toBe(2);
  expect(completed.verifications.map((verification) => verification.status)).toEqual([
    "VERIFIED",
  ]);
});

test("F_E2E_007_VERIFICATION_MISMATCH_PASS", async () => {
  const baseline = await harness.productState("missing-run");
  const { runId } = await harness.startNewRun(
    "E2E:VERIFICATION_MISMATCH 검증 불일치 일정을 만들어줘",
  );
  await harness.waitForRunStatus(runId, "WAITING_APPROVAL");
  await harness.approve(await harness.actionCard("calendar_create_event"));
  const recovery = await harness.waitForRunStatus(runId, "RECOVERY_REQUIRED");
  const snapshot = await harness.runSnapshot(runId);
  const recoveryProjection = requiredRow(snapshot.recovery);

  expect(recovery.actions.map((action) => action.status)).toEqual(["MISMATCH"]);
  expect(recovery.verifications.map((verification) => verification.status)).toEqual([
    "MISMATCH",
  ]);
  expect(recovery.recovery.reason).toBe("VERIFICATION_MISMATCH");
  expect(harness.writeCount(recovery) - harness.writeCount(baseline)).toBe(1);
  expect(harness.effectCount(recovery) - harness.effectCount(baseline)).toBe(1);
  expect(recoveryProjection.allowed_resolution_kinds).toEqual([
    "RECHECK",
    "ACCEPT_PARTIAL",
    "CREATE_CORRECTIVE_PLAN",
    "FAIL",
  ]);
  await expect(recoveryCard()).toContainText("VERIFICATION_MISMATCH");
  await expect(page.getByText("작업을 완료했습니다.", { exact: true })).toHaveCount(0);

  await recoveryCard().getByRole("button", { name: "현재 결과 수용" }).click();
  const completed = await harness.waitForRunStatus(runId, "COMPLETED");
  expect(completed.run.terminal_result_kind).toBe("PARTIAL");
  await expect(page.getByText("일부 작업은 완료되었고 나머지는 취소되었습니다.")).toBeVisible();
});

test("F_E2E_008_MCP_FAILURE_PASS", async () => {
  const baseline = await harness.productState("missing-run");
  const { runId } = await harness.startNewRun(
    "E2E:MCP_FAILURE MCP process 장애 태스크를 만들어줘",
  );
  await harness.waitForRunStatus(runId, "WAITING_APPROVAL");
  await harness.approve(await harness.actionCard("tasks_create_task"));
  const failed = await harness.waitForActionStatus(runId, "FAILED");

  expect(failed.run.status).toBe("WAITING_APPROVAL");
  expect(failed.actions.map((action) => action.status)).toEqual(["FAILED"]);
  expect(failed.execution_attempts.map((attempt) => attempt.status)).toEqual(["FAILED"]);
  expect(failed.recovery).toEqual({});
  expect(harness.writeCount(failed) - harness.writeCount(baseline)).toBe(1);
  expect(harness.effectCount(failed) - harness.effectCount(baseline)).toBe(0);
  expect(
    harness.toolCount(failed, "search_by_recovery_fingerprint")
      - harness.toolCount(baseline, "search_by_recovery_fingerprint"),
  ).toBe(1);
  expect(
    harness.mcpProcessStartCount(failed) - harness.mcpProcessStartCount(baseline),
  ).toBe(1);
  expect(uniqueValues(failed.workflow_handoffs, "handoff_id")).toHaveLength(
    failed.workflow_handoffs.length,
  );
  expect(harness.auditTypes(failed)).toEqual(
    expect.arrayContaining(["WRITE_UNKNOWN_RESULT", "WRITE_RECOVERY_RESOLVED_FAILED"]),
  );
  await expect(page.getByText("FAILED", { exact: true })).toBeVisible();
  await expect(page.getByText("작업을 완료했습니다.", { exact: true })).toHaveCount(0);
});

function recoveryCard() {
  return page.getByRole("article").filter({ hasText: "Recovery" });
}

function confirmationCard() {
  return page.getByRole("article").filter({ hasText: "추가 확인" });
}

function requiredRow(value: ProductRow | null | undefined): ProductRow {
  expect(value).toBeTruthy();
  return value as ProductRow;
}

function uniqueValues(rows: ProductRow[], key: string): unknown[] {
  return [...new Set(rows.map((row) => row[key]))];
}
