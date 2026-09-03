import { useState } from "react";
import type { ExternalLlmTransferScope } from "../../api/contract";

const DISMISS_KEY = "gwa.external-llm-disclosure.dismissed";

export function ExternalLlmDisclosureCard({ scope }: { scope: ExternalLlmTransferScope }): JSX.Element {
  const [dismissed, setDismissed] = useState(() => (
    typeof window !== "undefined" && window.localStorage.getItem(DISMISS_KEY) === "true"
  ));
  if (dismissed) return <></>;

  const dismiss = (): void => {
    window.localStorage.setItem(DISMISS_KEY, "true");
    setDismissed(true);
  };

  return (
    <article className="llm-disclosure-snackbar" role="status" aria-label="외부 LLM 전송 안내" data-scope-revision={scope.scope_revision}>
      <div>
        <strong>외부 API LLM 전송 안내</strong>
        <p>이 Run의 추론을 위해 아래 범위가 외부 LLM Provider로 전송될 수 있습니다.</p>
      </div>
      <button type="button" onClick={dismiss}>다시 보지 않음</button>
    </article>
  );
}
