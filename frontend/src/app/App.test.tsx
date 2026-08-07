import { render, screen, waitFor } from "@testing-library/react";
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

test("boots from fragment and clears the bootstrap secret", async () => {
  window.history.replaceState(null, "", "/#bootstrap_secret=secret-1&service_instance_id=svc-1");
  installFetch((path) => {
    if (path === "/health/live") {
      return jsonResponse({ status: "LIVE", service_instance_id: "svc-1", release_version: "test", api_contract_version: "1", occurred_at_ms: 1 });
    }
    if (path === "/health/ready") {
      return jsonResponse({ status: "READY", checks: [{ name: "sqlite", state: "READY" }], release_version: "test", api_contract_version: "1", occurred_at_ms: 2 });
    }
    if (path === "/api/v1/session/bootstrap") {
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

  await screen.findByText("Google 연결됨");
  expect(window.location.hash).toBe("");
  expect(document.body.textContent).not.toContain("secret-1");
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

  const selectButton = await screen.findByRole("button", { name: "선택" });
  await user.click(selectButton);
  await user.click(screen.getByRole("button", { name: "채팅에 추가" }));

  await waitFor(() =>
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/runs",
      expect.objectContaining({ method: "POST" }),
    ),
  );
  const startRunCall = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.find(
    ([path]) => path === "/api/v1/runs",
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

test("reloads snapshot when snapshot_required is emitted", async () => {
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
});

test("starts Google OAuth from settings when disconnected", async () => {
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
    if (path === "/api/v1/google/oauth/start" && init?.method === "POST") {
      return jsonResponse({
        flow_id: "flow-1",
        authorization_url: "https://accounts.google.com/o/oauth2/v2/auth?flow=1",
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

  await screen.findByText("Google 미연결");
  await user.click(screen.getByRole("button", { name: "설정" }));
  await user.click(screen.getByRole("button", { name: "Google 로그인" }));

  expect(window.open).toHaveBeenCalledWith(
    "https://accounts.google.com/o/oauth2/v2/auth?flow=1",
    "_blank",
    "noopener,noreferrer",
  );
  expect(await screen.findByText("Google 연결 완료를 기다리고 있습니다.")).toBeInTheDocument();
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

  await screen.findByRole("button", { name: "선택" });
  await user.click(screen.getByRole("button", { name: "설정" }));
  await user.click(screen.getByRole("button", { name: "연결 해제" }));

  await screen.findByText("Google 미연결");
  expect(screen.queryByRole("button", { name: "선택" })).not.toBeInTheDocument();
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

  await user.click(await screen.findByRole("button", { name: "원본 열기" }));
  expect(window.open).toHaveBeenCalledWith(
    "https://calendar.google.com/",
    "_blank",
    "noopener,noreferrer",
  );
});

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

function runtimeSummary(openRunIds: string[]) {
  return {
    google: "CONNECTED",
    mcp: "READY",
    api_llm: "NOT_CONFIGURED",
    ollama: "NOT_AVAILABLE",
    deployment_profile: "test",
    recovery_required_run_ids: [],
    open_run_ids: openRunIds,
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

function snapshotPayload(overrides: Partial<SnapshotShape>) {
  return {
    snapshot: {
      ...defaultSnapshot(),
      ...overrides,
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
    next_allowed_commands: ["RESUME", "CANCEL"],
    snapshot_version: 1,
  };
}
