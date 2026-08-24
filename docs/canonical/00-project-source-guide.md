# 00. Project Source Guide

**Canonical snapshot coordination guide — 2026-08-24**

## Concern authority

```
제품 목표·범위          → 01 PRD
사용자 기능 동작        → 01-A Functional
안전·금지·승인 정책     → 01-B Policy
UI·UX                   → 02 UI·UX
시스템·레이어 경계       → 03 Architecture
Domain aggregate·persistence·design invariant → 04 Domain·DB
lifecycle command·source state·guard·transition → Domain State Transition Contract
required persistent DB invariant semantics       → 04 Domain·DB
executable SQL migration realization             → implementation artifact verified by 10/12/16
state-transition normative verification         → State Transition Test Matrix
Retrieval               → 05
Agent·Workflow runtime  → 06
Tool·MCP·내부 Interface → 07
시퀀스                  → 08
보안                    → 09
환경·배포               → 10
관측성                  → 11
제품 회귀 검증          → 12
후보 비교·실험          → 13
운영                    → 14
Prompt·Failure          → 15
Repository placement/naming/import-export enforcement/single production authority → 16
```

03 owns system/layer dependency semantics. 16 owns how those constraints are realized and enforced in repository paths/imports/exports and may not relax 03.

Domain/state authority is layered rather than duplicated:

- `04 Domain·DB` owns aggregate facts, persistence semantics, and Domain invariants at the design level.
- `Domain State Transition Contract` owns the closed set of lifecycle commands, allowed source states, guards, and transition semantics.
- `04 Domain·DB` owns the required persistent invariant semantics: uniqueness, referential ownership, conditional-write/concurrency rules, review freshness, cross-aggregate guards, and which invariants require DB-level final defense.
- executable SQL migrations are **implementation artifacts**, not a separate behavioral/design authority. They realize the 04 contract and are verified by 10/12/16 for ordering, checksum, immutability, and enforcement. A migration may not invent a weaker or different invariant.
- `State Transition Test Matrix` is the normative verification matrix for those contracts; it does not invent a new lifecycle command/state/guard that is absent from the owning Domain/State contracts.
- `12 Test` verifies product contracts and `13 Evaluation` compares candidates; neither becomes a behavioral source of truth merely because a test/evaluation artifact contains an expected value.

06/15 own versioned runtime Node/Agent/Prompt identifiers. Current heavy-Agent atomic responsibility IDs remain owned by the current Workflow and Prompt·Failure contracts. Repository Architecture maps those semantic capabilities to canonical repository owner/path/file/symbol names and does not independently rename a runtime contract ID.

## Dependency-safe read order

문서 번호는 단순 목록 번호가 아니라 **의미 의존 순서**로 읽는다. 특정 Concern만 수정하더라도 아래 선행 Source를 먼저 확인한다.

```text
00 Project Source Guide
→ 01 PRD
→ 01-A Functional + 01-B Policy
→ 02 UI·UX
→ 03 System Architecture
→ 04 Domain·DB
→ Domain State Transition Contract
→ 05 Retrieval
→ 06 Workflow
→ 07 Interface / Port / MCP
→ 08 Sequence
→ 09 Security
→ 10 Infrastructure
→ 11 Observability
→ 15 Prompt·Failure
→ 16 Repository Architecture
→ State Transition Test Matrix
→ 12 Test
→ 13 Evaluation
→ 14 Operations
```

핵심 선행 관계:

- `07 Interface`는 `03`의 layer/dependency boundary와 `04/State/05/06`의 semantics를 **소비**한다. 07만 먼저 읽고 새로운 owner/Port/lifecycle 의미를 만들지 않는다.
- `08 Sequence`는 03~07의 이미 정의된 책임을 시간 순서로 배열할 뿐 새 behavior를 만들지 않는다.
- `16 Repository Architecture`는 semantic Sources를 읽은 뒤 path/file/symbol을 결정한다. 16에서 behavior를 역설계하지 않는다.
- `12 Test`와 `13 Evaluation`은 owner contract를 검증·비교한다. 테스트/평가 문장을 제품 behavior authority로 역수입하지 않는다.
- `14 Operations`는 current runtime/security/observability contract를 소비한다. 운영 편의를 이유로 새 production path를 만들지 않는다.

직접 진입할 때도 각 canonical 문서 상단의 **선행 읽기**를 따른다.

## Cross-document contract consumption rule

Canonical contract는 **Concern owner에서 한 번만 완전하게 정의**한다. Downstream 문서는 그 계약 전체를 다시 써서 공동 authority를 만들지 않고, 자기 concern을 구현·검증하는 데 필요한 **local projection**만 적는다.

- `03`은 layer/process boundary, `04`는 durable fact/invariant, State Contract는 lifecycle transition, `05`는 retrieval semantics, `06`은 workflow topology, `07`은 typed wire/Port, `08`은 interaction order를 각각 완전하게 소유한다.
- `09~11`, `14`는 선행 계약을 security/runtime/observability/operations 관점으로 **소비**한다. 선행 문서의 전체 state matrix, field list, reconciliation precedence, handler algorithm을 복제하지 않는다.
- `16`은 semantic contract를 path/file/symbol로 매핑할 뿐 behavior 설명을 복제하지 않는다.
- `12`와 `State Transition Test Matrix`는 검증 목적상 expected assertion을 명시적으로 반복할 수 있다. 이 반복은 behavioral authority가 아니라 verification oracle이다.
- `00-A/B/C`와 `99`는 supporting/noncanonical이므로 이해를 돕는 축약 반복을 허용하되 구현 authority로 인용하지 않는다.
- Owner 문구의 설명 방식만 바뀌고 downstream concern의 실제 projection이 바뀌지 않았다면 downstream 문서를 동시 수정하지 않는다. **Downstream 수정은 local consequence가 바뀔 때만 필요하다.**
- Cross-reference는 가능한 한 owner + stable concept/section을 가리킨다. 버전 문자열·변경일·패치 서술을 여러 canonical 본문에 복제하지 않는다.

이 규칙의 목적은 반복 문장을 줄이는 것이 아니라 **수정 전파 fan-out과 duplicate authority를 줄이는 것**이다. Coding Agent가 local context를 이해하는 데 필요한 guard·입출력·예외·검증 assertion은 남긴다.

## Architecture blocker vs implementation choice

Design freeze는 **Agent가 서로 다른 module/owner/type/authority를 만들게 만드는 불확실성**을 닫는 데 초점을 둔다.

Architecture blocker:
- semantic owner / layer / dependency direction ambiguity
- production path/file/symbol 또는 one-production-authority ambiguity
- Port ↔ Adapter binding/placement ambiguity
- 같은 current concept의 competing contract type/closed vocabulary
- lifecycle/side-effect/persistence boundary ambiguity
- external I/O와 DB transaction ownership ambiguity

Implementation choice:
- timeout/page/batch/file-size 같은 numeric tuning
- 내부 algorithm/data structure/helper detail
- adapter-local serialization detail
- presentation-only wording/formatting
- environment-specific configurable limit

Implementation choice는 합리적인 default로 구현해도 되며 design freeze blocker가 아니다. 여러 문서가 이런 값을 중복 소유해 불일치를 만들면 duplicate authority를 제거하고 concern owner에는 필요한 bounded/fail-closed 의미만 남긴다. 단 implementation choice를 이유로 새 semantic owner/package/Port/type을 발명해서는 안 된다.

## Project Source count

Declared canonical **design Project Source count is 21**. 아래 closed manifest가 이 snapshot의 구현·검증 의미 권위를 전부 구성한다. Executable migration은 이 설계를 구현하는 repository artifact이며 Project Source count에 포함하지 않는다.

### Canonical design Project Source manifest — exactly 21

```
01  00 Project Source Guide
02  01 Requirements / PRD
03  01-A Functional Definition
04  01-B Policy Definition
05  02 UI·UX Design
06  03 System Architecture
07  04 Domain·Database Design
08  05 Context·Retrieval
09  06 Agent·Workflow
10  07 Tool·MCP·Internal Interface
11  08 Sequence Design
12  09 Security·Auth
13  10 Infrastructure·Environment
14  11 Observability·Logging·Audit
15  12 Test Design
16  13 Evaluation·Experiment
17  14 Operations·Troubleshooting
18  15 Agent Capability·Failure·Prompt Contract
19  16 Repository Architecture Source
20  Domain State Transition Contract
21  State Transition Test Matrix
```

이 21개 목록은 count authority다. Project Overview/coordination·summary·audit page와 16 아래 subordinate normative page는 별도 Project Source entry로 추가 계산하지 않는다. Subordinate page는 16의 세부 normative source로 읽되 Project Source count는 증가시키지 않는다.

`Domain State Transition Contract`와 `State Transition Test Matrix`는 이 snapshot에 실제 포함되어야 하며 lifecycle implementation/checklist는 두 문서를 resolve할 수 있어야 한다.

Executable migration은 `16`의 `NNNN_<semantic_change>.sql` grammar와 `10`의 discovery/order/checksum 규칙을 따른다. **Applied migration은 immutable**이며, 구현이 04의 required invariant를 만족하지 못하면 기존 파일을 소급 수정하지 않고 다음 numeric forward migration을 추가한다. 12는 migration artifact가 04/State Contract 의미를 실제로 enforcement하는지 검증한다.

> **Snapshot completeness:** 이 frozen design set은 21개 canonical design source를 모두 포함한다. SQL 파일의 존재 여부는 design-source completeness가 아니라 implementation/release verification 항목이다.

## Snapshot folder layout

현재 ZIP은 **읽기 편의만 위해** 다음처럼 배치한다. 폴더는 새 semantic authority가 아니다.

```text
00 Project Source Guide.md
00 Supporting/                    # 비권위 rationale/summary
01 ... 15 ...                     # canonical concern owners
04-A Domain State Transition Contract.md
12-A State Transition Test Matrix.md
16 Repository Architecture/
  16 Repository Architecture Source.md
  00 ... 13 ...                   # 16의 normative subordinate pages
99 Archive/                       # historical/non-current material
```

Notion export hash는 파일명에서 제거한다. Canonical source identity는 파일 hash가 아니라 위 manifest의 문서 역할/제목으로 식별한다.

## Version rule

- Version·날짜·snapshot 번호는 **traceability metadata**이며 독립 correctness gate가 아니다.
- 실제 Gate는 Concern Authority, 현재 의미 정합성, source locator 유효성, 중복 authority 부재, 누락·모순 부재다.
- 다른 문서를 참조할 때는 가능한 한 특정 과거 Version 번호보다 **Concern owner와 current semantic contract**를 가리킨다.
- repository naming/placement grammar의 변경은 `16`, behavioral/runtime semantics의 변경은 해당 01–15 owner, lifecycle semantics는 `Domain State Transition Contract`, required DB invariant semantics는 `04 Domain·DB`가 각각 소유한다. SQL migration은 이 계약을 구현하며 독립 semantic owner가 아니다.

## Structural refactor gate

```
DOCUMENT_AUTHORITY_PRIORITY_PASS
DOCUMENT_PURPOSE_SCOPE_PASS
DOCUMENT_TRACEABILITY_CONSISTENCY_PASS
DOCUMENT_FORMAT_CONSISTENCY_PASS
SEMANTIC_TERMINOLOGY_CONSISTENCY_PASS
CROSS_REFERENCE_VALIDITY_PASS
TRACEABILITY_COMPLETENESS_PASS
NO_DUPLICATE_AUTHORITY_PASS
```

Only after all pass may `ARCHITECTURE_RULESET_FROZEN` and `READY_FOR_STRUCTURAL_REFACTOR` be declared. Product design freeze additionally requires the current State Transition Contract/Test Matrix, 16 implementation mapping, READ/WRITE/Recovery coverage, and dependency-safe implementation order to have no unresolved design decision.

For repository naming/placement questions, 16 is the single concern authority. Other Project Sources may define semantic identifiers they own, but they must not introduce an independent repository path/file/symbol naming rule. Such references are informative mappings to 16 unless the owning semantic contract itself is being versioned.
