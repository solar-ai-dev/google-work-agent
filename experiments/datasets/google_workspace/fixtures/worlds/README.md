# Fixture Worlds v0.3

- DEV World: 14개
- Node HOLDOUT World: 4개
- 합계: 18개
- 모든 주소와 데이터는 `example.test` 기반 합성 데이터다.
- 같은 `scenario_family_id`와 `fixture_relation_family`를 DEV와 HOLDOUT에 나누지 않는다.
- Canonical E2E Holdout은 이 Node HOLDOUT과 별도로 구축한다.
- Node Capability의 `MUTATED` 입력은 Fixture 원본을 바꾸지 않고, 평가 Item의 `mutation_spec`으로 통제된 오류·경계 조건만 주입한다.
