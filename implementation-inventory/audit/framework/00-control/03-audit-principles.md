# Audit Principles

1. Canonical concern owner가 의미를 소유하고 repository history나 기존 test는 authority가 아니다.
2. atomic requirement는 정확히 한 primary lane이 소유한다.
3. 다른 lane은 `SECONDARY_EVIDENCE_LANE`으로만 같은 requirement에 기여한다.
4. positive evidence와 non-vacuous negative evidence를 분리한다.
5. path 또는 source text 존재만으로 runtime reachability를 증명하지 않는다.
6. absence claim은 search universe와 current positive anchor를 함께 기록한다.
7. worker는 lane-local ID와 lane-local output만 사용한다.
8. verdict 충돌과 owner 충돌은 worker가 덮어쓰지 않고 Coordinator가 결정한다.
9. Wave 1 merge/freeze 전에는 Wave 2를 시작하지 않는다.
10. historical material은 methodology hypothesis이며 current evidence가 아니다.
