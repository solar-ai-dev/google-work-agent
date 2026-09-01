# Deterministic Merge Contract

Coordinator만 Wave별 final merge를 수행한다.

## Inputs

- freeze된 `runs/<AUDIT_SHA>/lanes/<EXACT-LANE-DIRECTORY>/` 산출물
- lane completion manifest와 파일 hash
- lane-local IDs와 `04-duplicate-authority.csv`; shared counter 없음

## Ordered merge

1. baseline SHA와 schema/header 검증
2. lane namespace와 허용 output path 검증
3. duplicate ID 검출
4. canonical locator와 atomic semantic key 정규화
5. duplicate semantic row와 primary-owner collision 검출
6. conflicting verdict와 동일 path:symbol owner claim 격리
7. secondary evidence 연결
8. unchecked/missing evidence와 uncovered concern 계산
9. 충돌 없는 row만 deterministic sort 후 merged view 생성
10. merge manifest에 input hash, disposition, output hash 기록

Worker output은 수정하지 않는다. 충돌은 Coordinator disposition row로 해결하며 원본을 보존한다. Wave 1 merged view가 freeze되기 전 Wave 2 input으로 사용할 수 없다.

## Future Coordinator output

Coordinator만 `runs/<AUDIT_SHA>/coordinator/`에 다음을 쓴다.

1. `00-merge-baseline.md`
2. `01-lane-input-manifest.csv`
3. `02-global-requirement-merge.csv`
4. `03-owner-collision-census.csv`
5. `04-duplicate-row-census.csv`
6. `05-cross-lane-contradictions.csv`
7. `06-global-findings.csv`
8. `07-global-unchecked.csv`
9. `08-global-coverage-summary.csv`
10. `09-coordinator-report.md`
