# 00-C. 핵심 정책·안전 불변조건 요약

> 요약 문서다. 충돌 시 `01-B Policy`, `04 Domain·DB`, `07 Interface`, SQL Constraint가 우선한다.

## 핵심 불변조건

1. **Provider 직접 호출 금지** — Core 외부 접근은 Connector Registry→MCP→Connector Adapter 경계만 사용한다.
2. **Write는 승인 후에만** — 승인 대상 Business Arguments/Target/Tool이 실행 전에 다시 검증된다.
3. **Claim Commit 전 MCP Write 금지**.
4. **승인 후 LLM 재작성 금지** — Tool·Arguments·Target·Dependency를 모델이 바꾸지 않는다.
5. **UNKNOWN_RESULT blind resend 금지**.
6. **FAILED 직접 재실행 금지** — `FAILED → MODIFIED → Review → Domain Validation → 새 Approval`.
7. **Verification 없이 성공 확정 금지** — Effect별 결정적 Read로 실제 외부 상태를 다시 확인한다.
8. **Action 상태와 Run 상태 혼용 금지** — 승인형 Write Action이 EXECUTING이어도 Run은 첫 Verification까지 기본 WAITING_APPROVAL이다.
9. **취소 중 in-flight 사실 보존** — RequestCancel Receipt가 durable cancel intent이며 결과 확정 전 Action을 CANCELLED로 덮지 않는다.
10. **FINALIZE는 상태 전이 Node가 아님** — Domain Command로 Terminal 상태가 먼저 만들어져야 한다.
11. **Confirmation owner resume** — 확인 응답은 발생시킨 Subgraph checkpoint로 돌아간다.
12. **외부 호출 중 SQLite Write Transaction 유지 금지**.
13. **Migration 소급 수정 금지** — 0001~0005는 checksum/history Artifact다.
14. **Gmail 원문 DELETE 금지** — Task/Calendar DELETE와 구분한다.
15. **Prompt Injection은 Source Data** — Connector 원문 속 instruction-like content가 정책/Tool 권한을 변경하지 못한다.
