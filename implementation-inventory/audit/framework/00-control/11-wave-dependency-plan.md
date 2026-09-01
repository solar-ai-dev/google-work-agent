# Wave Dependency Plan

## Wave 1

A~L은 동일 source baseline에서 독립 실행한다. 의미 질의가 필요하면 row를 복제하지 않고 dependency/handoff만 남긴다. R은 historical methodology만 다루며 Product row를 생성하지 않는다.

## Freeze barrier

Coordinator가 다음을 확인해야 Wave 2가 열린다: 모든 lane 종료, input hash 고정, schema 유효, primary-owner collision disposition, uncovered Canonical concern 계산, unchecked 보존.

## Wave 2 dependencies

- X1: A~H의 producer/consumer 계약과 B~G의 persistence/revision evidence
- X2: A~K의 requirement/evidence와 Coordinator가 Wave 1에서 freeze한 scenario input manifest
- X3: A~L의 requirement와 test/evidence claims
- X4: B~L의 owner/caller/import/registry/reachability claims

X1~X4는 서로의 mutable output을 소비하지 않는다. 상호 참조가 필요하면 Coordinator가 freeze한 input manifest만 사용한다.
