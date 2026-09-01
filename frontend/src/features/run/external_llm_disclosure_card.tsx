import type { ExternalLlmTransferScope } from "../../api/contract";

const DATA_CLASS_LABELS: Record<ExternalLlmTransferScope["data_classes"][number], string> = {
  USER_REQUEST: "사용자 요청",
  RESOURCE_METADATA: "자료 메타데이터",
  EVIDENCE_EXCERPT: "선택 근거 일부",
  PLAN_CONTEXT: "업무 계획 컨텍스트",
};

export function ExternalLlmDisclosureCard({ scope }: { scope: ExternalLlmTransferScope }): JSX.Element {
  return (
    <article className="info-card" aria-label="외부 LLM 전송 범위">
      <strong>외부 API LLM 전송 안내</strong>
      <p>이 Run의 추론을 위해 아래 범위가 외부 LLM Provider로 전송될 수 있습니다.</p>
      <dl className="metadata-list">
        <div><dt>자료 출처</dt><dd>{scope.source_kinds.join(", ")}</dd></div>
        <div><dt>전송 데이터</dt><dd>{scope.data_classes.map((item) => DATA_CLASS_LABELS[item]).join(", ")}</dd></div>
        <div><dt>목적</dt><dd>현재 요청의 분석·계획·응답 생성</dd></div>
        <div><dt>범위 revision</dt><dd>{scope.scope_revision}</dd></div>
      </dl>
    </article>
  );
}
