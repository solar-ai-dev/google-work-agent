# Google Work Agent — Codex Instructions

이 `AGENTS.md`는 저장소 루트 전체에 적용한다.

하위 `AGENTS.md`는 경로별 규칙을 추가할 수 있지만 이 파일과 `/docs`의 Canonical 계약을 약화시키면 안 된다.

## Authority

* 코딩 기준은 현재 저장소 `/docs`의 Canonical snapshot이다.
* 항상 `00 Project Source Guide`에서 Concern Owner와 선행 읽기 순서를 먼저 확인한다.
* behavior는 해당 Concern Owner가 소유하고, repository path/file/symbol/import/single-authority 규칙은 `16 Repository Architecture`가 소유한다.
* 현재 코드, 기존 테스트, Git history, 기존 파일명은 설계 Authority가 아니다. migration input이다.
* 현재 구현에서 target architecture를 역추론하지 않는다.
* 문서에 없는 state, lifecycle, owner, Port, operation, contract/type을 임의로 만들지 않는다.
* 적용된 Migration은 수정하지 않는다. 필요한 DB 변경은 forward Migration으로 추가한다.

## Current Work Mode

현재 작업은 일반적인 behavior-preserving refactor가 아니라 **Canonical design에 기존 구현을 reconciliation하는 migration**이다.

* 잘못된 기존 구조나 behavior는 기존 코드라는 이유로 보존하지 않는다.
* Canonical과 이미 일치하는 구현은 불필요하게 rewrite하지 않는다.
* 작업 단위는 파일이 아니라 **semantic capability**다.
* 새 구현을 추가하는 것보다 기존 authority를 canonical authority로 교체하는 것을 우선한다.

## Work Procedure

각 capability는 다음 순서로 처리한다.

```text
SPEC
→ Canonical Owner 확인
→ 기존 implementation / caller / test / DI 검색
→ KEEP | MOVE | MERGE | REWRITE | DELETE | CREATE 판정
→ canonical implementation으로 cut-over
→ production caller 전환
→ old authority / import / export 제거
→ 관련 테스트
```

규칙:

* 새 production file을 만들기 전에 동일 capability의 기존 구현을 먼저 찾는다.
* 하나의 capability에는 하나의 production authority만 둔다.
* 가능한 한 capability 하나를 완전히 cut-over한 뒤 다음 capability로 이동한다.
* 기존 구현을 대체하는 새 구현을 만들었다면 불필요한 old path를 남기지 않는다.
* 중복 구현은 MERGE/DELETE한다.
* 작은 diff보다 **가장 작은 완결 capability cut-over**를 우선한다.

## Architecture / Ownership

```text
DIRECTORY TELLS OWNERSHIP
FILENAME TELLS RESPONSIBILITY
IMPORT TELLS DEPENDENCY DIRECTION
ONE CAPABILITY HAS ONE PRODUCTION AUTHORITY
```

* Domain: invariant와 lifecycle/domain semantics
* Policy: deterministic allow/block/approval/safety
* Application: use case와 transaction orchestration
* Workflow/LangGraph: State, Node/Edge/Interrupt/Resume orchestration
* Port: 외부 boundary contract
* Adapter/Connector: concrete integration
* API: protocol validation/translation
* Composition Root: construction/DI/lifecycle wiring only

금지:

* Core → Provider SDK/API direct call
* Application → concrete Adapter
* Domain → Application/Adapter
* FastAPI Route → DB/Adapter concrete
* Agent → peer Agent direct call
* Agent/LLM → external Write authority
* speculative abstraction
* second live production authority
* 단순 forwarding만 늘리는 wrapper/adapter chain

## Canonical / Compatibility

Canonical은 기존 구조 위에 추가되는 새 계층이 아니다.

* 같은 의미의 V1/V2/Canonical implementation을 동시에 production authority로 유지하지 않는다.
* compatibility는 migration 중 필요한 얇은 delegate/re-export만 허용한다.
* compatibility layer는 business logic을 소유하지 않는다.
* capability cut-over가 끝나면 old caller/path/import/export와 temporary compatibility를 제거한다.
* `R1`, `R2`, `R2.1`, `Wave`, `Phase` 같은 구현 단계는 장기 production architecture로 남기지 않는다.

같은 business fact를 단순 Layer 이동 때문에 별도 DTO/type으로 반복 정의하지 않는다. 새 representation은 실제 boundary가 있을 때만 추가한다.

## State / Workflow / Write Safety

* undocumented state/transition/edge/resume target을 만들지 않는다.
* Domain Store는 승인·실행·검증 사실의 기준점이다.
* LangGraph Checkpoint는 workflow resume 위치다.
* UI/SSE/Trace는 Projection이며 Domain truth가 아니다.
* external MCP/Provider/LLM I/O 중 SQLite write transaction을 유지하지 않는다.
* Write는 Canonical Approval → Claim → BeginExecutionAttempt → Connector Write → Verification/Recovery 경계를 따른다.
* `BeginExecutionAttempt(applied=true)` commit 전 Connector Write는 0이어야 한다.
* `UNKNOWN_RESULT`에서는 blind resend나 새 Write Attempt를 만들지 않는다.
* Agent/LLM이 approval, policy, state transition, execution success를 최종 판정하지 않는다.

## Tests / Gates

* 기존 테스트도 Authority가 아니다. Canonical behavior와 invariant를 검증해야 한다.
* 기존 테스트가 Canonical과 충돌하면 KEEP | REWRITE | DELETE를 판정한다.
* 테스트는 observable behavior, state transition, safety invariant, external effect를 우선 검증한다.
* production source 문자열이나 private method 내부 구현을 직접 검사하는 테스트는 피한다.
* 테스트 파일끼리 private helper를 import하지 않는다. 반복되는 fixture/fake는 `tests/support` 또는 `tests/fakes`로 이동한다.
* 관련 safety/contract/state test가 깨진 상태에서 완료라고 보고하지 않는다.

필수 구조 Gate 예:

```text
Application → concrete Adapter        = 0
Domain → Application                  = 0
Core → Provider SDK/direct API        = 0
FastAPI Route → Adapter/DB concrete   = 0
Agent → Provider API/SDK              = 0
Agent → peer Agent direct call        = 0
external I/O inside SQLite write tx   = 0
duplicate production authority        = 0
```

## Completion

Capability는 다음을 만족해야 완료다.

* canonical authority 존재
* production caller가 canonical authority 사용
* duplicate writer/authority 0
* 불필요한 old caller/import/export 제거
* temporary compatibility 제거 또는 명시적 미완료 dependency만 존재
* 관련 Canonical tests 통과
* safety/state/transaction invariant 유지

새 구현을 추가한 것만으로 완료가 아니다.

**기존 authority가 제거되었다는 확인까지 필요하다.**

## Git / Scope

* 사용자가 명시하지 않으면 commit, push, merge, rebase, branch switch, destructive Git operation을 하지 않는다.
* 관련 없는 cleanup, formatting-only 대형 diff, dependency-wide upgrade를 만들지 않는다.
* 다른 작업자의 변경을 임의로 되돌리지 않는다.
* 저장소에서 확인 가능한 내용을 사용자에게 다시 묻지 않는다.

## Completion Report

완료 보고는 다음만 간결하게 포함한다.

* 변경한 capability
* cut-over / 삭제한 legacy authority
* 테스트·Gate 결과
* 남은 실제 blocker 또는 명시적 migration dependency

별도 status/report 문서는 사용자가 요청하지 않으면 만들지 않는다.
