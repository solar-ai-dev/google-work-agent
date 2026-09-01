# Completion Gates

## Lane gate

- `PRODUCT_SOURCE_SHA`와 `AUDIT_FRAMEWORK_SHA`가 run manifest와 일치
- worker checkout `HEAD == AUDIT_FRAMEWORK_SHA` + clean worktree
- Product/framework parity gate 통과: `PRODUCT_SOURCE_SHA..AUDIT_FRAMEWORK_SHA`의 허용 변경은 `implementation-inventory/audit/**`뿐
- mandatory read set 기록
- 허용 디렉터리 밖 write 0
- schema/header 유효
- lane-local ID collision 0
- duplicate candidate schema와 evidence reference 유효
- primary scope 밖 verdict 0
- evidence 없는 finding 0
- unchecked 누락 0
- `EXPECTED_REQUIREMENTS = ACCOUNTED_REQUIREMENTS`
- `ACCOUNTED_REQUIREMENTS = PASS_REQUIREMENTS + FINDING_REQUIREMENTS + UNCHECKED_REQUIREMENTS`
- `UNCLASSIFIED_REQUIREMENTS = 0`

`FINDING_REQUIREMENTS`는 finding row 개수가 아니라 `audit_disposition=FINDING`인 requirement row 개수다.

## Wave 1 merge gate

- A~L + R 종료 및 hash freeze
- shared mutable output 0
- 모든 lane accounting equation 통과
- `UNMERGED_LANE_REQUIREMENTS = 0`
- cross-lane primary-owner collision disposition 완료
- Canonical concern without lane 0
- duplicate semantic row와 duplicate ID 격리
- lane duplicate candidates가 X4 input manifest에 모두 포함

## Wave 2 merge gate

- X1~X4 종료 및 hash freeze
- handoff/lineage/test non-vacuity/global reachability의 unchecked 명시
- conflicting verdict와 missing secondary evidence 명시
- 모든 Wave 2 input이 frozen Wave 1 manifest/hash에만 의존

## Full Fresh Audit closure gate

최종 closure 선언에는 Wave 1/Wave 2가 끝났다는 사실만으로 충분하지 않다. 다음 값이 모두 0이어야 한다.

```text
GLOBAL_UNCHECKED_REQUIREMENTS = 0
GLOBAL_UNCLASSIFIED_REQUIREMENTS = 0
UNCOVERED_CANONICAL_REQUIREMENTS = 0
UNMERGED_LANE_REQUIREMENTS = 0
UNRESOLVED_PRIMARY_OWNER_COLLISIONS = 0
UNRESOLVED_VERDICT_CONTRADICTIONS = 0
UNADJUDICATED_DUPLICATE_CANDIDATES = 0
CONFIRMED_SAME_SEMANTIC_PRODUCTION_AUTHORITIES = 0
```

또한 삭제 이후 필수 capability/test proof 손실을 별도 global closure 항목으로 판정한다.

```text
ACCIDENTALLY_REMOVED_REQUIRED_CAPABILITY = 0
REMOVED_TEST_WITHOUT_REQUIRED_PROOF = 0
```

이 gate 정의 자체는 PASS/CLEAN 판정이 아니다. 실제 run evidence 없이 completion을 선언하지 않는다.
