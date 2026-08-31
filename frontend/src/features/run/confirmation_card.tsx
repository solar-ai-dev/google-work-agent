import type { PendingInterrupt } from "../../api/contract";

export function ConfirmationCard({ interrupt, text, busy, onTextChange, onSubmit }: {
  interrupt: PendingInterrupt;
  text: string;
  busy: boolean;
  onTextChange: (value: string) => void;
  onSubmit: (selectedOption?: string) => void;
}): JSX.Element {
  return (
    <article className="info-card" aria-labelledby={`confirmation-${interrupt.interrupt_id}`}>
      <strong id={`confirmation-${interrupt.interrupt_id}`}>추가 확인</strong>
      <p>{interrupt.question}</p>
      {interrupt.response_mode === "OPTION" ? (
        <div className="button-row">
          {interrupt.options.map((option) => <button className="button-primary" type="button" key={option} disabled={busy} onClick={() => onSubmit(option)}>{option}</button>)}
        </div>
      ) : (
        <>
          <label htmlFor={`confirmation-answer-${interrupt.interrupt_id}`}>확인 응답</label>
          <textarea id={`confirmation-answer-${interrupt.interrupt_id}`} className="composer" maxLength={4000} disabled={busy} value={text} onChange={(event) => onTextChange(event.target.value)} />
          <button className="button-primary" type="button" disabled={busy || !text.trim()} onClick={() => onSubmit()}>응답 보내기</button>
        </>
      )}
    </article>
  );
}
