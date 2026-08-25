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
      method: "GET" | "POST" | "PATCH" | "DELETE";
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
      { call: () => api.getSettings(), path: "/api/v1/settings", method: "GET" },
      { call: () => api.getLLMConnection(), path: "/api/v1/llm/connection", method: "GET" },
      {
        call: () =>
          api.patchSettings({
            command_id: "settings-1",
            requested_runtime_mode: "AUTO",
            external_llm_consent: true,
          }),
        path: "/api/v1/settings",
        method: "PATCH",
        bodyIncludes: { command_id: "settings-1", requested_runtime_mode: "AUTO" },
      },
      {
        call: () =>
          api.storeLLMApiKey({
            api_key: "sk-test",
            storage_mode: "KEYRING",
          }),
        path: "/api/v1/llm/api-key",
        method: "POST",
        bodyIncludes: { api_key: "sk-test", storage_mode: "KEYRING" },
      },
      { call: () => api.deleteLLMApiKey(), path: "/api/v1/llm/api-key", method: "DELETE" },
      { call: () => api.testLLMConnection(), path: "/api/v1/llm/test", method: "POST" },
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
            conversation_id: "conversation-1",
            request_text: "Summarize",
            entry_mode: "AGENT_SEARCH",
            selected_resource_ids: [],
            requested_mode: "AUTO",
          }),
        path: "/api/v1/runs",
        method: "POST",
        bodyIncludes: { conversation_id: "conversation-1", request_text: "Summarize" },
      },
      {
        call: () =>
          api.cancelRun({
            run_id: "run-1",
            command_id: "command-3",
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
            expected_version: 4,
            resume_kind: "RECOVERY_RECHECK",
          }),
        path: "/api/v1/runs/run-1/resume",
        method: "POST",
        bodyIncludes: { expected_version: 4, resume_kind: "RECOVERY_RECHECK" },
      },
      {
        call: () =>
          api.confirmRun({
            run_id: "run-1",
            command_id: "command-confirm",
            expected_version: 4,
            interrupt_id: "interrupt-1",
            response_kind: "OPTION_SELECTION",
            selected_option_ids: ["option-1"],
          }),
        path: "/api/v1/runs/run-1/confirm",
        method: "POST",
        bodyIncludes: { interrupt_id: "interrupt-1", selected_option_ids: ["option-1"] },
      },
      {
        call: () =>
          api.resolveRecovery({
            run_id: "run-1",
            command_id: "command-recovery",
            expected_version: 4,
            action_id: "action-1",
            resolution_kind: "ACCEPT_PARTIAL",
          }),
        path: "/api/v1/runs/run-1/resolve-recovery",
        method: "POST",
        bodyIncludes: { action_id: "action-1", resolution_kind: "ACCEPT_PARTIAL" },
      },
      {
        call: () =>
          api.approveAction({
            action_id: "action-1",
            command_id: "command-5",
            expected_version: 2,
          }),
        path: "/api/v1/actions/action-1/approve",
        method: "POST",
        bodyIncludes: { expected_version: 2, ttl_ms: 30000 },
      },
      {
        call: () =>
          api.rejectAction({
            action_id: "action-1",
            command_id: "command-6",
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
            expected_version: 2,
            arguments_patch: { subject: "Updated" },
          }),
        path: "/api/v1/actions/action-1/modify",
        method: "POST",
        bodyIncludes: { expected_version: 2, arguments_patch: { subject: "Updated" } },
      },
      {
        call: () =>
          api.prepareRetry({
            action_id: "action-1",
            command_id: "command-8",
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
        call: () => api.listGmailResources("follow up", "page-1", 20, false),
        path: "/api/v1/resources/gmail?query=follow+up&page_size=20&page_token=page-1&include_thread_metadata=false",
        method: "GET",
      },
      {
        call: () => api.getGmailResourceDetail("thread/1"),
        path: "/api/v1/resources/gmail/thread%2F1",
        method: "GET",
      },
      {
        call: () => api.downloadGmailAttachment("message/1", "attachment/1"),
        path: "/api/v1/gmail/messages/message%2F1/attachments/attachment%2F1",
        method: "GET",
      },
      {
        call: () => api.stageAttachment(new File(["abc"], "a.txt", { type: "text/plain" })),
        path: "/api/v1/attachments/stage",
        method: "POST",
        bodyIncludes: { filename: "a.txt", mime_type: "text/plain", data_base64: "YWJj" },
      },
      {
        call: () => api.listTaskResources("list-1", "page-2"),
        path: "/api/v1/resources/tasks?page_size=100&task_list_id=list-1&page_token=page-2",
        method: "GET",
      },
      {
        call: () => api.listCalendarResources(
          "calendar-1",
          "page-3",
          100,
          "2026-08-10T00:00:00Z",
          "2026-11-08T00:00:00Z",
        ),
        path: "/api/v1/resources/calendar?page_size=100&calendar_id=calendar-1&page_token=page-3&time_min=2026-08-10T00%3A00%3A00Z&time_max=2026-11-08T00%3A00%3A00Z",
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
