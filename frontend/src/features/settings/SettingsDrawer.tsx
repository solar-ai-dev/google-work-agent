import { useCallback, useEffect, useMemo, useState } from "react";
import {
  deleteLLMApiKey,
  getLLMConnection,
  getSettings,
  patchSettings,
  storeLLMApiKey,
} from "../../api";
import { ApiClientError } from "../../api/client";
import type { GoogleConnectionResponse, RuntimeSummary } from "../../api/contract";

type Props = {
  runtime: RuntimeSummary | null;
  google: GoogleConnectionResponse | null;
  theme: string;
  onThemeChange: (theme: string) => void;
  onClose: () => void;
  onConnect?: () => void;
  onDisconnect: () => void;
  onRuntimeRefresh: () => Promise<void>;
};

export function SettingsDrawer(props: Props): JSX.Element {
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [settingsError, setSettingsError] = useState<string | null>(null);
  const [settingsSavedMessage, setSettingsSavedMessage] = useState<string | null>(null);
  const [requestedRuntimeMode, setRequestedRuntimeMode] = useState("API_LLM");
  const [externalLLMConsent, setExternalLLMConsent] = useState(false);
  const [llmState, setLLMState] = useState<Record<string, unknown> | null>(null);
  const [llmStatusMessage, setLLMStatusMessage] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [storageMode, setStorageMode] = useState<"KEYRING" | "SESSION_ONLY">("KEYRING");

  const loadRuntimeSettings = useCallback(async (): Promise<void> => {
    setSettingsLoading(true);
    setSettingsError(null);
    try {
      const [settingsResponse, llmResponse] = await Promise.all([getSettings(), getLLMConnection()]);
      const settings = asRecord(settingsResponse);
      setRequestedRuntimeMode(String(settings.preferred_llm_mode ?? "AUTO"));
      setExternalLLMConsent(Boolean(settings.external_llm_consent));
      setLLMState(asRecord(llmResponse));
    } catch (error) {
      setSettingsError(error instanceof ApiClientError ? error.message : "설정 정보를 불러오지 못했습니다.");
    } finally {
      setSettingsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRuntimeSettings();
  }, [loadRuntimeSettings]);

  const llmSummary = useMemo(() => readRuntimeState(props.runtime), [props.runtime]);
  const connectionSummary = useMemo(() => readLLMState(llmState), [llmState]);

  async function handleSaveLLMSettings(): Promise<void> {
    setSettingsSavedMessage(null);
    setSettingsError(null);
    try {
      await patchSettings({
        command_id: `settings-${Date.now()}`,
        preferred_llm_mode: requestedRuntimeMode as "AUTO" | "LOCAL_GPU" | "API_LLM",
        external_llm_consent: externalLLMConsent,
      });
      await Promise.all([props.onRuntimeRefresh(), loadRuntimeSettings()]);
      setSettingsSavedMessage("LLM 설정을 저장했습니다.");
    } catch (error) {
      setSettingsError(error instanceof ApiClientError ? error.message : "설정을 저장하지 못했습니다.");
    }
  }

  async function handleStoreLLMApiKey(): Promise<void> {
    setLLMStatusMessage(null);
    setSettingsError(null);
    try {
      await storeLLMApiKey({ api_key: apiKey, storage_mode: storageMode });
      setApiKey("");
      await Promise.all([props.onRuntimeRefresh(), loadRuntimeSettings()]);
      setLLMStatusMessage("API 키를 저장했습니다.");
    } catch (error) {
      setSettingsError(error instanceof ApiClientError ? error.message : "API 키를 저장하지 못했습니다.");
    }
  }

  async function handleDeleteLLMApiKey(): Promise<void> {
    setLLMStatusMessage(null);
    setSettingsError(null);
    try {
      await deleteLLMApiKey();
      await Promise.all([props.onRuntimeRefresh(), loadRuntimeSettings()]);
      setLLMStatusMessage("API 키를 삭제했습니다.");
    } catch (error) {
      setSettingsError(error instanceof ApiClientError ? error.message : "API 키를 삭제하지 못했습니다.");
    }
  }

  async function handleTestLLMConnection(): Promise<void> {
    setLLMStatusMessage(null);
    setSettingsError(null);
    try {
      const response = await getLLMConnection();
      setLLMState(asRecord(response));
      await props.onRuntimeRefresh();
      setLLMStatusMessage("LLM 연결 상태를 다시 확인했습니다.");
    } catch (error) {
      setSettingsError(error instanceof ApiClientError ? error.message : "LLM 연결 테스트에 실패했습니다.");
    }
  }

  return (
    <aside className="drawer" aria-label="설정 및 진단">
      <div className="panel-header">
        <strong>설정·진단</strong>
        <button className="button-secondary" type="button" onClick={props.onClose}>닫기</button>
      </div>
      <div className="panel-body">
        <section className="info-card">
          <strong>일반</strong>
          <div className="button-row">
            <button className={props.theme === "light" ? "button-primary" : "button-secondary"} type="button" onClick={() => props.onThemeChange("light")}>Light</button>
            <button className={props.theme === "dark" ? "button-primary" : "button-secondary"} type="button" onClick={() => props.onThemeChange("dark")}>Dark</button>
          </div>
        </section>
        <section className="info-card">
          <strong>Google</strong>
          <p>{props.google?.connection_status === "CONNECTED" ? props.google.display_email : "연결되지 않음"}</p>
          <div className="button-row">
            {props.google?.connection_status !== "CONNECTED" && props.onConnect ? <button className="button-primary" type="button" onClick={props.onConnect}>Google 로그인</button> : null}
            {props.google?.connection_status === "CONNECTED" ? <button className="button-danger" type="button" onClick={props.onDisconnect}>연결 해제</button> : null}
          </div>
          {props.google?.missing_required_scopes.length ? <p className="status-warn">누락 Scope: {props.google.missing_required_scopes.join(", ")}</p> : null}
        </section>
        <section className="info-card">
          <strong>Runtime</strong>
          <div className="muted">Deployment {props.runtime?.deployment_profile ?? "-"}</div>
          <div className="muted">Google {props.runtime?.connectors[0]?.connection_status ?? "-"}</div>
          <div className="muted">API LLM {props.runtime?.llm_providers.find((item) => item.provider === "API_LLM")?.availability ?? "-"}</div>
          <div className="muted">Local GPU {props.runtime?.llm_providers.find((item) => item.provider === "LOCAL_GPU")?.availability ?? "-"}</div>
        </section>
        <section className="info-card">
          <strong>LLM</strong>
          {settingsLoading ? <p className="muted">설정을 불러오는 중입니다.</p> : null}
          {settingsError ? <p className="status-warn">{settingsError}</p> : null}
          {settingsSavedMessage ? <p className="muted">{settingsSavedMessage}</p> : null}
          {llmStatusMessage ? <p className="muted">{llmStatusMessage}</p> : null}
          <label style={{ display: "grid", gap: "0.35rem" }}>
            <span className="muted">Requested mode</span>
            <select value={requestedRuntimeMode} onChange={(event) => setRequestedRuntimeMode(event.target.value)} disabled={settingsLoading}>
              <option value="API_LLM">API_LLM</option><option value="AUTO">AUTO</option><option value="LOCAL_GPU">LOCAL_GPU</option>
            </select>
          </label>
          <label style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginTop: "0.75rem" }}>
            <input type="checkbox" checked={externalLLMConsent} onChange={(event) => setExternalLLMConsent(event.target.checked)} disabled={settingsLoading} />
            <span>외부 LLM 사용 동의</span>
          </label>
          <div className="button-row" style={{ marginTop: "0.75rem" }}>
            <button className="button-primary" type="button" onClick={() => void handleSaveLLMSettings()}>LLM 설정 저장</button>
            <button className="button-secondary" type="button" onClick={() => void handleTestLLMConnection()}>연결 테스트</button>
          </div>
          <div className="muted" style={{ marginTop: "0.75rem" }}>Build {llmSummary.buildProfile ?? "-"} / Actual {llmSummary.actualRuntime ?? "-"}</div>
          <div className="muted">Available {llmSummary.availableModes.join(", ") || "-"}</div>
          <div className="muted">API credential {connectionSummary.apiCredentialState ?? "-"} / API availability {connectionSummary.apiAvailability ?? "-"}</div>
          <div className="muted">Ollama {connectionSummary.ollamaAvailability ?? "-"} / Model {connectionSummary.approvedModelState ?? "-"}</div>
        </section>
        <section className="info-card">
          <strong>API Key</strong>
          <label style={{ display: "grid", gap: "0.35rem" }}>
            <span className="muted">Storage mode</span>
            <select value={storageMode} onChange={(event) => setStorageMode(event.target.value === "SESSION_ONLY" ? "SESSION_ONLY" : "KEYRING")}>
              <option value="KEYRING">KEYRING</option><option value="SESSION_ONLY">SESSION_ONLY</option>
            </select>
          </label>
          <label style={{ display: "grid", gap: "0.35rem", marginTop: "0.75rem" }}>
            <span className="muted">API key</span>
            <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-..." />
          </label>
          <div className="button-row" style={{ marginTop: "0.75rem" }}>
            <button className="button-primary" type="button" onClick={() => void handleStoreLLMApiKey()} disabled={!apiKey.trim()}>API 키 저장</button>
            <button className="button-secondary" type="button" onClick={() => void handleDeleteLLMApiKey()}>API 키 삭제</button>
          </div>
        </section>
      </div>
    </aside>
  );
}

function readLLMState(value: Record<string, unknown> | null | undefined): {
  buildProfile: string | null;
  actualRuntime: string | null;
  availableModes: string[];
  apiCredentialState: string | null;
  apiAvailability: string | null;
  ollamaAvailability: string | null;
  approvedModelState: string | null;
} {
  const llm = asRecord(value);
  const configured = llm.configured === true;
  return {
    buildProfile: null,
    actualRuntime: null,
    availableModes: [],
    apiCredentialState: configured ? "CONFIGURED" : "NOT_CONFIGURED",
    apiAvailability: typeof llm.validation_status === "string" ? llm.validation_status : null,
    ollamaAvailability: null,
    approvedModelState: null,
  };
}

function readRuntimeState(value: RuntimeSummary | null | undefined): ReturnType<typeof readLLMState> {
  const apiProvider = value?.llm_providers.find((item) => item.provider === "API_LLM");
  const localProvider = value?.llm_providers.find((item) => item.provider === "LOCAL_GPU");
  return {
    buildProfile: value?.deployment_profile ?? null,
    actualRuntime: value?.runtime_mode.actual_runtime ?? null,
    availableModes: value?.llm_providers
      .filter((item) => item.availability === "READY")
      .map((item) => item.provider) ?? [],
    apiCredentialState: apiProvider?.configured ? "CONFIGURED" : "NOT_CONFIGURED",
    apiAvailability: apiProvider?.availability ?? null,
    ollamaAvailability: localProvider?.availability ?? null,
    approvedModelState: localProvider?.model_id ?? null,
  };
}

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
