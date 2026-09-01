# Evidence Contract

Evidence row는 observation이며 verdict가 아니다.

## Required properties

- `evidence_id`는 lane-local namespace를 사용한다.
- `requirement_id`, `lane_id`, `evidence_kind`, exact `repo_path`와 가능한 경우 `symbol`/line을 기록한다.
- source evidence는 `AUDIT_SHA`에서 재현 가능해야 한다.
- runtime/test/build evidence는 exact command, exit code, count, artifact/hash, 실행 환경을 기록한다.
- caller/reachability evidence는 owner → import/export → composition/registry → runtime consumer의 연결을 분리해 기록한다.
- historical evidence는 `provenance=historical-reference`로 격리하며 current verdict의 직접 근거로 사용할 수 없다.

## Negative evidence

absence claim에는 search scope, method/query, result count, exclusions, non-vacuity anchor가 모두 필요하다. 현재 canonical owner 또는 실제 caller라는 positive anchor가 없는 `0 matches`는 closure evidence가 아니다.

Schema는 `framework/templates/implementation-evidence-template.csv`와 `negative-evidence-template.csv`를 따른다.
