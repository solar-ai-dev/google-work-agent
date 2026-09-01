# Duplicate Authority Contract

Duplicate candidate는 이름 유사성이 아니라 **동일 semantic capability를 둘 이상의 production path/symbol이 구현하거나 runtime authority로 주장할 가능성**이다. 실제 candidate와 판정은 future run에서만 기록한다.

## Lane candidate rule

- 각 Wave 1 worker는 자기 primary-owned atomic requirement에서만 candidate를 생성한다.
- candidate에는 semantic capability key, 양쪽 path:symbol, callers, imports/exports, composition/registry binding, runtime reachability와 evidence IDs가 필요하다.
- V1/V2, legacy/current, compat/current, Policy, Domain guard/transition, Registry, State/persistence writer, external effect executor, routing, validator/schema authority를 포함한다.
- passthrough/re-export/alias/wrapper는 별도 runtime authority인지 단순 indirection인지 evidence로 구분한다.
- name/source-text 유사성, zero grep result, historical finding만으로 duplicate verdict를 만들 수 없다.
- lane은 `04-duplicate-authority.csv`에 candidate만 기록하며 global survivor/deletion verdict를 확정하지 않는다.

## Cross-lane adjudication rule

X4만 freeze된 모든 lane candidate를 semantic group으로 묶고 global duplicate authority를 adjudicate한다. 동일 candidate의 lane 간 복제, owner 충돌, evidence 불충분 candidate는 원본을 수정하지 않고 별도 unadjudicated output에 남긴다.

Schema는 `framework/templates/duplicate-authority-template.csv`, future global output은 `runs/<AUDIT_SHA>/cross-layer/X4-global-semantic-uniqueness/`를 따른다.
