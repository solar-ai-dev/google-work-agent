import type { StartupCheck } from "../../api/contract";

export type StartupCheckState = {
  phase: string;
  status: "idle" | "loading" | "ready" | "error";
  message: string;
  checks: StartupCheck[];
  error?: string;
};

type Props = {
  state: StartupCheckState;
  onRetry: () => void;
};

export function StartupCheckScreen({ state, onRetry }: Props): JSX.Element {
  return (
    <main className="startup">
      <section className="startup-card" aria-live="polite" aria-busy={state.status === "loading"}>
        <h1>Google Work Agent</h1>
        <p>{state.message}</p>
        {state.error ? <p className="status-bad" role="alert">{state.error}</p> : null}
        <ul className="card-list">
          {state.checks.map((check) => (
            <li key={check.name} className="info-card">
              <strong>{check.name}</strong>
              <div className="muted">{check.state}</div>
              {check.detail ? <div className="muted">{check.detail}</div> : null}
            </li>
          ))}
        </ul>
        {state.status === "error" ? (
          <div className="button-row">
            <button className="button-primary" type="button" onClick={onRetry}>
              다시 확인
            </button>
          </div>
        ) : null}
      </section>
    </main>
  );
}
