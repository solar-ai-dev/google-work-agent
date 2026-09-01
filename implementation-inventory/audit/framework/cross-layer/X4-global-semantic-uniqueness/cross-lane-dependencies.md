# Cross-Lane Dependencies

Coordinator-frozen B~L manifest만 읽는다. X1~X3 결과는 병렬 실행 중 소비하지 않는다. owner collision은 Coordinator disposition 대상으로 제출하며 worker가 원 row를 수정하지 않는다.
