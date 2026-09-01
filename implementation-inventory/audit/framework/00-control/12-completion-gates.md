# Completion Gates

## Lane gate

- baseline SHA 일치
- mandatory read set 기록
- 허용 디렉터리 밖 write 0
- schema/header 유효
- lane-local ID collision 0
- duplicate candidate schema와 evidence reference 유효
- primary scope 밖 verdict 0
- evidence 없는 finding 0
- unchecked 누락 0

## Wave 1 merge gate

- A~L + R 종료 및 hash freeze
- shared mutable output 0
- cross-lane primary-owner collision disposition 완료
- Canonical concern without lane 0
- duplicate semantic row와 duplicate ID 격리
- lane duplicate candidates가 X4 input manifest에 모두 포함

## Wave 2 merge gate

- X1~X4 종료 및 hash freeze
- handoff/lineage/test non-vacuity/global reachability의 unchecked 명시
- conflicting verdict와 missing secondary evidence 명시

이 gate 정의 자체는 PASS/CLEAN 판정이 아니다. 실제 run evidence 없이 completion을 선언하지 않는다.
