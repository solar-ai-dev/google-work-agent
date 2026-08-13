# 00-C. 핵심 정책·안전 불변조건 요약

> 실제 권위는 01-B Policy, Domain 상태 전이 계약, DB Constraint, 07 Interface, 09 Security가 소유한다.

## 1. 안전 모델

안전은 LLM의 좋은 의도를 신뢰하는 것이 아니라 권한·상태·인자·실행·검증을 결정적 계약으로 분리해 잘못된 판단이 실제 Connector Side Effect로 이어지지 않게 하는 것이다.

```text
Agent 제안
→ Domain·Policy 판정
→ 사용자 승인
→ Claim
→ Connector Write
→ Provider 상태 재조회
→ Verification
→ Recovery
```

P0 첫 Connector는 Google Workspace다.

## 2. Agent가 소유하지 않는 것

- Policy 최종 허용
- Approval 생성/우회
- Connector Write 직접 실행
- 승인 Arguments 변경
- Write 성공 최종 확정
- UNKNOWN_RESULT blind resend
- Domain 상태 직접 변경

## 3. READ / WRITE

READ는 사용자 요청 범위에서 자동 수행 가능하지만 일반 Retrieval READ는 Approval/ExecutionAttempt/Verification Row를 만들지 않는다.

WRITE Effect:

```text
CREATE | UPDATE | SEND | 허용된 DELETE
```

모든 Write는 사용자 승인 후 실행한다.

## 4. Approval

Approval은 정확한 실행 권한 Snapshot이다.

```text
Action Version
Tool / Effect
Canonical Arguments
approval_arguments_hash
Target Resource
Source Snapshot
Policy / Tool Schema Version
Expiry
```

승인 이후 Tool/Arguments/Target을 다시 생성하지 않는다.

## 5. Claim V2

```text
Claim Transaction COMMIT
→ execution_arguments_hash 생성
→ Connector MCP로 전달
→ MCP가 실제 수신 Arguments 재해시
→ 일치할 때만 Provider Write
```

외부 호출 중 SQLite Write Transaction을 유지하지 않는다.

## 6. FAILED와 UNKNOWN_RESULT

FAILED는 미전달이 확정된 실패다. 재시도는 `MODIFIED → 새 Approval → 새 Attempt`를 거친다.

UNKNOWN_RESULT는 Provider에 전달됐을 가능성이 있는 상태다.

```text
UNKNOWN_RESULT
→ 기존 결과 조회/Search/GET
→ 기존 Attempt 복구
또는 RECOVERY_REQUIRED
```

새 Attempt와 blind resend를 금지한다.

## 7. Verification

- CREATE → 생성 Resource GET
- UPDATE → Target GET
- SEND → Sent 결과 조회
- DELETE → Target 부재/삭제 상태 확인

Tool 응답의 성공만으로 제품 성공을 확정하지 않는다.

## 8. Source는 비신뢰 데이터

Connector Source 본문은 Evidence이지 시스템 명령이 아니다. Source가 Policy 변경, Tool 실행, Local File/Shell 실행을 유발하지 못한다.

## 9. Domain / Checkpoint / UI

```text
Domain Store = 승인·실행·검증 사실
Checkpoint   = Graph 재개 위치
SSE / UI     = 사용자 Projection
```

서로 대체하지 않는다.

## 10. Connector 경계

```text
Core
→ Connector Registry
→ MCP Client/Port
→ Connector MCP Server
→ Provider Adapter
```

Core direct Provider API/SDK call과 direct fallback을 금지한다.

## 11. Profile-independent Safety

SINGLE/THREE/SIX가 달라도 Policy, Approval, Claim, Execution, Verification, Recovery는 동일한 결정적 Engine을 사용한다.
