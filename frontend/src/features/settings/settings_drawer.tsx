import { useCallback, useEffect, useRef, useState } from "react";
import { ApiClientError } from "../../api/client";
import { DiagnosticsPanel, type RuntimeSummary } from "../diagnostics";
import { listCalendars, listTaskLists } from "../resource_browser/api/list_resources";
import type { CalendarContainer, TaskListContainer } from "../../api/contract";
import { disconnectGoogle, getGoogleConnection, startGoogleConnection, type GoogleConnection } from "./api/google_connection_operations";
import { getSettings, type SettingsView } from "./api/get_settings";
import { deleteLlmCredential, getLlmCredentialStatus, storeLlmCredential, type LlmCredentialStatus } from "./api/llm_credential_operations";
import { updateRuntimeMode, type RuntimeMode } from "./api/update_runtime_mode";
import { updateSettings } from "./api/update_settings";

const OLLAMA_WINDOWS_INSTALL_GUIDE_URL = "https://ollama.com/download/windows";

const runtimeModeLabels: Record<RuntimeMode, string> = {
  AUTO: "자동 선택", LOCAL_GPU: "로컬 GPU", API_LLM: "외부 API 모델",
};
const googleConnectionLabels: Record<GoogleConnection["connection_status"], string> = {
  CONNECTING: "연결 중", CONNECTED: "연결됨", DISCONNECTED: "연결되지 않음",
  REAUTH_REQUIRED: "다시 로그인해야 합니다", UNAVAILABLE: "연결 상태를 확인할 수 없습니다",
};
const credentialValidationLabels: Record<LlmCredentialStatus["validation_status"], string> = {
  VALID: "확인됨", INVALID: "키를 확인해 주세요", UNAVAILABLE: "확인할 수 없음",
  NOT_CONFIGURED: "설정되지 않음",
};

function runtimeModeLabel(mode: string | null | undefined): string {
  if (mode === "MIXED") return "로컬·외부 모델 함께 사용";
  return mode && mode in runtimeModeLabels ? runtimeModeLabels[mode as RuntimeMode] : "확인 중";
}

type Props = {
  runtime: RuntimeSummary | null;
  theme: string;
  onThemeChange: (theme: string) => void;
  onClose: () => void;
  onOperationalStateChanged: () => Promise<void>;
};

export function SettingsDrawer({ runtime, theme, onThemeChange, onClose, onOperationalStateChanged }: Props): JSX.Element {
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [google, setGoogle] = useState<GoogleConnection | null>(null);
  const [credential, setCredential] = useState<LlmCredentialStatus | null>(null);
  const [taskLists, setTaskLists] = useState<TaskListContainer[]>([]);
  const [calendars, setCalendars] = useState<CalendarContainer[]>([]);
  const [apiKey, setApiKey] = useState("");
  const [storageMode, setStorageMode] = useState<"KEYRING" | "SESSION_ONLY">("KEYRING");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const commandIds = useRef(new Map<string, string>());

  const load = useCallback(async (): Promise<void> => {
    const [nextSettings, nextGoogle, nextCredential, nextTaskLists, nextCalendars] = await Promise.allSettled([
      getSettings(), getGoogleConnection(), getLlmCredentialStatus(), listTaskLists(), listCalendars(),
    ]);
    if (nextSettings.status === "fulfilled") setSettings(nextSettings.value);
    if (nextGoogle.status === "fulfilled") setGoogle(nextGoogle.value);
    if (nextCredential.status === "fulfilled") setCredential(nextCredential.value);
    if (nextTaskLists.status === "fulfilled") setTaskLists(nextTaskLists.value.items);
    if (nextCalendars.status === "fulfilled") setCalendars(nextCalendars.value.items);
    if ([nextSettings, nextGoogle, nextCredential, nextTaskLists, nextCalendars].every((result) => result.status === "rejected")) {
      throw nextSettings.status === "rejected" ? nextSettings.reason : new Error("Settings unavailable");
    }
  }, []);

  useEffect(() => {
    void load().catch((error: unknown) => setMessage(errorMessage(error, "설정 정보를 불러오지 못했습니다.")));
  }, [load]);

  function commandIdFor(operation: string): string {
    let commandId = commandIds.current.get(operation);
    if (!commandId) {
      commandId = crypto.randomUUID();
      commandIds.current.set(operation, commandId);
    }
    return commandId;
  }

  async function run(operation: string, action: (commandId: string) => Promise<void>, success: string, clearSecret = false): Promise<void> {
    setBusy(true);
    setMessage(null);
    try {
      await action(commandIdFor(operation));
      commandIds.current.delete(operation);
      await Promise.all([load(), onOperationalStateChanged()]);
      setMessage(success);
    } catch (error) {
      await Promise.allSettled([load(), onOperationalStateChanged()]);
      setMessage(errorMessage(error, "작업을 완료하지 못했습니다."));
    } finally {
      if (clearSecret) setApiKey("");
      setBusy(false);
    }
  }

  async function saveSettings(): Promise<void> {
    if (!settings) return;
    await run("settings:update", async (commandId) => {
      const updated = await updateSettings(commandId, {
        timezone: settings.timezone,
        default_calendar_id: settings.default_calendar_id,
        default_tasklist_id: settings.default_tasklist_id,
        preferred_llm_mode: settings.preferred_llm_mode,
        external_llm_consent: settings.external_llm_consent,
        retention_days: settings.retention_days,
        working_day_start_local: settings.working_day_start_local,
        working_day_end_local: settings.working_day_end_local,
        include_weekends: settings.include_weekends,
        calendar_buffer_minutes: settings.calendar_buffer_minutes,
      });
      setSettings(updated);
    }, "설정을 저장했습니다.");
  }

  function patch<K extends keyof SettingsView>(key: K, value: SettingsView[K]): void {
    setSettings((current) => current ? { ...current, [key]: value } : current);
  }

  function close(): void {
    setApiKey("");
    onClose();
  }

  const runtimeModes = availableRuntimeModes(runtime?.deployment_profile);
  const productLocalModels = runtime?.local_models?.filter((model) => model.selected) ?? [];
  const isLocalReady = productLocalModels.length > 0
    && productLocalModels.every((model) => model.installed && model.approved);

  return (
    <aside className="drawer" aria-label="설정 및 진단">
      <div className="panel-header"><strong>설정·진단</strong><button className="button-secondary" type="button" onClick={close}>닫기</button></div>
      <div className="panel-body">
        {message ? <p role="status" className="status-warn">{message}</p> : null}
        <section className="info-card"><strong>표시</strong><div className="button-row"><button type="button" className={theme === "light" ? "button-primary" : "button-secondary"} onClick={() => onThemeChange("light")}>밝게</button><button type="button" className={theme === "dark" ? "button-primary" : "button-secondary"} onClick={() => onThemeChange("dark")}>어둡게</button></div></section>
        <section className="info-card" aria-label="Google 연결">
          <strong>Google</strong><p>{google?.connection_status === "CONNECTED" ? google.display_email : google ? googleConnectionLabels[google.connection_status] : "확인 중"}</p>
          {google?.missing_required_scopes.length ? <p className="status-warn">추가로 필요한 권한: {google.missing_required_scopes.join(", ")}</p> : null}
          <div className="button-row">
            {google?.connection_status !== "CONNECTED" ? <button type="button" className="button-primary" disabled={busy} onClick={() => void run("google:connect", async (id) => { const result = await startGoogleConnection(id); window.open(requireOAuthUrl(result.authorization_url), "_blank", "noopener,noreferrer"); }, "Google 연결 완료를 기다리고 있습니다.")}>연결</button> : null}
            {google?.connection_status === "CONNECTED" ? <button type="button" className="button-danger" disabled={busy} onClick={() => void run("google:disconnect", async (id) => { await disconnectGoogle(id); }, "Google 연결을 해제했습니다.")}>연결 해제</button> : null}
          </div>
        </section>
        {settings ? <section className="info-card" aria-label="작업 설정">
          <strong>작업 설정</strong>
          <label>시간대<input value={settings.timezone} onChange={(e) => patch("timezone", e.target.value)} /></label>
          <label>기본 캘린더<select value={settings.default_calendar_id ?? ""} onChange={(e) => patch("default_calendar_id", e.target.value || null)}><option value="">선택</option>{calendars.map((item) => <option key={item.calendar_id} value={item.calendar_id}>{item.title}{item.primary ? " (기본)" : ""}</option>)}</select></label>
          <label>기본 태스크 목록<select value={settings.default_tasklist_id ?? ""} onChange={(e) => patch("default_tasklist_id", e.target.value || null)}><option value="">선택</option>{taskLists.map((item) => <option key={item.tasklist_id} value={item.tasklist_id}>{item.title}</option>)}</select></label>
          <label>업무 시작<input type="time" value={settings.working_day_start_local} onChange={(e) => patch("working_day_start_local", e.target.value)} /></label>
          <label>업무 종료<input type="time" value={settings.working_day_end_local} onChange={(e) => patch("working_day_end_local", e.target.value)} /></label>
          <label><input type="checkbox" checked={settings.include_weekends} onChange={(e) => patch("include_weekends", e.target.checked)} />주말 포함</label>
          <label>일정 사이 여유 시간(분)<input type="number" min="0" value={settings.calendar_buffer_minutes} onChange={(e) => patch("calendar_buffer_minutes", Number(e.target.value))} /></label>
          <label>보존 기간(일)<input type="number" min="1" value={settings.retention_days} onChange={(e) => patch("retention_days", Number(e.target.value))} /></label>
          <label>사용할 모델 실행 방식<select value={settings.preferred_llm_mode} onChange={(e) => patch("preferred_llm_mode", e.target.value as RuntimeMode)}>{runtimeModes.map((mode) => <option key={mode} value={mode}>{runtimeModeLabels[mode]}</option>)}</select></label>
          <label><input type="checkbox" checked={settings.external_llm_consent} onChange={(e) => patch("external_llm_consent", e.target.checked)} />외부 LLM 사용 동의</label>
          <button type="button" className="button-primary" disabled={busy} onClick={() => void saveSettings()}>LLM 설정 저장</button>
        </section> : null}
        <section className="info-card" aria-label="런타임 모드">
          <strong>런타임 모드</strong><p>요청 {runtimeModeLabel(runtime?.runtime_mode.requested_mode)} · 실제 {runtimeModeLabel(runtime?.runtime_mode.actual_runtime)}</p>{runtime?.runtime_mode.fallback_reason ? <p className="status-warn">요청한 실행 방식 대신 사용 가능한 방식으로 전환되었습니다.</p> : null}
          <div className="button-row">{runtimeModes.map((mode) => <button key={mode} type="button" className="button-secondary" disabled={busy} onClick={() => void run(`runtime:${mode}`, async (id) => { await updateRuntimeMode(id, mode); }, `${runtimeModeLabels[mode]} 방식을 요청했습니다.`)}>{runtimeModeLabels[mode]}</button>)}</div>
        </section>
        {runtime?.deployment_profile === "LOCAL_CAPABLE" ? <section className="info-card" aria-label="로컬 AI 준비">
          <strong>로컬 AI</strong>
          <p>{isLocalReady ? "제품 로컬 AI가 준비되었습니다." : "Ollama와 제품 로컬 AI 모델 준비가 필요합니다."}</p>
          {productLocalModels.length ? <ul>{productLocalModels.map((model) => <li key={model.model_id}>{model.model_id} · {model.installed && model.approved ? "준비됨" : "준비 필요"}</li>)}</ul> : <p className="muted">제품 모델 상태를 확인하고 있습니다.</p>}
          <div className="button-row">
            <a className="button-secondary" href={OLLAMA_WINDOWS_INSTALL_GUIDE_URL} target="_blank" rel="noreferrer">Ollama 설치 안내 열기</a>
            <button type="button" className="button-secondary" disabled={busy} onClick={() => void onOperationalStateChanged()}>다시 검사</button>
          </div>
        </section> : null}
        <section className="info-card" aria-label="LLM 자격증명">
          <strong>LLM 자격증명</strong><p>{credential?.configured ? `${credential.storage_mode === "KEYRING" ? "PC에 안전하게 저장" : "이번 실행에서만 사용"} / ${credentialValidationLabels[credential.validation_status]}` : "설정되지 않음"}</p>
          <label>저장 방식<select value={storageMode} onChange={(e) => setStorageMode(e.target.value === "SESSION_ONLY" ? "SESSION_ONLY" : "KEYRING")}><option value="KEYRING">PC에 안전하게 저장</option><option value="SESSION_ONLY">이번 실행에서만 사용</option></select></label>
          <label>API 키<input type="password" autoComplete="off" placeholder="sk-..." value={apiKey} onChange={(e) => setApiKey(e.target.value)} /></label>
          <div className="button-row"><button type="button" className="button-primary" disabled={busy || !apiKey.trim()} onClick={() => void run("credential:store", async (id) => { await storeLlmCredential(id, apiKey, storageMode); }, "자격증명을 저장했습니다.", true)}>API 키 저장</button><button type="button" className="button-danger" disabled={busy} onClick={() => void run("credential:delete", async (id) => { await deleteLlmCredential(id); }, "자격증명을 삭제했습니다.", true)}>API 키 삭제</button><button type="button" className="button-secondary" disabled={busy} onClick={() => void load()}>연결 테스트</button></div>
        </section>
        <DiagnosticsPanel runtime={runtime} onRefresh={onOperationalStateChanged} />
      </div>
    </aside>
  );
}

function availableRuntimeModes(profile: string | undefined): RuntimeMode[] {
  return profile === "LOCAL_CAPABLE" ? ["AUTO", "LOCAL_GPU", "API_LLM"] : ["API_LLM"];
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiClientError ? error.message : fallback;
}

function requireOAuthUrl(value: string): string {
  const url = new URL(value);
  if (url.protocol !== "http:" || url.hostname !== "127.0.0.1" || !url.port || url.pathname !== "/oauth/authorize") throw new Error("Unexpected OAuth authorization URL");
  url.searchParams.set("return_to", new URL("/", window.location.origin).toString());
  return url.toString();
}
