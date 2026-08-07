import { describe, expect, test, vi } from "vitest";
import * as api from "./index";

describe("api index wrappers", () => {
  test("calls same-origin endpoints with the expected methods", async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    ) as typeof fetch;

    const cases: Array<{
      call: () => Promise<unknown>;
      path: string;
      method: "GET" | "POST";
      bodyIncludes?: Record<string, unknown>;
    }> = [
      { call: () => api.getLive(), path: "/health/live", method: "GET" },
      { call: () => api.getReady(), path: "/health/ready", method: "GET" },
      {
        call: () =>
          api.bootstrapSession({
            bootstrap_secret: "secret-1",
            service_instance_id: "svc-1",
          }),
        path: "/api/v1/session/bootstrap",
        method: "POST",
        bodyIncludes: { bootstrap_secret: "secret-1", service_instance_id: "svc-1" },
      },
      { call: () => api.getRuntime(), path: "/api/v1/runtime", method: "GET" },
      { call: () => api.getGoogleConnection(), path: "/api/v1/google/connection", method: "GET" },
      { call: () => api.startGoogleOAuth(), path: "/api/v1/google/oauth/start", method: "POST" },
      { call: () => api.disconnectGoogle(), path: "/api/v1/google/disconnect", method: "POST" },
      {
        call: () => api.getCurrentAccount(),
        path: "/api/v1/identity/google-account",
        method: "GET",
      },
      {
        call: () => api.listConversations("account-1", "cursor-1"),
        path: "/api/v1/conversations?account_id=account-1&cursor=cursor-1",
        method: "GET",
      },
      {
        call: () =>
          api.createConversation({
            command_id: "command-1",
            request_hash: "hash-1",
            conversation_id: "conversation-1",
            account_id: "account-1",
            title: "Inbox triage",
          }),
        path: "/api/v1/conversations",
        method: "POST",
        bodyIncludes: { conversation_id: "conversation-1", account_id: "account-1" },
      },
      {
        call: () => api.getLatestConversationRun("conversation-1"),
        path: "/api/v1/conversations/conversation-1/latest-run",
        method: "GET",
      },
      { call: () => api.getRunSnapshot("run-1"), path: "/api/v1/runs/run-1", method: "GET" },
      {
        call: () => api.getRunContext("run-1"),
        path: "/api/v1/runs/run-1/context",
        method: "GET",
      },
      {
        call: () =>
          api.startRun({
            command_id: "command-2",
            request_hash: "hash-2",
            conversation_id: "conversation-1",
            user_message_id: "message-1",
            run_id: "run-1",
            workflow_key: "workflow-1",
            request_text: "Summarize",
            entry_mode: "AGENT_SEARCH",
            selected_resource_ids: [],
            requested_mode: "AUTO",
          }),
        path: "/api/v1/runs",
        method: "POST",
        bodyIncludes: { run_id: "run-1", request_text: "Summarize" },
      },
      {
        call: () =>
          api.cancelRun({
            run_id: "run-1",
            command_id: "command-3",
            request_hash: "hash-3",
            expected_run_version: 4,
          }),
        path: "/api/v1/runs/run-1/cancel",
        method: "POST",
        bodyIncludes: { expected_run_version: 4 },
      },
      {
        call: () =>
          api.resumeRun({
            run_id: "run-1",
            command_id: "command-4",
            request_hash: "hash-4",
            resume_kind: "manual",
            resume_payload: {},
          }),
        path: "/api/v1/runs/run-1/resume",
        method: "POST",
        bodyIncludes: { resume_kind: "manual" },
      },
      {
        call: () =>
          api.approveAction({
            action_id: "action-1",
            command_id: "command-5",
            request_hash: "hash-5",
            expected_version: 2,
            approved_by_account_id: "account-1",
            approved_by_display: "User",
            source_snapshot: { action_id: "action-1" },
            approval_id: "approval-1",
            idempotency_key: "idempotency-1",
          }),
        path: "/api/v1/actions/action-1/approve",
        method: "POST",
        bodyIncludes: { expected_version: 2, approved_by_account_id: "account-1" },
      },
      {
        call: () =>
          api.rejectAction({
            action_id: "action-1",
            command_id: "command-6",
            request_hash: "hash-6",
            expected_version: 2,
          }),
        path: "/api/v1/actions/action-1/reject",
        method: "POST",
        bodyIncludes: { expected_version: 2 },
      },
      {
        call: () =>
          api.modifyAction({
            action_id: "action-1",
            command_id: "command-7",
            request_hash: "hash-7",
            expected_version: 2,
          }),
        path: "/api/v1/actions/action-1/modify",
        method: "POST",
        bodyIncludes: { expected_version: 2 },
      },
      {
        call: () =>
          api.prepareRetry({
            action_id: "action-1",
            command_id: "command-8",
            request_hash: "hash-8",
            expected_action_version: 3,
          }),
        path: "/api/v1/actions/action-1/prepare-retry",
        method: "POST",
        bodyIncludes: { expected_action_version: 3 },
      },
      {
        call: () => api.listGmailResources("follow up", "page-1"),
        path: "/api/v1/resources/gmail?query=follow+up&page_size=20&page_token=page-1",
        method: "GET",
      },
      {
        call: () => api.listTaskResources("list-1", "page-2"),
        path: "/api/v1/resources/tasks?page_size=20&task_list_id=list-1&page_token=page-2",
        method: "GET",
      },
      {
        call: () => api.listCalendarResources("calendar-1", "page-3"),
        path: "/api/v1/resources/calendar?page_size=20&calendar_id=calendar-1&page_token=page-3",
        method: "GET",
      },
    ];

    for (const testCase of cases) {
      await testCase.call();
      const [path, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls.at(-1) as [
        string,
        RequestInit,
      ];
      expect(path).toBe(testCase.path);
      expect(init.method).toBe(testCase.method);
      if (testCase.bodyIncludes) {
        expect(JSON.parse(String(init.body))).toEqual(expect.objectContaining(testCase.bodyIncludes));
      }
    }
  });
});
