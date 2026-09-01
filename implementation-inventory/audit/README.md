# Audit Framework

`implementation-inventory/audit/`는 Fresh Audit의 구조·규칙·future output contract를 소유하는 유일한 repository root다. Product behavior와 repository architecture의 authority는 current Canonical이며 이 framework나 기존 Audit이 아니다.

## Directory roles

- `framework/`: control, schema template, historical-reference plan, Wave 1 lane, Wave 2 cross-layer 지침
- `runs/<AUDIT_SHA>/`: 실제 Audit을 시작할 때만 만드는 SHA-scoped 결과 root
- `runs/<AUDIT_SHA>/lanes/<EXACT-LANE>/`: Wave 1 worker 전용 write root
- `runs/<AUDIT_SHA>/cross-layer/<EXACT-X>/`: Wave 2 worker 전용 write root
- `runs/<AUDIT_SHA>/coordinator/`: Coordinator-only merge output

`implementation-inventory/ledger.md`와 `canonical-current-implementation-map.md`는 변경하지 않는 comparison target이다. `C:/project/google-work-agent-audit/**`는 read-only historical reference이며 PASS/CLEAN/finding/path/symbol을 current evidence로 상속하지 않는다.

## Execution isolation

Wave 1 A~L과 R은 자기 exact lane directory만 쓴다. Wave 1 freeze 후 X1~X4가 자기 cross-layer directory만 쓰며, 모든 merge는 Coordinator만 수행한다. shared mutable CSV, 다른 worker directory 수정, shared counter는 금지다.

현재 framework 단계에는 requirement/evidence/duplicate/finding/verdict/remediation과 실제 SHA run directory가 없다. 실행 순서는 `framework/00-control/10-parallel-execution-plan.md`와 `11-wave-dependency-plan.md`를 따른다.
