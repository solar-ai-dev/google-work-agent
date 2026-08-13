# 00-C. 핵심 정책·안전 불변조건 요약

- 승인 없는 Google Write 금지. 실제 Write는 승인·Claim 이후 MCP Write Tool로만 수행한다.
- Gmail Message/Thread 원문 삭제와 반복 Event 전체 일괄 수정 금지.
- Google Source 본문은 항상 비신뢰 DATA_ONLY다. Source의 명령문이 사용자 요청·Tool Route·Approval로 승격될 수 없다.
- Tool Route가 IN/OUT을 한 번 확정하며 Retrieval/Planning은 Tool을 재선택하지 않는다.
- React·FastAPI Route·Application·LangGraph·Agent·Domain의 Gmail·Tasks·Calendar Provider API/SDK 직접 호출과 Provider Client 구성 금지. 모든 Google Workspace Read/Write/Verification/Recovery는 MCP Client/Tool 경계를 통과하며 MCP 장애 시 direct fallback하지 않는다.
- TASK CREATE는 기존 미완료 Task 중복검사, CALENDAR CREATE는 Event/FreeBusy 충돌검사가 필수다.
- 사용자 명시 범위 밖의 필수 READ는 Scope Confirmation 없이 자동 확장하지 않는다.
- LLM이 중복/충돌을 단독 확정하지 않는다. 결정적 validator를 통과해야 한다.
- 정확 중복은 기본 no-action이며 강제 추가 생성/충돌 일정 Override는 2차 Confirmation과 APPROVED `PolicyConfirmationReceiptV1`을 요구한다.
- Receipt/Approval/Action lineage가 stale이면 실행 금지.
- ClaimContextV2는 승인 Business Hash와 Execution Hash를 분리하고 TTL/instance/nonce를 검증한다.
- `UNKNOWN_RESULT`에서 새 Write를 만들지 않는다.
- 모든 성공 Write는 MCP Verification Read로 실제 Google Provider 상태를 재조회해 종료한다.
- Prompt/Completion, Credential, Google 전체 원문, Attachment bytes를 Trace/Audit에 저장하지 않는다.
