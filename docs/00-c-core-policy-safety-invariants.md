# 00-C. 핵심 정책·안전 불변조건 요약

> R8.3 설명 문서. 충돌 시 Policy·Domain·Tool 계약이 우선한다.

## 핵심

- READ는 사용자 요청 범위에서 자동 가능하다.
- CREATE·UPDATE·SEND·허용 DELETE는 사용자 승인 필수다.
- Gmail 원문 삭제·Google Task 삭제·반복 Event 전체 일괄 수정은 금지한다.
- 승인 후 LLM은 Tool·Arguments·Target을 변경하지 않는다.
- Google Write 전에 Claim을 Commit한다.
- 외부 I/O 중 SQLite Write Transaction을 유지하지 않는다.
- `FAILED → EXECUTING`, `UNKNOWN_RESULT → EXECUTING` 직접 전이를 금지한다.
- UNKNOWN_RESULT에서는 blind resend하지 않고 기존 결과를 조회한다.
- CREATE/UPDATE는 GET 비교, SEND는 Sent Lookup, DELETE는 대상 부재/삭제 상태를 검증한다.
- Verification MISMATCH는 자동 Rollback/교정하지 않는다.
- Checkpoint는 재개 위치일 뿐 승인·실행 사실의 기준점이 아니다.
- Prompt·Completion·Credential·Google 전체 원문을 일반 Trace/Audit에 저장하지 않는다.
