import { render, screen, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { App } from "./App";

type MockResponse = {
  status?: number;
  json?: unknown;
  headers?: Record<string, string>;
};

type SnapshotShape = {
  run_id: string;
  conversation_id: string;
  status: string;
  version: number;
  entry_mode: string;
  requested_mode: string;
  actual_runtime: string;
  started_at_ms: number;
  finished_at_ms: number | null;
  active_plan: {
    plan_id: string;
    revision_no: number;
    status: string;
    summary_text: string;
    created_at_ms: number;
  };
  actions: Array<{
    action_id: string;
    tool_name: string;
    status: string;
    version: number;
    effect_type: string;
    approval_required: boolean;
    verification_policy: string;
    risk?: Record<string, unknown>;
    next_allowed_commands: string[];
  }>;
  approvals: Array<{
    approval_id: string;
    action_id: string;
    status: string;
    approved_at_ms: number;
    expires_at_ms: number;
  }>;
  execution_status: { action_count: number; terminal_action_count: number };
  verification_summary: { verified_count: number; mismatch_count: number };
  recovery_summary: { unknown_result_action_count: number };
  result_kind?: string | null;
  next_allowed_commands: string[];
  snapshot_version: number;
};

class FakeEventSource {
  static instances: FakeEventSource[] = [];

  url: string;
  withCredentials: boolean;
  listeners = new Map<string, Array<(event: MessageEvent<string>) => void>>();

  constructor(url: string, init?: EventSourceInit) {
    this.url = url;
    this.withCredentials = Boolean(init?.withCredentials);
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    const current = this.listeners.get(type) ?? [];
    current.push(listener);
    this.listeners.set(type, current);
  }

  close(): void {
    return;
  }

  emit(type: string, payload: Record<string, unknown>, eventId = `${type}-1`): void {
    const event = { data: JSON.stringify(payload), lastEventId: eventId } as MessageEvent<string>;
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }
}

const originalFetch = globalThis.fetch;

beforeEach(() => {
  localStorage.clear();
  FakeEventSource.instances = [];
  Object.defineProperty(window, "EventSource", { value: FakeEventSource, configurable: true });
  Object.defineProperty(window, "open", { value: vi.fn(), configurable: true });
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  window.history.replaceState(null, "", "/");
});

async function selectCalendarDate(user: ReturnType<typeof userEvent.setup>, date: string, count = 1): Promise<void> {
  await user.click(await screen.findByRole("button", { name: `${date} 일정 ${count}개` }));
}

test("captures the bootstrap fragment before asynchronous startup checks", async () => {
  window.history.replaceState(null, "", "/#bootstrap_secret=secret-1&service_instance_id=svc-1");
  let bootstrapRequested = false;
  installFetch((path) => {
    if (path === "/health/live") {
      window.history.replaceState(null, "", "/");
      return jsonResponse({ status: "LIVE", service_instance_id: "svc-1", release_version: "test", api_contract_version: "1", occurred_at_ms: 1 });
    }
    if (path === "/health/ready") {
      return jsonResponse({ status: "READY", checks: [{ name: "sqlite", state: "READY" }], release_version: "test", api_contract_version: "1", occurred_at_ms: 2 });
    }
    if (path === "/api/v1/session/bootstrap") {
      bootstrapRequested = true;
      return jsonResponse({ session_established: true, service_instance_id: "svc-1", api_contract_version: "1" });
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary([]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  render(<App />);

  await screen.findByText(/Google/);
  expect(window.location.hash).toBe("");
  expect(bootstrapRequested).toBe(true);
  expect(document.body.textContent).not.toContain("secret-1");
});

test("keeps the fragment until one StrictMode bootstrap request succeeds", async () => {
  window.history.replaceState(null, "", "/#bootstrap_secret=secret-1&service_instance_id=svc-1");
  const paths: string[] = [];
  let bootstrapStarted = false;
  let resolveBootstrap: (response: Response) => void = () => {
    throw new Error("Bootstrap request did not start");
  };
  globalThis.fetch = vi.fn((input: string | URL) => {
    const path = String(input);
    paths.push(path);
    if (path === "/health/live") {
      return Promise.resolve(jsonFetchResponse(liveResponse()));
    }
    if (path === "/health/ready") {
      return Promise.resolve(jsonFetchResponse(readyResponse()));
    }
    if (path === "/api/v1/session/bootstrap") {
      bootstrapStarted = true;
      return new Promise<Response>((resolve) => {
        resolveBootstrap = resolve;
      });
    }
    if (path === "/api/v1/runtime") {
      return Promise.resolve(jsonFetchResponse({ summary: runtimeSummary([]), api_contract_version: "1" }));
    }
    if (path === "/api/v1/google/connection") {
      return Promise.resolve(jsonFetchResponse(googleConnection()));
    }
    if (path === "/api/v1/identity/google-account") {
      return Promise.resolve(jsonFetchResponse({ account: currentAccount(), api_contract_version: "1" }));
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return Promise.resolve(jsonFetchResponse({ items: [], next_cursor: null, api_contract_version: "1" }));
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return Promise.resolve(jsonFetchResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" }));
    }
    return Promise.reject(new Error(`Unhandled path ${path}`));
  }) as typeof fetch;

  render(
    <StrictMode>
      <App />
    </StrictMode>,
  );

  await waitFor(() => expect(bootstrapStarted).toBe(true));
  expect(paths.filter((path) => path === "/api/v1/session/bootstrap")).toHaveLength(1);
  expect(paths).not.toContain("/api/v1/runtime");
  expect(window.location.hash).toContain("bootstrap_secret");

  resolveBootstrap(jsonFetchResponse({ session_established: true, service_instance_id: "svc-1", api_contract_version: "1" }));

  await screen.findByText(/Google/);
  expect(window.location.hash).toBe("");
  expect(paths.indexOf("/api/v1/session/bootstrap")).toBeLessThan(paths.indexOf("/api/v1/runtime"));
  expect(paths.indexOf("/api/v1/session/bootstrap")).toBeLessThan(paths.indexOf("/api/v1/google/connection"));
  expect(paths.indexOf("/api/v1/session/bootstrap")).toBeLessThan(paths.indexOf("/api/v1/identity/google-account"));
});

test("starts a run in RESOURCE_SELECTED mode", async () => {
  let conversationCreated = false;
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse({ status: "LIVE", service_instance_id: "svc-1", release_version: "test", api_contract_version: "1", occurred_at_ms: 1 });
    }
    if (path === "/health/ready") {
      return jsonResponse({ status: "READY", checks: [{ name: "sqlite", state: "READY" }], release_version: "test", api_contract_version: "1", occurred_at_ms: 2 });
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary([]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({
        items: conversationCreated
          ? [{ id: "conversation-1", account_id: "account-1", title: "Project sync", created_at_ms: 1, updated_at_ms: 2 }]
          : [],
        next_cursor: null,
        api_contract_version: "1",
      });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({
        source: "gmail",
        items: [
          {
            source: "gmail",
            resource_type: "gmail_thread",
            resource_id: "thread-project",
            parent_id: null,
            title: "Project sync follow-up",
            subtitle: "Need a draft for the Thursday recap.",
            link_url: "https://mail.google.com/mail/u/0/#inbox/thread-project",
            version: "3",
            related_resource_ids: [],
            metadata: {},
          },
        ],
        next_page_token: null,
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/conversations" && init?.method === "POST") {
      conversationCreated = true;
      return jsonResponse({ conversation_id: "conversation-1" });
    }
    if (path === "/api/v1/runs" && init?.method === "POST") {
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        run_id: "run-1",
        conversation_id: "conversation-1",
        run_status: "CREATED",
        run_version: 0,
        user_message_id: "message-1",
        workflow_key: "workflow-run-1",
        enqueued: true,
        request_replayed: false,
      });
    }
    if (path === "/api/v1/runs/run-1") {
      return jsonResponse(snapshotPayload({ status: "CREATED", entry_mode: "RESOURCE_SELECTED" }));
    }
    if (path === "/api/v1/runs/run-1/context") {
      return jsonResponse({
        context: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          workflow_key: "workflow-run-1",
          entry_mode: "RESOURCE_SELECTED",
          requested_mode: "AUTO",
          status: "CREATED",
          version: 0,
          request_text: "Summarize the selected thread",
          selected_resource_ids: ["thread-project"],
        },
        api_contract_version: "1",
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  const selectControl = await screen.findByRole("checkbox", { name: /선택/ });
  await user.click(selectControl);
  await user.type(screen.getByRole("textbox", { name: "선택한 메일에 대해 질문하거나 업무를 요청하세요..." }), "선택 자료를 정리해 줘");
  await user.click(screen.getByRole("button", { name: "보내기" }));

  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/runs",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const startRunCall = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
    ([path, init]) => path === "/api/v1/runs" && init?.method === "POST",
  );
  const body = JSON.parse(String(startRunCall?.[1].body)) as {
    entry_mode: string;
    selected_resource_ids: string[];
  };
  expect(body.entry_mode).toBe("RESOURCE_SELECTED");
  expect(body.selected_resource_ids).toEqual(["thread-project"]);
});

test("shows approve button for write actions and posts approve command", async () => {
  let approved = false;
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse({ status: "LIVE", service_instance_id: "svc-1", release_version: "test", api_contract_version: "1", occurred_at_ms: 1 });
    }
    if (path === "/health/ready") {
      return jsonResponse({ status: "READY", checks: [{ name: "sqlite", state: "READY" }], release_version: "test", api_contract_version: "1", occurred_at_ms: 2 });
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary(["run-1"]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({
        items: [{ id: "conversation-1", account_id: "account-1", title: "Inbox", created_at_ms: 1, updated_at_ms: 2 }],
        next_cursor: null,
        api_contract_version: "1",
      });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/runs/run-1") {
      return jsonResponse(
        snapshotPayload({
          status: approved ? "EXECUTING" : "WAITING_APPROVAL",
          actions: [
            {
              action_id: "action-1",
              tool_name: "tasks_create_task",
              status: approved ? "APPROVED" : "PROPOSED",
              version: approved ? 3 : 2,
              effect_type: "CREATE",
              approval_required: true,
              verification_policy: "GET_COMPARE",
              next_allowed_commands: approved ? [] : ["APPROVE", "MODIFY", "REJECT"],
            },
          ],
        }),
      );
    }
    if (path === "/api/v1/runs/run-1/context") {
      return jsonResponse({
        context: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          workflow_key: "workflow-run-1",
          entry_mode: "AGENT_SEARCH",
          requested_mode: "AUTO",
          status: approved ? "EXECUTING" : "WAITING_APPROVAL",
          version: approved ? 2 : 1,
          request_text: "Prepare the weekly follow-up",
          selected_resource_ids: [],
        },
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/actions/action-1/approve" && init?.method === "POST") {
      approved = true;
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        action_id: "action-1",
        action_status: "APPROVED",
        action_version: 3,
        next_allowed_commands: [],
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  const approveButton = await screen.findByRole("button", { name: "승인" });
  await user.click(approveButton);

  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/actions/action-1/approve",
      expect.objectContaining({ method: "POST" }),
    ),
  );
});

test("TST-UI-212 reloads a snapshot after SSE recovery without replaying a write", async () => {
  installFetch((path) => {
    if (path === "/health/live") {
      return jsonResponse({ status: "LIVE", service_instance_id: "svc-1", release_version: "test", api_contract_version: "1", occurred_at_ms: 1 });
    }
    if (path === "/health/ready") {
      return jsonResponse({ status: "READY", checks: [{ name: "sqlite", state: "READY" }], release_version: "test", api_contract_version: "1", occurred_at_ms: 2 });
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary(["run-1"]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({
        items: [{ id: "conversation-1", account_id: "account-1", title: "Inbox", created_at_ms: 1, updated_at_ms: 2 }],
        next_cursor: null,
        api_contract_version: "1",
      });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/runs/run-1") {
      return jsonResponse(snapshotPayload({}));
    }
    if (path === "/api/v1/runs/run-1/context") {
      return jsonResponse({
        context: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          workflow_key: "workflow-run-1",
          entry_mode: "AGENT_SEARCH",
          requested_mode: "AUTO",
          status: "WAITING_APPROVAL",
          version: 1,
          request_text: "Prepare the weekly follow-up",
          selected_resource_ids: [],
        },
        api_contract_version: "1",
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  render(<App />);

  await screen.findByText("사용자 요청");
  const instance = FakeEventSource.instances[0];
  instance.emit("snapshot_required", { reason: "cursor expired" }, "evt-1");

  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith("/api/v1/runs/run-1", expect.any(Object)),
  );
  expect(globalThis.fetch).not.toHaveBeenCalledWith("/api/v1/runs", expect.any(Object));
  expect(FakeEventSource.instances).toHaveLength(1);
});

test("confirms an interrupt and explicitly resolves a mismatch", async () => {
  let stage: "confirmation" | "mismatch" | "completed" = "confirmation";
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary(["run-1"]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({
        items: [{ id: "conversation-1", account_id: "account-1", title: "Inbox", created_at_ms: 1, updated_at_ms: 2 }],
        next_cursor: null,
        api_contract_version: "1",
      });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/runs/run-1") {
      const mismatch = stage === "mismatch";
      return jsonResponse(
        snapshotPayload({
          status: stage === "confirmation" ? "WAITING_CONFIRMATION" : mismatch ? "RECOVERY_REQUIRED" : "COMPLETED",
          version: stage === "confirmation" ? 1 : 2,
          actions: mismatch
            ? [{
                action_id: "action-1",
                tool_name: "tasks_update_task",
                status: "MISMATCH",
                version: 4,
                effect_type: "UPDATE",
                approval_required: false,
                verification_policy: "GET_COMPARE",
                next_allowed_commands: [],
              }]
            : [],
          verification_summary: { verified_count: 0, mismatch_count: mismatch ? 1 : 0 },
        }),
      );
    }
    if (path === "/api/v1/runs/run-1/context") {
      return jsonResponse({
        context: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          workflow_key: "workflow-run-1",
          entry_mode: "AGENT_SEARCH",
          requested_mode: "AUTO",
          status: stage === "confirmation" ? "WAITING_CONFIRMATION" : stage === "mismatch" ? "RECOVERY_REQUIRED" : "COMPLETED",
          version: stage === "confirmation" ? 1 : 2,
          request_text: "Update the task after confirmation",
          selected_resource_ids: [],
        },
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/runs/run-1/confirm" && init?.method === "POST") {
      stage = "mismatch";
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        run_id: "run-1",
        run_status: "EXECUTING",
        run_version: 2,
      });
    }
    if (path === "/api/v1/runs/run-1/resolve-recovery" && init?.method === "POST") {
      stage = "completed";
      return jsonResponse({
        applied: true,
        result_code: "TRANSITION_APPLIED",
        run_id: "run-1",
        run_status: "COMPLETED",
        run_version: 3,
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await screen.findByText("확인 요청 정보를 동기화하고 있습니다.");
  expect(screen.getByLabelText("확인 응답")).toBeDisabled();
  FakeEventSource.instances[0].emit("confirmation_required", {
    user_interrupt: { interrupt_id: "interrupt-1", question: "Which task should be updated?" },
  });
  await screen.findByText("Which task should be updated?");
  expect(screen.getByLabelText("확인 응답")).toBeEnabled();
  await user.type(screen.getByLabelText("확인 응답"), "Use the follow-up task");
  await user.click(screen.getByRole("button", { name: "응답 보내기" }));
  await user.click(await screen.findByRole("button", { name: "현재 결과 수용" }));

  expect(globalThis.fetch).toHaveBeenCalledWith(
    "/api/v1/runs/run-1/confirm",
    expect.objectContaining({ method: "POST", body: expect.stringContaining('"interrupt_id":"interrupt-1"') }),
  );
  expect(globalThis.fetch).toHaveBeenCalledWith(
    "/api/v1/runs/run-1/resolve-recovery",
    expect.objectContaining({ method: "POST", body: expect.stringContaining('"resolution_kind":"ACCEPT_PARTIAL"') }),
  );
});

test("starts Google OAuth from the disconnected status action", async () => {
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary([]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse({
        ...googleConnection(),
        connected: false,
        credential_state: "DISCONNECTED",
        account_email: null,
        safe_error_code: "TOKEN_EXCHANGE_INVALID_REQUEST",
        safe_error_description: "Google rejected a required token request field.",
      });
    }
    if (path === "/api/v1/settings") {
      return jsonResponse({ settings: settingsPayload(), api_contract_version: "1" });
    }
    if (path === "/api/v1/llm/connection") {
      return jsonResponse({ llm: llmConnectionPayload(), api_contract_version: "1" });
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/google/oauth/start" && init?.method === "POST") {
      return jsonResponse({
        flow_id: "flow-1",
        authorization_url: "http://127.0.0.1:43123/oauth/authorize?state=flow-1",
        callback_url: "http://localhost/callback",
        expires_at_ms: 1000,
        oauth_environment: "DEVELOPMENT",
        scopes: ["gmail.readonly"],
        api_contract_version: "1",
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await screen.findByText(/Google/);
  await user.click(screen.getByRole("button", { name: "설정" }));
  expect(await screen.findByText("TOKEN_EXCHANGE_INVALID_REQUEST")).toBeInTheDocument();
  expect(
    screen.getByText("Google rejected a required token request field."),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Google 연결" }));

  expect(window.open).toHaveBeenCalledWith(
    "http://127.0.0.1:43123/oauth/authorize?state=flow-1",
    "_blank",
    "noopener,noreferrer",
  );
  expect(await screen.findByText("Google 연결 완료를 기다리고 있습니다.")).toBeInTheDocument();
});

test("does not open an unexpected authorization URL returned by the API", async () => {
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary([]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse({ ...googleConnection(), connected: false, credential_state: "DISCONNECTED", account_email: null });
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/google/oauth/start" && init?.method === "POST") {
      return jsonResponse({
        flow_id: "flow-1",
        authorization_url: "https://invalid.example/authorization",
        callback_url: "http://127.0.0.1/callback",
        expires_at_ms: 1000,
        oauth_environment: "DEVELOPMENT",
        scopes: ["gmail.readonly"],
        api_contract_version: "1",
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await user.click(await screen.findByRole("button", { name: "Google 연결" }));
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/google/oauth/start",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(window.open).not.toHaveBeenCalled();
  expect(screen.getByText("Google 연결을 시작하지 못했습니다.")).toBeInTheDocument();
});

test("disconnects Google and refreshes the runtime summary", async () => {
  let disconnected = false;
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({
        summary: {
          ...runtimeSummary([]),
          google: disconnected ? "DISCONNECTED" : "CONNECTED",
        },
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(
        disconnected
          ? {
              ...googleConnection(),
              connected: false,
              credential_state: "DISCONNECTED",
              account_email: null,
            }
          : googleConnection(),
      );
    }
    if (path === "/api/v1/settings") {
      return jsonResponse({ settings: settingsPayload(), api_contract_version: "1" });
    }
    if (path === "/api/v1/llm/connection") {
      return jsonResponse({ llm: llmConnectionPayload(), api_contract_version: "1" });
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({
        source: "gmail",
        items: [gmailThread()],
        next_page_token: null,
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/google/disconnect" && init?.method === "POST") {
      disconnected = true;
      return jsonResponse({
        ...googleConnection(),
        connected: false,
        credential_state: "DISCONNECTED",
        account_email: null,
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await screen.findByRole("checkbox", { name: /선택/ });
  await user.click(screen.getByRole("button", { name: "설정" }));
  await user.click(screen.getByRole("button", { name: "연결 해제" }));

  await screen.findByText("Google 미연결");
  expect(screen.queryByRole("checkbox", { name: /선택/ })).not.toBeInTheDocument();
});

test("submits cancel, resume, and retry actions while showing unknown-result recovery", async () => {
  let cancelled = false;
  let resumed = false;
  let retried = false;
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary(["run-1"]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({
        items: [{ id: "conversation-1", account_id: "account-1", title: "Inbox", created_at_ms: 1, updated_at_ms: 2 }],
        next_cursor: null,
        api_contract_version: "1",
      });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [gmailThread()], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/runs/run-1") {
      return jsonResponse(
        snapshotPayload({
          status: resumed ? "EXECUTING" : cancelled ? "CANCEL_REQUESTED" : "RECOVERY_REQUIRED",
          actions: [
            {
              action_id: "action-failed",
              tool_name: "tasks_create_task",
              status: retried ? "PENDING" : "FAILED",
              version: retried ? 3 : 2,
              effect_type: "CREATE",
              approval_required: false,
              verification_policy: "GET_COMPARE",
              next_allowed_commands: retried ? [] : ["PREPARE_RETRY"],
            },
            {
              action_id: "action-unknown",
              tool_name: "calendar_update_event",
              status: "UNKNOWN_RESULT",
              version: 4,
              effect_type: "UPDATE",
              approval_required: false,
              verification_policy: "GET_COMPARE",
              next_allowed_commands: [],
            },
          ],
          recovery_summary: { unknown_result_action_count: 1 },
        }),
      );
    }
    if (path === "/api/v1/runs/run-1/context") {
      return jsonResponse({
        context: {
          run_id: "run-1",
          conversation_id: "conversation-1",
          workflow_key: "workflow-run-1",
          entry_mode: "AGENT_SEARCH",
          requested_mode: "AUTO",
          status: resumed ? "EXECUTING" : cancelled ? "CANCEL_REQUESTED" : "RECOVERY_REQUIRED",
          version: 1,
          request_text: "Recover the failed write",
          selected_resource_ids: [],
        },
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/runs/run-1/cancel" && init?.method === "POST") {
      cancelled = true;
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        run_id: "run-1",
        run_status: "CANCEL_REQUESTED",
        run_version: 2,
      });
    }
    if (path === "/api/v1/runs/run-1/resume" && init?.method === "POST") {
      resumed = true;
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        run_id: "run-1",
        run_status: "EXECUTING",
        run_version: 3,
      });
    }
    if (path === "/api/v1/actions/action-failed/prepare-retry" && init?.method === "POST") {
      retried = true;
      return jsonResponse({
        applied: true,
        result_code: "ACCEPTED",
        action_id: "action-failed",
        action_status: "PENDING",
        action_version: 3,
        next_allowed_commands: [],
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await screen.findByText("결과 불명 작업 1건을 확인하고 있습니다.");
  await user.click(screen.getByRole("button", { name: "취소" }));
  await user.click(screen.getByRole("button", { name: "재개" }));
  await user.click(screen.getByRole("button", { name: "다시 준비" }));

  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/actions/action-failed/prepare-retry",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  expect(screen.getByText("실제 결과를 확인하는 중입니다. 새 쓰기 실행은 잠시 막혀 있습니다.")).toBeInTheDocument();
});

test("opens only safe Google links from resource items", async () => {
  installFetch((path) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({ summary: runtimeSummary([]), api_contract_version: "1" });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/resources/gmail/thread-project") {
      return jsonResponse(gmailDetail("thread-project", { canonical_url: "javascript:alert('xss')" }));
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({
        source: "gmail",
        items: [{ ...gmailThread(), link_url: "javascript:alert('xss')" }],
        next_page_token: null,
        api_contract_version: "1",
      });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await user.click(await screen.findByRole("button", { name: /Project sync follow-up/ }));
  expect(screen.queryByRole("button", { name: "원본 열기" })).not.toBeInTheDocument();
});

test("saves llm settings and stores, tests, then deletes the api key", async () => {
  let requestedRuntimeMode = "API_LLM";
  let externalLLMConsent = false;
  let credentialState = "MISSING";
  installFetch((path, init) => {
    if (path === "/health/live") {
      return jsonResponse(liveResponse());
    }
    if (path === "/health/ready") {
      return jsonResponse(readyResponse());
    }
    if (path === "/api/v1/runtime") {
      return jsonResponse({
        summary: runtimeSummary([], {
          llm: llmConnectionPayload({
            requested_mode: requestedRuntimeMode,
            external_llm_consent: externalLLMConsent,
            api_provider: {
              credential_state: credentialState,
              availability: credentialState === "MISSING" ? "NOT_CONFIGURED" : "AVAILABLE",
              last_probe: 1,
              safe_error_code: null,
            },
          }),
        }),
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/google/connection") {
      return jsonResponse(googleConnection());
    }
    if (path === "/api/v1/settings" && (!init || init.method === "GET")) {
      return jsonResponse({
        settings: settingsPayload({
          requested_runtime_mode: requestedRuntimeMode,
          external_llm_consent: externalLLMConsent,
        }),
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/llm/connection" && (!init || init.method === "GET")) {
      return jsonResponse({
        llm: llmConnectionPayload({
          requested_mode: requestedRuntimeMode,
          external_llm_consent: externalLLMConsent,
          api_provider: {
            credential_state: credentialState,
            availability: credentialState === "MISSING" ? "NOT_CONFIGURED" : "AVAILABLE",
            last_probe: 1,
            safe_error_code: null,
          },
        }),
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/identity/google-account") {
      return jsonResponse({ account: currentAccount(), api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonResponse({ items: [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      return jsonResponse({ source: "gmail", items: [], next_page_token: null, api_contract_version: "1" });
    }
    if (path === "/api/v1/settings" && init?.method === "PATCH") {
      const body = JSON.parse(String(init.body)) as {
        requested_runtime_mode: string;
        external_llm_consent: boolean;
      };
      requestedRuntimeMode = body.requested_runtime_mode;
      externalLLMConsent = body.external_llm_consent;
      return jsonResponse({
        settings: settingsPayload({
          requested_runtime_mode: requestedRuntimeMode,
          external_llm_consent: externalLLMConsent,
        }),
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/llm/api-key" && init?.method === "POST") {
      credentialState = "AVAILABLE";
      return jsonResponse({ credential_state: credentialState, api_contract_version: "1" });
    }
    if (path === "/api/v1/llm/test" && init?.method === "POST") {
      return jsonResponse({
        llm: llmConnectionPayload({
          requested_mode: requestedRuntimeMode,
          external_llm_consent: externalLLMConsent,
          api_provider: {
            credential_state: credentialState,
            availability: "AVAILABLE",
            last_probe: 2,
            safe_error_code: null,
          },
        }),
        api_contract_version: "1",
      });
    }
    if (path === "/api/v1/llm/api-key" && init?.method === "DELETE") {
      credentialState = "MISSING";
      return jsonResponse({ credential_state: credentialState, api_contract_version: "1" });
    }
    throw new Error(`Unhandled path ${path}`);
  });

  const user = userEvent.setup();
  render(<App />);

  await screen.findByText(/Google/);
  await user.click(screen.getByRole("button", { name: "설정" }));
  await screen.findByText("Requested mode");
  await user.selectOptions(screen.getByDisplayValue("API_LLM"), "AUTO");
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "LLM 설정 저장" }));
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/settings",
      expect.objectContaining({ method: "PATCH" }),
    ),
  );

  await user.selectOptions(screen.getByDisplayValue("KEYRING"), "SESSION_MEMORY");
  await user.type(screen.getByPlaceholderText("sk-..."), "sk-phase-m");
  await user.click(screen.getByRole("button", { name: "API 키 저장" }));
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/llm/api-key",
      expect.objectContaining({ method: "POST" }),
    ),
  );

  await user.click(screen.getByRole("button", { name: "연결 테스트" }));
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/llm/test",
      expect.objectContaining({ method: "POST" }),
    ),
  );

  await user.click(screen.getByRole("button", { name: "API 키 삭제" }));
  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/llm/api-key",
      expect.objectContaining({ method: "DELETE" }),
    ),
  );
});

test("TST-UI-201 header shows product, connection, account, help, settings, and safe status", async () => {
  installUiContractFetch();
  render(<App />);

  await screen.findByText("승인이 필요합니다.");
  expect(screen.getByText("user@example.com")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "도움말" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "설정" })).toBeInTheDocument();
  expect(screen.getByText("승인이 필요합니다.")).toBeInTheDocument();
  expect(screen.queryByText("WAITING_APPROVAL")).not.toBeInTheDocument();
});

test("TST-UI-202 renders the left, center, and right workspace panels", async () => {
  installUiContractFetch();
  render(<App />);

  await screen.findByRole("list", { name: "Google 업무 자료" });
  expect(screen.getByRole("region", { name: "선택 자료 상세" })).toBeInTheDocument();
  expect(screen.getByText("대화")).toBeInTheDocument();
  expect(screen.getByText("최근 실행")).toBeInTheDocument();
});

test("TST-UI-203 resource row supports focus, selection, and keyboard-accessible controls", async () => {
  const user = userEvent.setup();
  installUiContractFetch();
  render(<App />);

  const row = await screen.findByRole("button", { name: /첫 번째 자료/ });
  await user.click(row);
  expect(row).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("checkbox", { name: "첫 번째 자료 선택" })).not.toBeChecked();
  expect(screen.getByText("GMAIL")).toBeInTheDocument();
  expect(screen.getByText("TASKS")).toBeInTheDocument();
  expect(screen.getByText("CALENDAR")).toBeInTheDocument();
});

test("TST-UI-204 requests a 100-item batch and keeps the provider token separate from UI pages", async () => {
  const requests = installUiContractFetch();
  render(<App />);

  await screen.findByText("첫 번째 자료");
  const firstPage = requests.find((request) => request.path.startsWith("/api/v1/resources/gmail?"));
  expect(firstPage?.path).toContain("page_size=20");
  expect(screen.getByRole("button", { name: "1" })).toBeInTheDocument();
});

test("shows the Gmail exact count in the active tab instead of below the search field", async () => {
  installUiContractFetch({ gmailCount: 189 });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  expect(await screen.findByRole("tab", { name: /메일.*189/ })).toBeInTheDocument();
  expect(screen.getByText("189")).toHaveClass("resource-tab-count");
});

test("removes the loading status element after Gmail list loading completes", async () => {
  const delayedGmail = deferred<Response>();
  installUiContractFetch({ gmailListResponse: delayedGmail.promise });
  render(<App />);

  expect(await screen.findByText("자료를 불러오는 중입니다.")).toBeInTheDocument();
  delayedGmail.resolve(jsonFetchResponse({ source: "gmail", items: [gmailThread()], next_page_token: null, api_contract_version: "1" }));
  await waitFor(() => {
    expect(screen.queryByText("자료를 불러오는 중입니다.")).not.toBeInTheDocument();
  });
  expect(document.querySelector(".resource-load-status")).toBeNull();
});

test("automatically loads Tasks and Calendar when their source tabs become active", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch();
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("후속 조치")).toBeInTheDocument();
  expect(screen.getByText("8월 12일 (수)")).toBeInTheDocument();
  expect(screen.queryByText("needsAction")).not.toBeInTheDocument();
  expect(screen.queryByText("2026-08-12T09:00:00+09:00")).not.toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: /캘린더/ }));
  await screen.findByLabelText("월간 일정");
  await selectCalendarDate(user, "2026-08-10");
  expect(await screen.findByText("프로젝트 검토")).toBeInTheDocument();
  expect(screen.getByText("09:00")).toBeInTheDocument();
  expect(screen.queryByText("캘린더 목록")).not.toBeInTheDocument();

  expect(requests.some((request) => request.path.startsWith("/api/v1/resources/tasks?page_size=100"))).toBe(true);
  const calendarRequest = requests.find((request) => request.path.startsWith("/api/v1/resources/calendar?page_size=100"));
  expect(calendarRequest?.path).toContain("time_min=");
  expect(calendarRequest?.path).toContain("time_max=");
});

test("keeps Gmail and Tasks counts when the Calendar tab changes", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ gmailCount: 186, taskBatchSizes: [10] });
  render(<App />);

  await screen.findByRole("tab", { name: /메일.*186/ });
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  await screen.findByText("할 일 1");
  expect(screen.getByRole("tab", { name: /메일.*186/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /태스크.*10/ })).toBeInTheDocument();
  expect(screen.queryByText(/^태스크 10$/)).not.toBeInTheDocument();
  expect(requests.some((request) => request.path === "/api/v1/resources/tasks/count")).toBe(false);

  await user.click(screen.getByRole("tab", { name: /캘린더/ }));
  await selectCalendarDate(user, "2026-08-10");
  await screen.findByText("프로젝트 검토");
  expect(screen.getByRole("tab", { name: /캘린더/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /메일.*186/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /태스크.*10/ })).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /메일.*186/ }));
  expect(await screen.findByText("첫 번째 자료")).toBeInTheDocument();
  expect(requests.filter((request) => request.path === "/api/v1/resources/gmail/count").length).toBe(1);
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar/count")).length).toBe(0);
});

test("preloads Gmail and Tasks counts without preloading inactive source lists", async () => {
  const requests = installUiContractFetch({ gmailCount: 189, taskBatchSizes: [100, 21] });
  render(<App />);

  await screen.findByRole("tab", { name: /메일.*189/ });
  expect(await screen.findByRole("tab", { name: /태스크.*100\+/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /캘린더/ })).toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(1);
  expect(requests.some((request) => request.path === "/api/v1/resources/tasks/count")).toBe(false);
  expect(requests.some((request) => request.path.startsWith("/api/v1/resources/calendar/count"))).toBe(false);
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar?page_size=100")).length).toBe(0);
});

test("reveals initial source counts together only after every preload settles", async () => {
  const gmailCount = deferred<Response>();
  const taskBatch = deferred<Response>();
  const requests = installUiContractFetch({
    gmailCountResponse: gmailCount.promise,
    taskListResponse: taskBatch.promise,
  });
  render(<App />);

  await waitFor(() => expect(requests.filter((request) => request.path === "/api/v1/resources/gmail/count")).toHaveLength(1));
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(1);
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar/count")).length).toBe(0);

  gmailCount.resolve(jsonFetchResponse({ source: "gmail", total_count: 189, api_contract_version: "1" }));
  taskBatch.resolve(jsonFetchResponse({
    source: "tasks",
    items: [{ source: "tasks", resource_type: "task", resource_id: "task-1", parent_id: "task-list-default", title: "할 일 1", subtitle: null, link_url: null, version: "1", related_resource_ids: [], metadata: {} }],
    next_page_token: null,
    api_contract_version: "1",
  }));
  await Promise.resolve();
  expect(screen.queryByRole("tab", { name: /메일.*189/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: /태스크.*1/ })).not.toBeInTheDocument();

  expect(await screen.findByRole("tab", { name: /메일.*189/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /태스크.*1/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /캘린더/ })).toBeInTheDocument();
});

test("keeps successful initial counts when another preload request fails", async () => {
  const gmailCount = deferred<Response>();
  const requests = installUiContractFetch({
    gmailCountResponse: gmailCount.promise,
    taskBatchSizes: [10],
  });
  render(<App />);

  await waitFor(() => expect(requests.filter((request) => request.path === "/api/v1/resources/gmail/count")).toHaveLength(1));
  gmailCount.reject(new Error("count unavailable"));

  expect(await screen.findByRole("tab", { name: /태스크.*10/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /캘린더/ })).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: /메일.*\d/ })).not.toBeInTheDocument();
  expect(requests.some((request) => request.path === "/api/v1/resources/tasks/count")).toBe(false);
});

test("preloads Gmail and Tasks counts even when the initial account identity is unavailable", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ accountAbsent: true, gmailCount: 189, taskBatchSizes: [10] });
  render(<App />);

  expect(await screen.findByRole("tab", { name: /메일.*189/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /태스크.*10/ })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /캘린더/ })).toBeInTheDocument();
  expect(requests.filter((request) => request.path === "/api/v1/resources/gmail/count")).toHaveLength(1);
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(1);
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar/count")).length).toBe(0);
  expect(requests.some((request) => request.path === "/api/v1/resources/tasks/count")).toBe(false);

  await user.click(screen.getByRole("tab", { name: /태스크.*10/ }));
  expect(await screen.findByText("할 일 1")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(1);
});

test("Tasks eagerly materializes completed rows and opens the exact count from cache", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({
    taskBatchSizes: [2],
    completedTaskResponses: [
      {
        items: [
          { source: "tasks", resource_type: "task", resource_id: "done-1", parent_id: "task-list-default", title: "완료 업무", subtitle: null, link_url: "https://tasks.google.com/", version: "1", related_resource_ids: [], metadata: { task_status: "completed", completed_at: "2026-08-13T00:30:00.000Z" } },
          { source: "tasks", resource_type: "task", resource_id: "mixed-1", parent_id: "task-list-default", title: "섞인 미완료", subtitle: null, link_url: "https://tasks.google.com/", version: "1", related_resource_ids: [], metadata: { task_status: "incomplete" } },
        ],
        nextPageToken: "completed-page-2",
      },
      {
        items: [
          { source: "tasks", resource_type: "task", resource_id: "done-2", parent_id: "task-list-default", title: "완료 업무 2", subtitle: null, link_url: "https://tasks.google.com/", version: "1", related_resource_ids: [], metadata: { task_status: "completed", completed_at: "invalid" } },
          { source: "tasks", resource_type: "task", resource_id: "done-1", parent_id: "task-list-default", title: "완료 업무", subtitle: null, link_url: "https://tasks.google.com/", version: "1", related_resource_ids: [], metadata: { task_status: "completed", completed_at: "2026-08-13T00:30:00.000Z" } },
        ],
      },
    ],
  });
  render(<App />);
  await waitFor(() => expect(requests.filter((request) => request.path.includes("status_scope=completed"))).toHaveLength(2));
  await user.click(await screen.findByRole("tab", { name: /태스크/ }));
  expect(await screen.findByRole("button", { name: "완료됨(2) ▸" })).toBeInTheDocument();
  const incompleteList = screen.getByRole("list", { name: "Google 업무 자료" });
  const completedSection = screen.getByLabelText("완료됨");
  const pagination = screen.getByRole("navigation", { name: "자료 페이지" });
  expect(incompleteList.compareDocumentPosition(completedSection) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(completedSection.compareDocumentPosition(pagination) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(requests.some((request) => request.path.includes("page_token=completed-page-2"))).toBe(true);
  const completedCallsBeforeOpen = requests.filter((request) => request.path.includes("status_scope=completed")).length;
    await user.click(screen.getByRole("button", { name: "완료됨(2) ▸" }));
    expect(await screen.findByText("✓ 완료 업무")).toBeInTheDocument();
    expect(screen.getByText("완료일: 8월 13일 (목)")).toBeInTheDocument();
    expect(screen.getAllByText(/완료일:/)).toHaveLength(1);
    expect(screen.queryByText("✓ 섞인 미완료")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "완료됨(2) ▾" })).toBeInTheDocument();
  expect(requests.filter((request) => request.path.includes("status_scope=completed"))).toHaveLength(completedCallsBeforeOpen);
});

test("Tasks completed refresh replaces the terminal cache and client-side more makes no request", async () => {
  const user = userEvent.setup();
  const completed = (id: string, title = id): Record<string, unknown> => ({
    source: "tasks", resource_type: "task", resource_id: id, parent_id: "task-list-default", title,
    subtitle: null, link_url: null, version: "1", related_resource_ids: [], metadata: { task_status: "completed" },
  });
  const initial = Array.from({ length: 22 }, (_, index) => completed(`done-${index + 1}`, `완료 ${index + 1}`));
  const requests = installUiContractFetch({
    taskBatchSizes: [2],
    completedTaskResponses: [
      { items: initial },
      { items: [completed("done-a", "완료 A"), completed("done-b", "완료 B"), completed("done-c", "완료 C"), completed("done-c", "완료 C")] },
      { items: [completed("done-a", "완료 A"), completed("done-b", "완료 B"), completed("done-c", "완료 C")] },
      { items: [completed("done-a", "완료 A"), completed("done-c", "완료 C")] },
    ],
  });
  render(<App />);
  await user.click(await screen.findByRole("tab", { name: /태스크/ }));
  await user.click(await screen.findByRole("button", { name: "완료됨(22) ▸" }));
  expect(await screen.findByText("✓ 완료 20")).toBeInTheDocument();
  expect(screen.queryByText("✓ 완료 21")).not.toBeInTheDocument();
  const callsBeforeMore = requests.filter((request) => request.path.includes("status_scope=completed")).length;
  await user.click(screen.getByRole("button", { name: "더 보기" }));
  expect(await screen.findByText("✓ 완료 22")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.includes("status_scope=completed"))).toHaveLength(callsBeforeMore);

  await user.click(screen.getByRole("button", { name: "현재 목록 새로고침" }));
  expect(await screen.findByRole("button", { name: "완료됨(3) ▾" })).toBeInTheDocument();
  expect(screen.getAllByText(/✓ 완료 [ABC]/)).toHaveLength(3);
  await user.click(screen.getByRole("button", { name: "현재 목록 새로고침" }));
  expect(await screen.findByRole("button", { name: "완료됨(3) ▾" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "현재 목록 새로고침" }));
  expect(await screen.findByRole("button", { name: "완료됨(2) ▾" })).toBeInTheDocument();
  expect(screen.queryByText("✓ 완료 B")).not.toBeInTheDocument();
});

test("Tasks completed materialization failure preserves incomplete Tasks without a fake completed count", async () => {
  const user = userEvent.setup();
  installUiContractFetch({ taskBatchSizes: [2], completedTaskErrors: [true] });
  render(<App />);

  await user.click(await screen.findByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("할 일 1")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "완료됨 ▸" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "완료됨(0) ▸" })).not.toBeInTheDocument();
});

test("keeps Gmail DOM isolated when a stale Tasks preload resolves after a source switch", async () => {
  const user = userEvent.setup();
  const pendingTasks = deferred<Response>();
  const requests = installUiContractFetch({ taskListResponse: pendingTasks.promise });
  render(<App />);

  await waitFor(() => expect(
    requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")),
  ).toHaveLength(1));
  await user.click(await screen.findByRole("tab", { name: /태스크/ }));
  await user.click(screen.getByRole("tab", { name: /메일/ }));
  expect(await screen.findByText("첫 번째 자료")).toBeInTheDocument();

  pendingTasks.resolve(taskListResponse(1));
  await Promise.resolve();
  expect(screen.getByRole("tab", { name: /메일/ })).toHaveAttribute("aria-selected", "true");
  expect(screen.queryByText("할 일 1")).not.toBeInTheDocument();
  expect(document.querySelector(".task-date-section")).toBeNull();
  expect(document.querySelector(".task-resource-item")).toBeNull();
});

test("keeps Gmail DOM unchanged when completed background materialization settles", async () => {
  const completedResponse = deferred<Response>();
  const requests = installUiContractFetch({ completedTaskResponse: completedResponse.promise });
  render(<App />);

  expect(await screen.findByText("첫 번째 자료")).toBeInTheDocument();
  await waitFor(() => expect(requests.some((request) => request.path.includes("status_scope=completed"))).toBe(true));
  completedResponse.resolve(jsonFetchResponse({
    source: "tasks",
    items: [{ source: "tasks", resource_type: "task", resource_id: "done-1", parent_id: "task-list-default", title: "완료 업무", subtitle: null, link_url: null, version: "1", related_resource_ids: [], metadata: { task_status: "completed" } }],
    next_page_token: null,
    api_contract_version: "1",
  }));
  await Promise.resolve();

  expect(screen.getByText("첫 번째 자료")).toBeInTheDocument();
  expect(document.querySelector(".task-date-section")).toBeNull();
  expect(document.querySelector(".task-resource-item")).toBeNull();
});

test("Tasks terminal provider batch uses 20-item UI pages and confirms the exact total locally", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ taskBatchSizes: [41] });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("할 일 1")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "1" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "2" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "3" })).toBeInTheDocument();
  expect(requests.some((request) => request.path === "/api/v1/resources/tasks/count")).toBe(false);

  await user.click(await screen.findByRole("button", { name: "3" }));
  expect(await screen.findByText("할 일 41")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(1);
});

test("Tasks fetches the next provider batch only at the known last UI page", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ taskBatchSizes: [100, 41] });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("할 일 1")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /태스크.*100\+/ })).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "5" })).toHaveLength(1);
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(1);

  await user.click(screen.getByRole("button", { name: "4" }));
  expect(await screen.findByText("할 일 61")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(1);

  await user.click(screen.getByRole("button", { name: "5" }));
  expect(await screen.findByText("할 일 81")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.includes("/api/v1/resources/tasks?page_size=100&page_token=tasks-page-2")).length).toBe(1);
  expect(screen.getByRole("button", { name: "7" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /태스크.*141/ })).toBeInTheDocument();
});

test("Tasks date sort menu materializes every provider batch into a separate cache", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({
    taskBatchSizes: [2, 2],
    taskDues: ["2026-08-12", null, "2026-08-10", "2026-08-11"],
  });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("할 일 1")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "태스크 정렬 메뉴" }));
  expect(screen.getByRole("menu", { name: "정렬 기준" })).toBeInTheDocument();
  await user.click(screen.getByRole("menuitemradio", { name: "날짜순" }));

  await waitFor(() => expect(
    requests.filter((request) => request.path.includes("/api/v1/resources/tasks?page_size=100&page_token=tasks-page-2")).length,
  ).toBe(1));
  const titles = [...document.querySelectorAll(".resource-list .row-title")].map((element) => element.textContent);
  expect(titles).toEqual(["할 일 3", "할 일 4", "할 일 1", "할 일 2"]);
});

test("Tasks date sort menu sorts a terminal 22-item batch without another API request", async () => {
  const user = userEvent.setup();
  const taskDues = Array.from({ length: 22 }, (_, index) => `2026-08-${String(index + 2).padStart(2, "0")}`);
  taskDues[21] = "2026-08-01";
  const requests = installUiContractFetch({ taskBatchSizes: [22], taskDues });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("할 일 1")).toBeInTheDocument();
  const taskRequestsBeforeSort = requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length;

  await user.click(screen.getByRole("button", { name: "태스크 정렬 메뉴" }));
  expect(screen.getByRole("menuitemradio", { name: "기본 순서" })).toHaveAttribute("aria-checked", "true");
  expect(screen.queryByRole("combobox", { name: "할 일 정렬" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("textbox", { name: "작업 검색" }));
  expect(screen.queryByRole("menu", { name: "정렬 기준" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "태스크 정렬 메뉴" }));
  await user.click(screen.getByRole("menuitemradio", { name: "날짜순" }));
  expect(await screen.findByText("할 일 22")).toBeInTheDocument();
  expect(screen.queryByRole("menu", { name: "정렬 기준" })).not.toBeInTheDocument();
  expect([...document.querySelectorAll(".resource-list .row-title")].map((element) => element.textContent)[0]).toBe("할 일 22");
  expect(screen.getByRole("button", { name: "2" })).toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(taskRequestsBeforeSort);

  await user.click(screen.getByRole("button", { name: "2" }));
  expect(await screen.findByText("할 일 21")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "1" }));
  await user.click(screen.getByRole("button", { name: "태스크 정렬 메뉴" }));
  await user.click(screen.getByRole("menuitemradio", { name: "기본 순서" }));
  expect(await screen.findByText("할 일 1")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "태스크 정렬 메뉴" }));
  await user.click(screen.getByRole("menuitemradio", { name: "날짜순" }));
  expect(await screen.findByText("할 일 22")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(taskRequestsBeforeSort);
});

test("Tasks 4xx failure does not retry the same browse request indefinitely", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ taskError: true });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("요청이 올바르지 않습니다.")).toBeInTheDocument();
  await new Promise((resolve) => window.setTimeout(resolve, 20));
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(2);
});

test("Tasks date sort groups the current UI page without changing provider-order rows or requests", async () => {
  const user = userEvent.setup();
  const today = new Date();
  const dateKey = (offset: number): string => {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() + offset);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  };
  const dateLabel = (offset: number): string => {
    const date = new Date(today.getFullYear(), today.getMonth(), today.getDate() + offset);
    return `${date.toLocaleDateString("ko-KR", { month: "long", day: "numeric" })} (${date.toLocaleDateString("ko-KR", { weekday: "short" })})`;
  };
  const longTitle = "아주 길고 긴 업무 제목이 날짜 영역을 밀어내지 않아야 합니다";
  const requests = installUiContractFetch({
    taskBatchSizes: [7],
    taskDues: [null, dateKey(20), dateKey(3), dateKey(1), dateKey(0), dateKey(-1), dateKey(-2)],
    taskTitles: ["날짜 없음 업무", "9월 업무", "8월 업무", "내일 업무", "오늘 업무", longTitle, "이틀 전 업무"],
  });
  render(<App />);

  await user.click(await screen.findByRole("tab", { name: /태스크/ }));
  expect([...document.querySelectorAll(".resource-list .row-title")].map((element) => element.textContent))
    .toEqual(["날짜 없음 업무", "9월 업무", "8월 업무", "내일 업무", "오늘 업무", longTitle, "이틀 전 업무"]);
  expect(document.querySelectorAll(".task-date-section")).toHaveLength(0);
  expect(screen.getByText(longTitle).closest(".task-row-main")).not.toBeNull();
  expect(screen.getByText(dateLabel(-1)).closest(".task-row-date")).not.toBeNull();
  const requestsBeforeSort = requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length;

  await user.click(screen.getByRole("button", { name: "태스크 정렬 메뉴" }));
  await user.click(screen.getByRole("menuitemradio", { name: "날짜순" }));

  expect(await screen.findByLabelText("지난 날짜")).toBeInTheDocument();
  expect(document.querySelector(".resource-list")).toHaveClass("task-date-sorted");
  expect(document.querySelectorAll(".task-date-sorted .task-resource-item")).toHaveLength(7);
  expect(document.querySelectorAll(".task-date-section-divider")).toHaveLength(5);
  expect(screen.getByLabelText("오늘")).toBeInTheDocument();
  expect(screen.getByLabelText("내일")).toBeInTheDocument();
  expect(screen.getByLabelText(dateLabel(3))).toBeInTheDocument();
  expect(screen.getByLabelText(dateLabel(20))).toBeInTheDocument();
  expect(screen.getByLabelText("날짜 없음")).toBeInTheDocument();
  expect([...document.querySelectorAll(".resource-list .row-title")].map((element) => element.textContent))
    .toEqual(["이틀 전 업무", longTitle, "오늘 업무", "내일 업무", "8월 업무", "9월 업무", "날짜 없음 업무"]);
  expect(screen.getByText("1일 지남")).toBeInTheDocument();
  expect(screen.getByText("2일 지남")).toBeInTheDocument();
  expect(screen.queryByText(dateLabel(-1))).not.toBeInTheDocument();
  expect(screen.queryByText(dateLabel(0))).not.toBeInTheDocument();
  expect(screen.queryByText(dateLabel(1))).not.toBeInTheDocument();
  expect(screen.queryAllByText(dateLabel(3))).toHaveLength(1);
  expect(screen.queryAllByText(dateLabel(20))).toHaveLength(1);
  expect(screen.queryByText("예정일 지남")).not.toBeInTheDocument();
  expect(screen.queryByText("마감일 지남")).not.toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(requestsBeforeSort);

  await user.click(screen.getByRole("button", { name: "태스크 정렬 메뉴" }));
  await user.click(screen.getByRole("menuitemradio", { name: "기본 순서" }));
  expect(await screen.findByText("날짜 없음 업무")).toBeInTheDocument();
  expect(document.querySelector(".resource-list")).not.toHaveClass("task-date-sorted");
  expect(document.querySelectorAll(".task-date-section")).toHaveLength(0);
  expect(document.querySelectorAll(".task-date-section-divider")).toHaveLength(0);
  expect([...document.querySelectorAll(".resource-list .row-title")].map((element) => element.textContent))
    .toEqual(["날짜 없음 업무", "9월 업무", "8월 업무", "내일 업무", "오늘 업무", longTitle, "이틀 전 업무"]);
});

test("Tasks keep provider titles in both sort modes and retain the fallback for blank titles", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({
    taskBatchSizes: [2],
    taskTitles: ["GWA-DEADLINE-ONLY-TEST", ""],
  });
  render(<App />);

  await user.click(await screen.findByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("GWA-DEADLINE-ONLY-TEST")).toBeInTheDocument();
  expect(screen.getByText("제목 정보 없음")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "태스크 정렬 메뉴" }));
  await user.click(screen.getByRole("menuitemradio", { name: "날짜순" }));
  expect(await screen.findByText("GWA-DEADLINE-ONLY-TEST")).toBeInTheDocument();

  const taskCallsBeforeRefresh = requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length;
  await user.click(screen.getByRole("button", { name: "현재 목록 새로고침" }));
  expect(await screen.findByText("GWA-DEADLINE-ONLY-TEST")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(taskCallsBeforeRefresh + 1);
});

test("reuses a source-specific cache entry when returning to an already loaded source", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch();
  render(<App />);

  await screen.findByText("첫 번째 자료");
  const gmailCallsBefore = requests.filter((request) => request.path.startsWith("/api/v1/resources/gmail?")).length;
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  await screen.findByText("후속 조치");
  await user.click(screen.getByRole("tab", { name: /메일/ }));
  expect(await screen.findByText("첫 번째 자료")).toBeInTheDocument();

  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/gmail?")).length).toBe(gmailCallsBefore);
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(1);
});

test("restores the cached Gmail next-page token after re-entering the source", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ gmailBatch: true, gmailCount: 40 });
  render(<App />);

  await screen.findByText("자료 1");
  const gmailCallsBefore = requests.filter((request) => request.path.startsWith("/api/v1/resources/gmail?")).length;
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  await screen.findByText("후속 조치");
  await user.click(screen.getByRole("tab", { name: /메일/ }));
  expect(await screen.findByText("자료 1")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "다음" })).toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/gmail?")).length).toBe(gmailCallsBefore);

  await user.click(screen.getByRole("button", { name: "다음" }));
  expect(await screen.findByText("자료 21")).toBeInTheDocument();
  expect(requests.at(-1)?.path).toContain("page_size=20");
  expect(requests.at(-1)?.path).toContain("page_token=page-2");
});

test("uses list-only Gmail requests for unvisited intermediate pages and hydrates the target page", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ gmailBatch: true, gmailCount: 80 });
  render(<App />);

  await screen.findByText("자료 1");
  await user.click(await screen.findByRole("button", { name: "4" }));
  expect(await screen.findByText("자료 61")).toBeInTheDocument();

  const gmailRequests = requests.filter((request) => request.path.startsWith("/api/v1/resources/gmail?"));
  expect(gmailRequests.map((request) => request.path)).toEqual(expect.arrayContaining([
    expect.stringContaining("page_token=page-3&include_thread_metadata=false"),
    expect.stringContaining("page_token=page-4"),
  ]));
  expect(gmailRequests.find((request) => request.path.includes("page_token=page-2"))?.path)
    .not.toContain("include_thread_metadata=false");
  expect(gmailRequests.find((request) => request.path.includes("page_token=page-4"))?.path)
    .not.toContain("include_thread_metadata=false");

  const callsBeforeSelectingIntermediate = gmailRequests.length;
  await user.click(screen.getByRole("button", { name: "2" }));
  expect(await screen.findByText("자료 21")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/gmail?")).length)
    .toBe(callsBeforeSelectingIntermediate + 1);
});

test("selects the requested Gmail page during loading and restores the last loaded page on failure", async () => {
  const user = userEvent.setup();
  const pageFive = deferred<Response>();
  const requests = installUiContractFetch({ gmailBatch: true, gmailCount: 100, gmailPageResponses: { "page-5": pageFive.promise } });
  render(<App />);

  await screen.findByText("자료 1");
  await user.click(await screen.findByRole("button", { name: "3" }));
  expect(await screen.findByText("자료 41")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "5" }));
  expect(screen.getByRole("button", { name: "5" })).toHaveClass("button-primary");
  expect(screen.getByText("5페이지를 불러오는 중입니다.")).toBeInTheDocument();
  expect(screen.getByText("자료 41")).toBeInTheDocument();

  pageFive.resolve(jsonFetchResponse({ error_code: "UPSTREAM_UNAVAILABLE", user_message: "메일을 불러오지 못했습니다.", retryable: true, request_id: "request-1", api_contract_version: "1" }, 502));
  expect(await screen.findByText("메일을 불러오지 못했습니다.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "3" })).toHaveClass("button-primary");
  expect(screen.getByText("자료 41")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.includes("page_token=page-5")).length).toBe(1);
});

test("keeps the loaded Gmail page visible until the requested page succeeds", async () => {
  const user = userEvent.setup();
  const pageFive = deferred<Response>();
  const requests = installUiContractFetch({ gmailBatch: true, gmailCount: 100, gmailPageResponses: { "page-5": pageFive.promise } });
  render(<App />);

  await screen.findByText("자료 1");
  await user.click(await screen.findByRole("button", { name: "3" }));
  expect(await screen.findByText("자료 41")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "5" }));
  expect(screen.getByRole("button", { name: "5" })).toHaveClass("button-primary");
  expect(screen.getByText("5페이지를 불러오는 중입니다.")).toBeInTheDocument();
  expect(screen.getByText("자료 41")).toBeInTheDocument();

  pageFive.resolve(gmailPageResponse(5, 100));
  expect(await screen.findByText("자료 81")).toBeInTheDocument();
  expect(screen.queryByText("5페이지를 불러오는 중입니다.")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "5" })).toHaveClass("button-primary");
  expect(requests.filter((request) => request.path.includes("page_token=page-5")).length).toBe(1);
});

test("shows a cached Gmail page immediately without another request", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ gmailBatch: true, gmailCount: 100 });
  render(<App />);

  await screen.findByText("자료 1");
  await user.click(await screen.findByRole("button", { name: "5" }));
  expect(await screen.findByText("자료 81")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "3" }));
  expect(await screen.findByText("자료 41")).toBeInTheDocument();
  const requestsBeforeCachedPage = requests.length;
  await user.click(screen.getByRole("button", { name: "5" }));
  expect(await screen.findByText("자료 81")).toBeInTheDocument();
  expect(screen.queryByText("5페이지를 불러오는 중입니다.")).not.toBeInTheDocument();
  expect(requests).toHaveLength(requestsBeforeCachedPage);
});

test("prefetches only the next Gmail page and reuses it on navigation", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ gmailBatch: true, gmailCount: 80 });
  render(<App />);

  await screen.findByText("자료 1");
  await waitFor(() => expect(requests.filter((request) => request.path.includes("page_token=page-2")).length).toBe(1));
  expect(requests.some((request) => request.path.includes("page_token=page-3"))).toBe(false);

  await user.click(screen.getByRole("button", { name: "2" }));
  expect(await screen.findByText("자료 21")).toBeInTheDocument();
  expect(screen.queryByText("2페이지를 불러오는 중입니다.")).not.toBeInTheDocument();
  expect(requests.filter((request) => request.path.includes("page_token=page-2")).length).toBe(1);
  await waitFor(() => expect(requests.filter((request) => request.path.includes("page_token=page-3")).length).toBe(1));
});

test("reuses an in-flight Gmail prefetch when the user selects that page", async () => {
  const user = userEvent.setup();
  const pageTwo = deferred<Response>();
  const requests = installUiContractFetch({ gmailBatch: true, gmailCount: 80, gmailPageResponses: { "page-2": pageTwo.promise } });
  render(<App />);

  await screen.findByText("자료 1");
  await waitFor(() => expect(requests.filter((request) => request.path.includes("page_token=page-2")).length).toBe(1));
  await user.click(screen.getByRole("button", { name: "2" }));
  expect(screen.getByRole("button", { name: "2" })).toHaveClass("button-primary");
  expect(screen.getByText("2페이지를 불러오는 중입니다.")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.includes("page_token=page-2")).length).toBe(1);

  pageTwo.resolve(gmailPageResponse(2, 80));
  expect(await screen.findByText("자료 21")).toBeInTheDocument();
});

test("keeps the latest Gmail page intent when an earlier prefetch resolves later", async () => {
  const user = userEvent.setup();
  const pageTwo = deferred<Response>();
  const pageThree = deferred<Response>();
  const requests = installUiContractFetch({
    gmailBatch: true,
    gmailCount: 80,
    gmailPageResponses: { "page-2": pageTwo.promise, "page-3": pageThree.promise },
  });
  render(<App />);

  await screen.findByText("자료 1");
  await waitFor(() => expect(requests.filter((request) => request.path.includes("page_token=page-2")).length).toBe(1));
  await user.click(screen.getByRole("button", { name: "2" }));
  expect(screen.getByRole("button", { name: "2" })).toHaveClass("button-primary");
  await user.click(screen.getByRole("button", { name: "3" }));
  expect(screen.getByRole("button", { name: "3" })).toHaveClass("button-primary");

  pageTwo.resolve(gmailPageResponse(2, 80));
  await waitFor(() => expect(requests.filter((request) => request.path.includes("page_token=page-3")).length).toBe(1));
  expect(screen.getByRole("button", { name: "3" })).toHaveClass("button-primary");
  expect(screen.getByText("자료 1")).toBeInTheDocument();

  pageThree.resolve(gmailPageResponse(3, 80));
  expect(await screen.findByText("자료 41")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "3" })).toHaveClass("button-primary");
});

test("does not retry a failed Gmail count while the source scope is unchanged", async () => {
  const requests = installUiContractFetch({ gmailCountError: true });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await waitFor(() => expect(requests.filter((request) => request.path === "/api/v1/resources/gmail/count")).toHaveLength(1));
  await new Promise((resolve) => window.setTimeout(resolve, 50));
  expect(requests.filter((request) => request.path === "/api/v1/resources/gmail/count")).toHaveLength(1);
});

test("debounces Gmail search input into one browse request", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch();
  render(<App />);

  const input = await screen.findByRole("textbox", { name: "메일 검색" });
  const initialBrowseCalls = requests.filter((request) => request.path.startsWith("/api/v1/resources/gmail?")).length;
  await user.type(input, "project");
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/gmail?")).length).toBe(initialBrowseCalls);
  await waitFor(() => expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/gmail?")).length).toBe(initialBrowseCalls + 1));
  expect(requests.at(-1)?.path).toContain("query=project");
});

test("reuses the Calendar event cache when returning to Calendar", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch();
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /캘린더/ }));
  await selectCalendarDate(user, "2026-08-10");
  await screen.findByText("프로젝트 검토");
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  await screen.findByText("후속 조치");
  await user.click(screen.getByRole("tab", { name: /캘린더/ }));
  expect(await screen.findByText("프로젝트 검토")).toBeInTheDocument();

  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar?")).length).toBe(3);
});

test("does not let a delayed previous source response replace the active source", async () => {
  const user = userEvent.setup();
  const delayedGmail = deferred<Response>();
  installUiContractFetch({ gmailListResponse: delayedGmail.promise });
  render(<App />);

  await user.click(await screen.findByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("후속 조치")).toBeInTheDocument();
  delayedGmail.resolve(jsonFetchResponse({ source: "gmail", items: [gmailThread()], next_page_token: null, api_contract_version: "1" }));

  await waitFor(() => expect(screen.getByText("후속 조치")).toBeInTheDocument());
  expect(screen.queryByText("첫 번째 자료")).not.toBeInTheDocument();
});

test("does not let a delayed Calendar response replace the active Tasks source", async () => {
  const user = userEvent.setup();
  const delayedCalendar = deferred<Response>();
  installUiContractFetch({ calendarListResponse: delayedCalendar.promise });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /캘린더/ }));
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("후속 조치")).toBeInTheDocument();
  delayedCalendar.resolve(jsonFetchResponse(calendarEventResponse()));

  await waitFor(() => expect(screen.getByText("후속 조치")).toBeInTheDocument());
  expect(screen.queryByText("프로젝트 검토")).not.toBeInTheDocument();
});

test("refresh bypasses the known page and re-requests only the active source", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch();
  render(<App />);

  await screen.findByText("첫 번째 자료");
  const gmailCallsBefore = requests.filter((request) => request.path.startsWith("/api/v1/resources/gmail?")).length;
  await user.click(screen.getByRole("button", { name: "현재 목록 새로고침" }));
  await waitFor(() => expect(
    requests.filter((request) => request.path.startsWith("/api/v1/resources/gmail?")).length,
  ).toBe(gmailCallsBefore + 2));
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(1);
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar?")).length).toBe(0);
});

test("Calendar refresh re-requests events without loading calendar containers", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch();
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /캘린더/ }));
  await screen.findByLabelText("월간 일정");
  const callsBefore = requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar?")).length;
  await user.click(screen.getByRole("button", { name: "현재 목록 새로고침" }));

  await waitFor(() => expect(
    requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar?")).length,
  ).toBe(callsBefore + 1));
  expect(requests.some((request) => request.path.startsWith("/api/v1/resources/calendar/count"))).toBe(false);
  expect(screen.queryByText("캘린더 목록")).not.toBeInTheDocument();
});

test("Tasks refresh keeps stale UI until a fresh provider result replaces its cache", async () => {
  const user = userEvent.setup();
  const refreshedTasks = deferred<Response>();
  const requests = installUiContractFetch({
    taskBatchSizes: [23],
    taskRefreshResponse: refreshedTasks.promise,
  });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("할 일 1")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /태스크.*23/ })).toBeInTheDocument();
  const taskCallsBeforeRefresh = requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length;

  await user.click(screen.getByRole("button", { name: "현재 목록 새로고침" }));
  await waitFor(() => expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(taskCallsBeforeRefresh + 1));
  expect(requests.at(-1)?.path).toContain("refresh=true");
  expect(screen.getByRole("tab", { name: /태스크.*23/ })).toBeInTheDocument();
  expect(screen.getByText("할 일 1")).toBeInTheDocument();

  refreshedTasks.resolve(taskListResponse(22, 2));
  expect(await screen.findByRole("tab", { name: /태스크.*22/ })).toBeInTheDocument();
  expect(screen.queryByText("할 일 1")).not.toBeInTheDocument();
  expect(requests.some((request) => request.path === "/api/v1/resources/tasks/count")).toBe(false);
});

test("Tasks refresh failure keeps the existing count and provider-order list", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ taskBatchSizes: [23], taskRefreshError: true });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("할 일 1")).toBeInTheDocument();
  const taskCallsBeforeRefresh = requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length;

  await user.click(screen.getByRole("button", { name: "현재 목록 새로고침" }));
  expect(await screen.findByText("태스크를 불러오지 못했습니다.")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: /태스크.*23/ })).toBeInTheDocument();
  expect(screen.getByText("할 일 1")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length).toBe(taskCallsBeforeRefresh + 1);
});

test("Tasks date-sort refresh invalidates its cached result and rebuilds it from a fresh batch", async () => {
  const user = userEvent.setup();
  const taskDues = Array.from({ length: 22 }, (_, index) => `2026-08-${String(index + 2).padStart(2, "0")}`);
  taskDues[21] = "2026-08-01";
  const requests = installUiContractFetch({
    taskBatchSizes: [22],
    taskDues,
    taskRefreshBatchSize: 21,
  });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  await user.click(screen.getByRole("button", { name: "태스크 정렬 메뉴" }));
  await user.click(screen.getByRole("menuitemradio", { name: "날짜순" }));
  expect(await screen.findByRole("tab", { name: /태스크.*22/ })).toBeInTheDocument();
  expect(screen.getByText("할 일 22")).toBeInTheDocument();
  const callsBeforeRefresh = requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length;

  await user.click(screen.getByRole("button", { name: "현재 목록 새로고침" }));

  await waitFor(() => expect(
    requests.filter((request) => request.path.startsWith("/api/v1/resources/tasks?") && !request.path.includes("status_scope=completed")).length,
  ).toBe(callsBeforeRefresh + 1));
  expect(requests.at(-1)?.path).toContain("refresh=true");
  expect(await screen.findByRole("tab", { name: /태스크.*21/ })).toBeInTheDocument();
  expect(screen.queryByText("할 일 22")).not.toBeInTheDocument();
  expect(requests.some((request) => request.path === "/api/v1/resources/tasks/count")).toBe(false);
});

test("resource viewer empty state follows the active source and clears the previous focus", async () => {
  const user = userEvent.setup();
  installUiContractFetch();
  render(<App />);

  expect(await screen.findByText("왼쪽 목록에서 메일을 선택하면 상세 내용을 확인할 수 있습니다.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /첫 번째 자료/ }));
  expect(await screen.findByText("실제 메일 본문입니다.")).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /캘린더/ }));
  expect(await screen.findByText("왼쪽 목록에서 일정을 선택하면 상세 내용을 확인할 수 있습니다.")).toBeInTheDocument();
  expect(screen.queryByText("실제 메일 본문입니다.")).not.toBeInTheDocument();

  await selectCalendarDate(user, "2026-08-10");
  await user.click(screen.getByRole("button", { name: /프로젝트 검토/ }));
  expect(screen.getByRole("heading", { name: "프로젝트 검토" })).toBeInTheDocument();
  expect(screen.getByText("시작 시간")).toBeInTheDocument();
  expect(screen.getByText("종료 시간")).toBeInTheDocument();
  expect(screen.queryByText("2026-08-10T09:00:00+09:00")).not.toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByText("왼쪽 목록에서 태스크를 선택하면 상세 내용을 확인할 수 있습니다.")).toBeInTheDocument();
  expect(screen.queryByRole("heading", { name: "프로젝트 검토" })).not.toBeInTheDocument();
});

test("source tabs expose their search, composer, and Calendar section labels", async () => {
  const user = userEvent.setup();
  installUiContractFetch();
  render(<App />);

  expect(await screen.findByRole("textbox", { name: "메일 검색" })).toHaveAttribute(
    "placeholder",
    "검색 (제목, 보낸사람, 내용)",
  );
  expect(screen.getByRole("textbox", { name: "선택한 메일에 대해 질문하거나 업무를 요청하세요..." })).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /태스크/ }));
  expect(await screen.findByRole("textbox", { name: "작업 검색" })).toHaveAttribute("placeholder", "작업 검색");
  expect(screen.getByRole("textbox", { name: "선택한 태스크에 대해 질문하거나 업무를 요청하세요..." })).toBeInTheDocument();

  await user.click(screen.getByRole("tab", { name: /캘린더/ }));
  expect(await screen.findByLabelText("월간 일정")).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "일정 검색" })).toHaveAttribute("placeholder", "일정 검색");
  expect(screen.getByRole("textbox", { name: "선택한 일정에 대해 질문하거나 업무를 요청하세요..." })).toBeInTheDocument();
});

test("Tasks UI renders normalized status and scheduled date without raw provider values", async () => {
  const user = userEvent.setup();
  installUiContractFetch({
    taskMetadata: { task_status: "incomplete", scheduled_date: "2000-01-01" },
  });
  render(<App />);

  await user.click(await screen.findByRole("tab", { name: /태스크/ }));
  const row = await screen.findByRole("button", { name: /후속 조치/ });
  expect(screen.getByText("1월 1일 (토)")).toBeInTheDocument();
  await user.click(row);

  expect(await screen.findByText("미완료")).toBeInTheDocument();
  expect(screen.getByText("예정일")).toBeInTheDocument();
  expect(screen.getByText("2000년 1월 1일 (토)")).toBeInTheDocument();
  expect(screen.queryByText("needsAction")).not.toBeInTheDocument();
  expect(screen.queryByText("2000-01-01T00:00:00.000Z")).not.toBeInTheDocument();
  expect(screen.queryByText("마감일")).not.toBeInTheDocument();
  expect(screen.queryByText("예정일 지남")).not.toBeInTheDocument();
});

test("completed Tasks display their normalized status", async () => {
  const user = userEvent.setup();
  installUiContractFetch({
    taskMetadata: { task_status: "completed", scheduled_date: "2000-01-01" },
  });
  render(<App />);

  await user.click(await screen.findByRole("tab", { name: /태스크/ }));
  await user.click(await screen.findByRole("button", { name: /후속 조치/ }));
  expect(await screen.findByText("완료")).toBeInTheDocument();
  expect(screen.queryByText("예정일 지남")).not.toBeInTheDocument();
});

test("Calendar rows use compact timed and all-day time labels", async () => {
  const user = userEvent.setup();
  installUiContractFetch({
    calendarEvents: [
      calendarEventItem({
        resource_id: "event-timed",
        title: "디자인 리뷰 미팅",
        metadata: {
          start: "2026-08-11T15:00:00+09:00",
          end: "2026-08-11T16:00:00+09:00",
        },
      }),
      calendarEventItem({
        resource_id: "event-all-day",
        title: "연차",
        metadata: {
          start: "2026-08-12",
          end: "2026-08-13",
        },
      }),
    ],
  });
  render(<App />);

  await user.click(await screen.findByRole("tab", { name: /캘린더/ }));
  await selectCalendarDate(user, "2026-08-11");
  expect(await screen.findByText("15:00")).toBeInTheDocument();
  expect(screen.getByText("디자인 리뷰 미팅")).toBeInTheDocument();
  await selectCalendarDate(user, "2026-08-12");
  expect(screen.getByText("종일")).toBeInTheDocument();
  expect(screen.getByText("연차")).toBeInTheDocument();
});

test("Calendar Month View materializes provider pages, keeps date selection client-side, and reuses a visited month", async () => {
  const user = userEvent.setup();
  const firstPage = calendarEventResponse([calendarEventItem()], "calendar-page-2");
  const secondPage = calendarEventResponse([
    calendarEventItem({ resource_id: "event-2", title: "두 번째 일정" }),
  ]);
  const requests = installUiContractFetch({ calendarPageResponses: [
    jsonFetchResponse(firstPage),
    jsonFetchResponse(secondPage),
  ] });
  render(<App />);

  await user.click(await screen.findByRole("tab", { name: /캘린더/ }));
  await screen.findByLabelText("월간 일정");
  await waitFor(() => expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar?")).length).toBeGreaterThanOrEqual(4));
  const calendarRequests = requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar?"));
  expect(calendarRequests[0]?.path).toContain("page_size=100");
  expect(calendarRequests[0]?.path).toContain("time_min=");
  expect(calendarRequests[0]?.path).toContain("time_max=");
  expect(calendarRequests[1]?.path).toContain("page_token=calendar-page-2");

  const callsBeforeSelection = calendarRequests.length;
  await selectCalendarDate(user, "2026-08-10", 2);
  expect(await screen.findByText("두 번째 일정")).toBeInTheDocument();
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar?")).length).toBe(callsBeforeSelection);

  await user.click(screen.getByRole("button", { name: "다음 달" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "다음 달" })).toBeInTheDocument());
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar?")).length).toBe(callsBeforeSelection + 1);
  await user.click(screen.getByRole("button", { name: "이전 달" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "다음 달" })).toBeInTheDocument());
  expect(requests.filter((request) => request.path.startsWith("/api/v1/resources/calendar?")).length).toBe(callsBeforeSelection + 1);
});

test("Calendar Month View keeps only the latest month response and reuses adjacent prefetch", async () => {
  const user = userEvent.setup();
  const september = deferred<Response>();
  const october = deferred<Response>();
  const requests = installUiContractFetch({
    calendarResponseForPath: (path) => {
      const timeMin = new URL(`http://local${path}`).searchParams.get("time_min") ?? "";
      if (timeMin.includes("-08-29")) return september.promise;
      if (timeMin.includes("-09-26")) return october.promise;
      return jsonFetchResponse(calendarEventResponse());
    },
  });
  render(<App />);

  await user.click(await screen.findByRole("tab", { name: /캘린더/ }));
  await screen.findByLabelText("월간 일정");
  await waitFor(() => expect(requests.some((request) => request.path.includes("-06-27"))).toBe(true));
  await waitFor(() => expect(requests.some((request) => request.path.includes("-08-29"))).toBe(true));
  expect(requests.some((request) => request.path.includes("-09-26"))).toBe(false);

  await user.click(screen.getByRole("button", { name: "다음 달" }));
  await user.click(screen.getByRole("button", { name: "다음 달" }));
  await waitFor(() => expect(requests.filter((request) => request.path.includes("-09-26"))).toHaveLength(1));
  october.resolve(jsonFetchResponse(calendarEventResponse([
    calendarEventItem({ resource_id: "october", title: "10월 일정", metadata: { start: "2026-10-01T09:00:00+09:00", end: "2026-10-01T10:00:00+09:00" } }),
  ])));
  await screen.findByText("10월 일정");

  september.resolve(jsonFetchResponse(calendarEventResponse([
    calendarEventItem({ resource_id: "september", title: "9월 일정", metadata: { start: "2026-09-01T09:00:00+09:00", end: "2026-09-01T10:00:00+09:00" } }),
  ])));
  await waitFor(() => expect(screen.getByText("10월 일정")).toBeInTheDocument());
  expect(screen.queryByText("9월 일정")).not.toBeInTheDocument();
  expect(requests.filter((request) => request.path.includes("-08-29"))).toHaveLength(1);
});

test("Calendar refresh ignores an older generation after a newer refresh completes", async () => {
  const user = userEvent.setup();
  const firstRefresh = deferred<Response>();
  const secondRefresh = deferred<Response>();
  let augustRequests = 0;
  const requests = installUiContractFetch({
    calendarResponseForPath: (path) => {
      const timeMin = new URL(`http://local${path}`).searchParams.get("time_min") ?? "";
      if (!timeMin.includes("-07-25")) return jsonFetchResponse(calendarEventResponse());
      augustRequests += 1;
      if (augustRequests === 2) return firstRefresh.promise;
      if (augustRequests === 3) return secondRefresh.promise;
      return jsonFetchResponse(calendarEventResponse());
    },
  });
  render(<App />);

  await user.click(await screen.findByRole("tab", { name: /캘린더/ }));
  await screen.findByLabelText("월간 일정");
  const refresh = screen.getByRole("button", { name: "현재 목록 새로고침" });
  await user.click(refresh);
  await user.click(refresh);
  await waitFor(() => expect(augustRequests).toBe(3));

  secondRefresh.resolve(jsonFetchResponse(calendarEventResponse([
    calendarEventItem({ resource_id: "fresh", title: "최신 일정", metadata: { start: "2026-08-10T09:00:00+09:00", end: "2026-08-10T10:00:00+09:00" } }),
  ])));
  await selectCalendarDate(user, "2026-08-10");
  await screen.findByText("최신 일정");
  firstRefresh.resolve(jsonFetchResponse(calendarEventResponse([
    calendarEventItem({ resource_id: "stale", title: "오래된 일정", metadata: { start: "2026-08-10T09:00:00+09:00", end: "2026-08-10T10:00:00+09:00" } }),
  ])));
  await waitFor(() => expect(screen.getByText("최신 일정")).toBeInTheDocument());
  expect(screen.queryByText("오래된 일정")).not.toBeInTheDocument();
  expect(requests.filter((request) => request.path.includes("-07-25"))).toHaveLength(3);
});

test("TST-UI-205 does not render a fake resource count", async () => {
  installUiContractFetch();
  render(<App />);

  await screen.findByText("첫 번째 자료");
  expect(screen.queryByText(/총 .*건/)).not.toBeInTheDocument();
});

test("does not expose a technical resource ID in the row or viewer", async () => {
  const technicalId = "19fe92f3e539543b";
  installUiContractFetch({
    resource: {
      title: technicalId,
      subtitle: technicalId,
      metadata: {
        sender: "김대리",
        sender_email: "kim@example.com",
        subject: "Q2 마케팅 캠페인 결과 공유",
        snippet: "후속 조치 검토를 요청드립니다.",
        received_at: "2025-05-24 09:15",
      },
    },
  });
  const user = userEvent.setup();
  render(<App />);

  const row = await screen.findByRole("button", { name: /Q2 마케팅 캠페인 결과 공유/ });
  expect(screen.getByText("김대리 <kim@example.com>")).toBeInTheDocument();
  expect(screen.getByText(/2025/)).toBeInTheDocument();
  expect(screen.queryByText("2025-05-24 09:15")).not.toBeInTheDocument();
  expect(screen.getByText("후속 조치 검토를 요청드립니다.")).toBeInTheDocument();
  expect(screen.queryByText(technicalId)).not.toBeInTheDocument();
  await user.click(row);
  expect(screen.getByRole("heading", { name: "Q2 마케팅 캠페인 결과 공유" })).toBeInTheDocument();
  expect(screen.queryByText(technicalId)).not.toBeInTheDocument();
});

test("uses the Gmail subject instead of a generic resource fallback title", async () => {
  installUiContractFetch({
    resource: {
      title: "메일 자료",
      metadata: { subject: "예산 검토 요청", snippet: "검토 의견을 부탁드립니다." },
    },
  });
  render(<App />);

  await screen.findByText("예산 검토 요청");
  expect(screen.queryByText("메일 자료")).not.toBeInTheDocument();
});

test("TST-UI-206 keeps focus separate from multiple selected resources and sends selected IDs", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ twoItems: true });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  const selectControls = screen.getAllByRole("checkbox", { name: /선택/ });
  await user.click(selectControls[0]!);
  await user.click(selectControls[1]!);
  await user.click(screen.getByRole("button", { name: /두 번째 자료/ }));
  expect(screen.getByRole("heading", { name: "두 번째 자료" })).toBeInTheDocument();
  expect(screen.getByText("요청에 사용할 자료 2개")).toBeInTheDocument();
  expect(screen.getByText("첫 번째 자료 · 두 번째 자료")).toBeInTheDocument();
  await user.type(screen.getByRole("textbox", { name: "선택한 메일에 대해 질문하거나 업무를 요청하세요..." }), "선택 자료 정리");
  await user.click(screen.getByRole("button", { name: "보내기" }));
  const start = requests.find((request) => request.path === "/api/v1/runs");
  const body = JSON.parse(String(start?.init?.body)) as { entry_mode: string; selected_resource_ids: string[] };
  expect(body).toMatchObject({
    entry_mode: "RESOURCE_SELECTED",
    selected_resource_ids: ["resource-1", "resource-2"],
  });
  expect(new Set(body.selected_resource_ids).size).toBe(2);
});

test("TST-UI-207 uses AGENT_SEARCH without selection and quick action does not write directly", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch();
  render(<App />);

  await screen.findByText("첫 번째 자료");
  expect(screen.queryByText(/요청에 사용할 자료/)).not.toBeInTheDocument();
  await user.type(screen.getByRole("textbox", { name: "선택한 메일에 대해 질문하거나 업무를 요청하세요..." }), "메일을 찾아줘");
  await user.click(screen.getByRole("button", { name: "보내기" }));
  const start = requests.find((request) => request.path === "/api/v1/runs");
  expect(JSON.parse(String(start?.init?.body))).toMatchObject({ entry_mode: "AGENT_SEARCH" });
  expect(requests.some((request) => request.path.includes("/actions/") || request.path.includes("gmail/send"))).toBe(false);
});

test("TST-UI-208 Gmail viewer and approval use only available projection fields", async () => {
  installUiContractFetch({ action: true });
  render(<App />);

  await screen.findByText("첫 번째 자료");
  await userEvent.setup().click(screen.getByRole("button", { name: /첫 번째 자료/ }));
  expect(await screen.findByText("실제 메일 본문입니다.")).toBeInTheDocument();
  expect(screen.getByText("김대리 <kim@example.com>")).toBeInTheDocument();
  expect(screen.getByText(/받는 사람 user@example.com/)).toBeInTheDocument();
  expect(screen.getByText("승인 상세")).toBeInTheDocument();
  expect(screen.queryByText("Evidence")).not.toBeInTheDocument();
});

test("Action risk follows the SSE-refreshed snapshot without rendering raw JSON", async () => {
  const options: Parameters<typeof installUiContractFetch>[0] = {
    action: true,
    actionRisk: {},
  };
  installUiContractFetch(options);
  render(<App />);

  await screen.findByText("승인 상세");
  expect(screen.queryByText(/서버 검증에서 확인된 위험 정보/)).not.toBeInTheDocument();

  options.actionRisk = {
    schedule: { outcome: "WARNING", candidate_resource_ids: ["task-sensitive-1"] },
  };
  FakeEventSource.instances[0]?.emit("action_status", { action_id: "action-1" });

  expect(
    await screen.findByText("서버 검증에서 확인된 위험 정보가 있습니다. 승인 전에 확인해 주세요."),
  ).toBeInTheDocument();
  expect(document.body.textContent).not.toContain("task-sensitive-1");
  expect(document.body.textContent).not.toContain("candidate_resource_ids");
});

test.each([
  ["RISK", "현재 일정 기준으로 가능한 시간이 제한적입니다."],
  [
    "INFEASIBLE",
    "현재 업무 시간과 일정 기준으로 마감 전에 필요한 연속 시간을 확보할 수 없습니다.",
  ],
])("feasibility %s renders only the safe projection", async (decision, message) => {
  installUiContractFetch({
    action: true,
    actionRisk: {
      feasibility_input: { business_deadline: "private-deadline" },
      feasibility: {
        decision,
        reason_codes: ["PRIVATE_REASON"],
        required_duration_minutes: 120,
      },
    },
  });
  render(<App />);

  expect(await screen.findByText(message)).toBeInTheDocument();
  expect(document.body.textContent).not.toContain("private-deadline");
  expect(document.body.textContent).not.toContain("PRIVATE_REASON");
  if (decision === "INFEASIBLE") {
    expect(screen.queryByRole("button", { name: "승인" })).not.toBeInTheDocument();
  }
});

test("similar Task duplicate requires an acknowledgement without exposing resource IDs", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({
    action: true,
    actionRisk: {
      duplicate: {
        decision: "SIMILAR_CANDIDATE",
        matched_resource_ids: ["task-private-1"],
      },
    },
  });
  render(<App />);

  expect(await screen.findByText("비슷한 기존 작업이 있습니다.")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "확인하고 승인" }));

  const approve = requests.find((request) => request.path.endsWith("/actions/action-1/approve"));
  expect(JSON.parse(String(approve?.init?.body))).toMatchObject({
    duplicate_acknowledged: true,
  });
  expect(document.body.textContent).not.toContain("task-private-1");
});

test("clear Task duplicate is blocked by default and offers an explicit override", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({
    action: true,
    actionRisk: {
      duplicate: {
        decision: "CLEAR_DUPLICATE",
        matched_resource_ids: ["task-private-2"],
      },
    },
  });
  render(<App />);

  expect(await screen.findByText(/동일한 작업이 이미 있습니다/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "승인" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "그래도 새로 만들기" }));

  const approve = requests.find((request) => request.path.endsWith("/actions/action-1/approve"));
  expect(JSON.parse(String(approve?.init?.body))).toMatchObject({
    duplicate_acknowledged: true,
  });
  expect(document.body.textContent).not.toContain("task-private-2");
});

test("NOT_DUPLICATE shows no warning and uses ordinary approval", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({
    action: true,
    actionRisk: {
      duplicate: {
        decision: "NOT_DUPLICATE",
        matched_resource_ids: [],
      },
    },
  });
  render(<App />);

  await user.click(await screen.findByRole("button", { name: "승인" }));
  expect(screen.queryByText(/기존 작업이 있습니다/)).not.toBeInTheDocument();
  const approve = requests.find((request) => request.path.endsWith("/actions/action-1/approve"));
  expect(JSON.parse(String(approve?.init?.body))).toMatchObject({
    duplicate_acknowledged: false,
  });
});

test("Calendar WARNING requires explicit acknowledgement without exposing authority fields", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({
    action: true,
    actionRisk: {
      calendar_conflict: {
        decision: "WARNING",
        matched_resource_ids: ["calendar-private-1"],
        reason_codes: ["OUTSIDE_WORK_HOURS"],
      },
    },
  });
  render(<App />);

  expect(
    await screen.findByText("겹칠 가능성이 있거나 업무 시간 밖의 일정입니다."),
  ).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "확인하고 승인" }));
  const approve = requests.find((request) => request.path.endsWith("/actions/action-1/approve"));
  expect(JSON.parse(String(approve?.init?.body))).toMatchObject({
    calendar_conflict_acknowledged: true,
  });
  expect(document.body.textContent).not.toContain("calendar-private-1");
  expect(document.body.textContent).not.toContain("OUTSIDE_WORK_HOURS");
});

test("Calendar HARD_CONFLICT offers an explicit override", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({
    action: true,
    actionRisk: {
      calendar_conflict: {
        decision: "HARD_CONFLICT",
        matched_resource_ids: ["calendar-private-2"],
      },
    },
  });
  render(<App />);

  expect(await screen.findByText("해당 시간에 기존 일정이 있습니다.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "승인" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "충돌을 알고도 진행" }));
  const approve = requests.find((request) => request.path.endsWith("/actions/action-1/approve"));
  expect(JSON.parse(String(approve?.init?.body))).toMatchObject({
    calendar_conflict_acknowledged: true,
  });
  expect(document.body.textContent).not.toContain("calendar-private-2");
});

test("Calendar NO_CONFLICT shows ordinary approval", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({
    action: true,
    actionRisk: {
      calendar_conflict: { decision: "NO_CONFLICT", matched_resource_ids: [] },
    },
  });
  render(<App />);

  await user.click(await screen.findByRole("button", { name: "승인" }));
  expect(screen.queryByText(/기존 일정/)).not.toBeInTheDocument();
  const approve = requests.find((request) => request.path.endsWith("/actions/action-1/approve"));
  expect(JSON.parse(String(approve?.init?.body))).toMatchObject({
    calendar_conflict_acknowledged: false,
  });
});

test("Gmail detail shows loading, retries a safe error, and renders the actual body", async () => {
  const user = userEvent.setup();
  installUiContractFetch({ detailErrorOnce: true });
  render(<App />);

  await user.click(await screen.findByRole("button", { name: /첫 번째 자료/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("메일 내용을 불러오지 못했습니다.");
  await user.click(screen.getByRole("button", { name: "다시 시도" }));
  expect(await screen.findByText("실제 메일 본문입니다.")).toBeInTheDocument();
});

test("Gmail detail keeps an empty body honest and never exposes IDs or raw dates", async () => {
  const technicalId = "19fe92f3e539543b";
  installUiContractFetch({
    resource: {
      resource_id: technicalId,
      title: "업무 확인",
      metadata: { received_at: "Mon, 10 Aug 2026 09:15:00 +0900" },
    },
    detail: {
      resource_id: technicalId,
      message_id: "19fe92f3e539543c",
      body: null,
      received_at: "Mon, 10 Aug 2026 09:15:00 +0900",
    },
  });
  render(<App />);

  await userEvent.setup().click(await screen.findByRole("button", { name: /업무 확인/ }));
  expect(await screen.findByText("표시할 메일 내용이 없습니다.")).toBeInTheDocument();
  expect(document.body.textContent).not.toContain(technicalId);
  expect(document.body.textContent).not.toContain("Mon, 10 Aug 2026 09:15:00 +0900");
});

test("TST-UI-209 renders independent approval commands with versions and disables duplicate submission", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ action: true });
  render(<App />);

  await screen.findByRole("button", { name: "승인" });
  await user.click(screen.getByRole("button", { name: "승인" }));
  const approve = requests.find((request) => request.path.endsWith("/approve"));
  expect(JSON.parse(String(approve?.init?.body))).toMatchObject({ expected_version: 7 });
  expect(screen.getByText("승인 상세")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "수정" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "거절" })).toBeInTheDocument();
});

test("approved Action can be rejected and refreshes to a non-executable rejected state", async () => {
  const user = userEvent.setup();
  const requests = installUiContractFetch({ action: true, actionStatus: "APPROVED" });
  render(<App />);

  await user.click(await screen.findByRole("button", { name: "거절" }));
  const reject = requests.find((request) => request.path.endsWith("/reject"));
  expect(JSON.parse(String(reject?.init?.body))).toMatchObject({
    expected_version: 7,
    reason_code: null,
  });
  expect(await screen.findByText("REJECTED")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "승인" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "거절" })).not.toBeInTheDocument();
});

test("TST-UI-210 filters conversations and shows recent execution fallback", async () => {
  const user = userEvent.setup();
  installUiContractFetch({ conversations: true, run: false });
  render(<App />);

  await screen.findByText("업무 대화");
  await user.type(screen.getByRole("textbox", { name: "대화 검색" }), "없는 대화");
  expect(screen.queryByText("업무 대화")).not.toBeInTheDocument();
  expect(screen.getByText("표시할 실행 기록이 없습니다.")).toBeInTheDocument();
});

test("TST-UI-211 shows loading, empty, error, focus, and disabled pagination states", async () => {
  installUiContractFetch({ empty: true });
  render(<App />);

  await screen.findByText("표시할 자료가 없습니다.");
  expect(screen.getByRole("button", { name: "이전" })).toBeDisabled();
  expect(screen.getByRole("textbox", { name: "선택한 메일에 대해 질문하거나 업무를 요청하세요..." })).toBeInTheDocument();
});

test("composer exposes one prompt, has no clear button, and retains the send control", async () => {
  installUiContractFetch();
  render(<App />);

  const composer = await screen.findByRole("textbox", { name: "선택한 메일에 대해 질문하거나 업무를 요청하세요..." });
  expect(composer).toHaveAttribute("placeholder", "선택한 메일에 대해 질문하거나 업무를 요청하세요...");
  expect(screen.queryByText("선택한 메일에 대해 질문하거나 업무를 요청하세요...")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "입력 지우기" })).not.toBeInTheDocument();
  const send = screen.getByRole("button", { name: "보내기" });
  expect(send).toHaveAttribute("title", "보내기");
  expect(composer.closest(".composer-surface")).toContainElement(send);
});

test("simple Gmail focus prioritizes the viewer and only shows the run header for an actual run", async () => {
  const user = userEvent.setup();
  installUiContractFetch({ run: false });
  render(<App />);

  await user.click(await screen.findByRole("button", { name: /첫 번째 자료/ }));
  expect(await screen.findByText("실제 메일 본문입니다.")).toBeInTheDocument();
  expect(screen.queryByText("새 요청")).not.toBeInTheDocument();
  expect(screen.queryByText("작업을 처리하고 있습니다.")).not.toBeInTheDocument();
});

test("TST-UI-213 hides raw runtime status and has no native window controls", async () => {
  installUiContractFetch({ status: "SINGLE" });
  render(<App />);

  await screen.findByText("작업을 처리하고 있습니다.");
  expect(screen.queryByText("SINGLE")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /최소화|최대화|닫기/ })).not.toBeInTheDocument();
});

test("shows a partial-result notice after a run is cancelled", async () => {
  installUiContractFetch({ status: "CANCELLED", resultKind: "PARTIAL" });
  render(<App />);

  expect(
    await screen.findByText("일부 작업은 완료되었고 나머지는 취소되었습니다."),
  ).toBeInTheDocument();
});

function installUiContractFetch(options: {
  action?: boolean;
  actionStatus?: string;
  actionRisk?: Record<string, unknown>;
  accountAbsent?: boolean;
  conversations?: boolean;
  calendarEvents?: Record<string, unknown>[];
  calendarPageResponses?: Response[];
  calendarResponseForPath?: (path: string) => Response | Promise<Response>;
  detail?: Record<string, unknown>;
  detailErrorOnce?: boolean;
  empty?: boolean;
  calendarListResponse?: Promise<Response>;
  gmailListResponse?: Promise<Response>;
  gmailBatch?: boolean;
  gmailPageResponses?: Record<string, Promise<Response>>;
  gmailCount?: number;
  gmailCountError?: boolean;
  gmailCountResponse?: Promise<Response>;
  run?: boolean;
  resource?: Partial<ReturnType<typeof gmailThread>>;
  resultKind?: string;
  status?: string;
  taskBatchSizes?: number[];
  taskTitles?: Array<string | null>;
  taskRefreshBatchSize?: number;
  taskRefreshError?: boolean;
  taskRefreshResponse?: Promise<Response>;
  taskDues?: Array<string | null>;
  taskError?: boolean;
  taskListResponse?: Promise<Response>;
  taskMetadata?: Record<string, unknown>;
  completedTaskResponses?: Array<{
    items: Record<string, unknown>[];
    nextPageToken?: string | null;
  }>;
  completedTaskErrors?: boolean[];
  completedTaskResponse?: Promise<Response>;
  twoItems?: boolean;
} = {}): Array<{ path: string; init?: RequestInit }> {
  const requests: Array<{ path: string; init?: RequestInit }> = [];
  let calendarResponseIndex = 0;
  let detailAttempts = 0;
  let actionStatus = options.actionStatus ?? "PROPOSED";
  let firstTaskPageRequests = 0;
  let completedTaskResponseIndex = 0;
  globalThis.fetch = vi.fn(async (input: string | URL, init?: RequestInit) => {
    const path = String(input);
    requests.push({ path, init });
    if (path === "/health/live") return jsonFetchResponse(liveResponse());
    if (path === "/health/ready") return jsonFetchResponse(readyResponse());
    if (path === "/api/v1/runtime") return jsonFetchResponse({ summary: runtimeSummary(options.run === false ? [] : ["run-1"], { llm: {} }), api_contract_version: "1" });
    if (path === "/api/v1/google/connection") return jsonFetchResponse(googleConnection());
    if (path === "/api/v1/identity/google-account") return jsonFetchResponse({ account: options.accountAbsent ? null : currentAccount(), api_contract_version: "1" });
    if (path === "/api/v1/settings") return jsonFetchResponse({ settings: settingsPayload(), api_contract_version: "1" });
    if (path.startsWith("/api/v1/conversations?")) {
      return jsonFetchResponse({ items: options.conversations ? [{ id: "conversation-1", account_id: "account-1", title: "업무 대화", updated_at_ms: 1, created_at_ms: 1 }] : [], next_cursor: null, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail/") && !path.includes("?") && !path.endsWith("/count")) {
      detailAttempts += 1;
      if (options.detailErrorOnce && detailAttempts === 1) {
        return jsonFetchResponse({
          error_code: "UPSTREAM_UNAVAILABLE",
          user_message: "메일 내용을 불러오지 못했습니다.",
          retryable: true,
          request_id: "request-1",
          api_contract_version: "1",
        }, 502);
      }
      const resourceId = decodeURIComponent(path.split("/").at(-1) ?? "resource-1");
      const metadata: Record<string, unknown> = options.resource?.metadata ?? {};
      return jsonFetchResponse({
        ...gmailDetail(resourceId, {
          subject: typeof metadata.subject === "string"
            ? metadata.subject
            : options.resource?.title ?? (resourceId === "resource-2" ? "두 번째 자료" : "첫 번째 자료"),
          sender_name: typeof metadata.sender_name === "string"
            ? metadata.sender_name
            : typeof metadata.sender === "string" ? metadata.sender : "김대리",
          sender_email: typeof metadata.sender_email === "string" ? metadata.sender_email : "kim@example.com",
          received_at: typeof metadata.received_at === "string" ? metadata.received_at : "Mon, 10 Aug 2026 09:15:00 +0900",
        }),
        ...options.detail,
      });
    }
    if (path === "/api/v1/resources/gmail/count") {
      if (options.gmailCountResponse) return options.gmailCountResponse;
      if (options.gmailCountError) {
        return jsonFetchResponse({
          error_code: "UPSTREAM_UNAVAILABLE",
          user_message: "메일 수를 불러오지 못했습니다.",
          retryable: true,
          request_id: "request-1",
          api_contract_version: "1",
        }, 504);
      }
      return jsonFetchResponse({ source: "gmail", total_count: options.gmailCount ?? 2, api_contract_version: "1" });
    }
    if (path === "/api/v1/resources/tasks/count") {
      return jsonFetchResponse({ source: "tasks", total_count: 1, api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/gmail")) {
      const gmailPageToken = new URL(`http://local${path}`).searchParams.get("page_token") ?? "first";
      if (options.gmailPageResponses?.[gmailPageToken]) return options.gmailPageResponses[gmailPageToken];
      if (options.gmailListResponse) {
        return options.gmailListResponse;
      }
      if (options.gmailBatch) {
        if (options.gmailCount) {
          const pageToken = path.match(/page_token=page-(\d+)/);
          const pageNumber = pageToken ? Number(pageToken[1]) : 1;
          const start = (pageNumber - 1) * 20;
          const items = Array.from({ length: 20 }, (_, index) => ({
            ...gmailThread(),
            resource_id: `resource-${start + index + 1}`,
            title: `자료 ${start + index + 1}`,
          }));
          return jsonFetchResponse({
            source: "gmail",
            items,
            next_page_token: pageNumber * 20 < options.gmailCount ? `page-${pageNumber + 1}` : null,
            api_contract_version: "1",
          });
        }
        const items = path.includes("page_token=page-2")
          ? [{ ...gmailThread(), resource_id: "resource-101", title: "두 번째 batch 자료" }]
          : Array.from({ length: 20 }, (_, index) => ({
              ...gmailThread(),
              resource_id: `resource-${index + 1}`,
              title: `자료 ${index + 1}`,
            }));
        return jsonFetchResponse({
          source: "gmail",
          items,
          next_page_token: path.includes("page_token=page-2") ? null : "page-2",
          api_contract_version: "1",
        });
      }
      const items = options.empty ? [] : path.includes("page_token=page-2")
        ? [{ ...gmailThread(), resource_id: "resource-2", title: "두 번째 자료" }]
        : [
            { ...gmailThread(), ...options.resource, resource_id: "resource-1", title: options.resource?.title ?? "첫 번째 자료" },
            ...(options.twoItems ? [{ ...gmailThread(), resource_id: "resource-2", title: "두 번째 자료" }] : []),
          ];
      return jsonFetchResponse({ source: "gmail", items, next_page_token: options.empty || options.twoItems || path.includes("page_token=page-2") ? null : "page-2", api_contract_version: "1" });
    }
    if (path.startsWith("/api/v1/resources/tasks")) {
      if (path.includes("status_scope=completed")) {
        const responseIndex = completedTaskResponseIndex++;
        if (options.completedTaskErrors?.[responseIndex]) throw new Error("completed tasks unavailable");
        if (options.completedTaskResponse && responseIndex === 0) return options.completedTaskResponse;
        const response = options.completedTaskResponses?.[responseIndex] ?? { items: [], nextPageToken: null };
        return jsonFetchResponse({ source: "tasks", items: response.items, next_page_token: response.nextPageToken ?? null, api_contract_version: "1" });
      }
      if (options.taskListResponse) return options.taskListResponse;
      if (options.taskError) {
        return jsonFetchResponse({
          error_code: "INVALID_ARGUMENT",
          user_message: "요청이 올바르지 않습니다.",
          retryable: false,
          request_id: "request-1",
          api_contract_version: "1",
        }, 422);
      }
      const pageToken = new URL(`http://local${path}`).searchParams.get("page_token");
      if (pageToken === null) firstTaskPageRequests += 1;
      if (pageToken === null && firstTaskPageRequests > 1 && options.taskRefreshResponse) {
        return options.taskRefreshResponse;
      }
      if (options.taskRefreshError && pageToken === null && firstTaskPageRequests > 1) {
        return jsonFetchResponse({
          error_code: "UPSTREAM_UNAVAILABLE",
          user_message: "태스크를 불러오지 못했습니다.",
          retryable: true,
          request_id: "request-1",
          api_contract_version: "1",
        }, 502);
      }
      const batchIndex = pageToken === null ? 0 : Number(pageToken.replace("tasks-page-", "")) - 1;
      const batchSizes = options.taskBatchSizes ?? [1];
      const start = batchSizes.slice(0, batchIndex).reduce((sum, size) => sum + size, 0);
      const size = pageToken === null && firstTaskPageRequests > 1 && options.taskRefreshBatchSize !== undefined
        ? options.taskRefreshBatchSize
        : batchSizes[batchIndex] ?? 0;
      return jsonFetchResponse({
        source: "tasks",
        items: Array.from({ length: size }, (_, index) => ({
          source: "tasks",
          resource_type: "task",
          resource_id: `task-${start + index + 1}`,
          parent_id: "task-list-default",
          title: options.taskTitles && start + index < options.taskTitles.length
            ? options.taskTitles[start + index]
            : (options.taskBatchSizes ? `할 일 ${start + index + 1}` : "후속 조치"),
          subtitle: null,
          link_url: null,
          version: "1",
          related_resource_ids: ["task-list-default"],
          metadata: options.taskMetadata ?? {
            task_status: "incomplete",
            scheduled_date: options.taskDues && start + index < options.taskDues.length
              ? options.taskDues[start + index]
              : "2026-08-12",
          },
        })),
        next_page_token: batchIndex + 1 < batchSizes.length ? `tasks-page-${batchIndex + 2}` : null,
        api_contract_version: "1",
      });
    }
    if (path.startsWith("/api/v1/resources/calendar")) {
      if (options.calendarListResponse) return options.calendarListResponse;
      if (options.calendarResponseForPath) return options.calendarResponseForPath(path);
      const calendarPageResponse = options.calendarPageResponses?.[calendarResponseIndex];
      calendarResponseIndex += 1;
      if (calendarPageResponse) return calendarPageResponse;
      return jsonFetchResponse(calendarEventResponse(options.calendarEvents));
    }
    if (path === "/api/v1/conversations" && init?.method === "POST") return jsonFetchResponse({ conversation_id: "conversation-1" });
    if (path === "/api/v1/runs" && init?.method === "POST") return jsonFetchResponse({ applied: true, result_code: "ACCEPTED", run_id: "run-1", conversation_id: "conversation-1", run_status: "WAITING_APPROVAL", run_version: 1, user_message_id: "message-1", workflow_key: "workflow-1", enqueued: true, request_replayed: false });
    if (path === "/api/v1/runs/run-1") return jsonFetchResponse(snapshotPayload({ status: options.status ?? "WAITING_APPROVAL", result_kind: options.resultKind, actions: options.action ? [{ action_id: "action-1", tool_name: "gmail_draft", status: actionStatus, version: 7, effect_type: "CREATE", approval_required: true, verification_policy: "GET_COMPARE", risk: options.actionRisk ?? {}, next_allowed_commands: [] }] : [] }));
    if (path === "/api/v1/runs/run-1/context") return jsonFetchResponse({ context: null, api_contract_version: "1" });
    if (path.includes("/api/v1/actions/") && init?.method === "POST") {
      actionStatus = path.endsWith("/reject") ? "REJECTED" : "APPROVED";
      return jsonFetchResponse({ applied: true, result_code: "OK", action_id: "action-1", action_status: actionStatus, action_version: 8, next_allowed_commands: [] });
    }
    throw new Error(`Unhandled path ${path}`);
  }) as typeof fetch;
  return requests;
}

function calendarEventResponse(
  items = [calendarEventItem()],
  nextPageToken: string | null = null,
): Record<string, unknown> {
  return {
    source: "calendar",
    items,
    next_page_token: nextPageToken,
    api_contract_version: "1",
  };
}

function calendarEventItem(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const metadata = overrides.metadata as Record<string, unknown> | undefined;
  return {
    source: "calendar",
    resource_type: "calendar_event",
    resource_id: "event-1",
    parent_id: "primary",
    title: "프로젝트 검토",
    subtitle: "2026-08-10T09:00:00+09:00",
    link_url: "https://calendar.google.com/",
    version: "1",
    related_resource_ids: ["primary"],
    metadata: {
      start: "2026-08-10T09:00:00+09:00",
      end: "2026-08-10T10:00:00+09:00",
      ...metadata,
    },
    ...overrides,
  };
}

function installFetch(handler: (path: string, init?: RequestInit) => MockResponse): void {
  globalThis.fetch = vi.fn(async (input: string | URL, init?: RequestInit) => {
    const response = handler(String(input), init);
    return new Response(JSON.stringify(response.json ?? {}), {
      status: response.status ?? 200,
      headers: {
        "Content-Type": "application/json",
        ...(response.headers ?? {}),
      },
    });
  }) as typeof fetch;
}

function jsonResponse(json: unknown, status = 200): MockResponse {
  return { status, json };
}

function jsonFetchResponse(json: unknown, status = 200): Response {
  return new Response(JSON.stringify(json), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function gmailPageResponse(pageNumber: number, totalCount: number): Response {
  const start = (pageNumber - 1) * 20;
  return jsonFetchResponse({
    source: "gmail",
    items: Array.from({ length: 20 }, (_, index) => ({
      ...gmailThread(),
      resource_id: `resource-${start + index + 1}`,
      title: `자료 ${start + index + 1}`,
    })),
    next_page_token: pageNumber * 20 < totalCount ? `page-${pageNumber + 1}` : null,
    api_contract_version: "1",
  });
}

function taskListResponse(count: number, start = 1): Response {
  return jsonFetchResponse({
    source: "tasks",
    items: Array.from({ length: count }, (_, index) => ({
      source: "tasks",
      resource_type: "task",
      resource_id: `task-${start + index}`,
      parent_id: "task-list-default",
      title: `할 일 ${start + index}`,
      subtitle: null,
      link_url: null,
      version: "1",
      related_resource_ids: ["task-list-default"],
      metadata: { task_status: "incomplete", scheduled_date: "2026-08-12" },
    })),
    next_page_token: null,
    api_contract_version: "1",
  });
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void; reject: (reason?: unknown) => void } {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  return {
    promise: new Promise<T>((next, fail) => {
      resolve = next;
      reject = fail;
    }),
    resolve,
    reject,
  };
}

function liveResponse() {
  return {
    status: "LIVE",
    service_instance_id: "svc-1",
    release_version: "test",
    api_contract_version: "1",
    occurred_at_ms: 1,
  };
}

function readyResponse() {
  return {
    status: "READY",
    checks: [{ name: "sqlite", state: "READY" }],
    release_version: "test",
    api_contract_version: "1",
    occurred_at_ms: 2,
  };
}

function runtimeSummary(openRunIds: string[], overrides: Record<string, unknown> = {}) {
  return {
    google: "CONNECTED",
    mcp: "READY",
    api_llm: "NOT_CONFIGURED",
    ollama: "NOT_AVAILABLE",
    deployment_profile: "test",
    recovery_required_run_ids: [],
    open_run_ids: openRunIds,
    ...overrides,
  };
}

function settingsPayload(overrides: Record<string, unknown> = {}) {
  return {
    config_schema_version: 1,
    deployment_profile: "LOCAL_CAPABLE",
    requested_runtime_mode: "API_LLM",
    default_calendar_id: null,
    default_tasklist_id: null,
    timezone: "Asia/Seoul",
    work_hours: { days: [0, 1, 2, 3, 4], start: "09:00", end: "18:00" },
    approval_ttl_minutes: 30,
    run_retention_days: 30,
    external_llm_consent: false,
    ollama_endpoint: "http://127.0.0.1:11434",
    approved_model_id: "approved-model",
    log_level: "INFO",
    ...overrides,
  };
}

function llmConnectionPayload(overrides: Record<string, unknown> = {}) {
  return {
    build_profile: "LOCAL_CAPABLE",
    requested_mode: "API_LLM",
    available_modes: ["API_LLM", "LOCAL_GPU", "AUTO"],
    actual_runtime: null,
    external_llm_consent: false,
    api_provider: {
      credential_state: "MISSING",
      availability: "NOT_CONFIGURED",
      last_probe: 1,
      safe_error_code: null,
    },
    ollama: {
      visible: true,
      availability: "AVAILABLE",
      version: "0.3.0",
      endpoint_state: "CONFIGURED",
      approved_model_state: "APPROVED",
      hardware_capability: {
        cpu_arch: "x86_64",
        core_summary: "8",
        memory_bytes: 17179869184,
        gpu_present: true,
        gpu_vendor: "NVIDIA",
        gpu_name: "Test GPU",
        gpu_memory_bytes: 8589934592,
        capability_status: "VALIDATED",
        safe_reason_codes: [],
      },
      last_probe: 1,
      safe_error_code: null,
    },
    ...overrides,
  };
}

function googleConnection() {
  return {
    connected: true,
    credential_state: "CONNECTED",
    account_email: "user@example.com",
    display_name: "User",
    granted_scopes: ["gmail.readonly"],
    missing_scopes: [],
    reauth_required: false,
    oauth_environment: "DEVELOPMENT",
    last_checked_at_ms: 3,
    api_contract_version: "1",
  };
}

function currentAccount() {
  return {
    account_id: "account-1",
    email: "user@example.com",
    display_name: "User",
  };
}

function gmailThread() {
  return {
    source: "gmail",
    resource_type: "gmail_thread",
    resource_id: "thread-project",
    parent_id: null,
    title: "Project sync follow-up",
    subtitle: "Need a draft for the Thursday recap.",
    link_url: "https://mail.google.com/mail/u/0/#inbox/thread-project",
    version: "3",
    related_resource_ids: [],
    metadata: {},
  };
}

function gmailDetail(resourceId = "thread-project", overrides: Record<string, unknown> = {}) {
  return {
    resource_id: resourceId,
    message_id: "message-project-2",
    sender_name: "김대리",
    sender_email: "kim@example.com",
    recipients: ["user@example.com"],
    cc: [],
    subject: "Project sync follow-up",
    received_at: "Mon, 10 Aug 2026 09:15:00 +0900",
    body: "실제 메일 본문입니다.",
    attachments: [],
    canonical_url: `https://mail.google.com/mail/u/0/#inbox/${resourceId}`,
    api_contract_version: "1",
    ...overrides,
  };
}

function snapshotPayload(overrides: Partial<SnapshotShape>) {
  const snapshot = {
    ...defaultSnapshot(),
    ...overrides,
  };
  return {
    snapshot: {
      ...snapshot,
      actions: snapshot.actions.map((action) => ({ ...action, risk: action.risk ?? {} })),
    },
    api_contract_version: "1",
  };
}

function defaultSnapshot(): SnapshotShape {
  return {
    run_id: "run-1",
    conversation_id: "conversation-1",
    status: "WAITING_APPROVAL",
    version: 1,
    entry_mode: "AGENT_SEARCH",
    requested_mode: "AUTO",
    actual_runtime: "API_LLM",
    started_at_ms: 1,
    finished_at_ms: null,
    active_plan: {
      plan_id: "plan-1",
      revision_no: 1,
      status: "WAITING_APPROVAL",
      summary_text: "Create follow-up tasks",
      created_at_ms: 1,
    },
    actions: [],
    approvals: [],
    execution_status: { action_count: 1, terminal_action_count: 0 },
    verification_summary: { verified_count: 0, mismatch_count: 0 },
    recovery_summary: { unknown_result_action_count: 0 },
    next_allowed_commands: ["RESUME", "REQUEST_CANCEL"],
    snapshot_version: 1,
  };
}
