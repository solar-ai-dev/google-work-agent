# Finding Contract

Finding은 향후 lane worker가 자기 lane의 atomic requirement에 대해서만 작성한다.

- finding은 하나 이상의 requirement ID와 재현 가능한 evidence ID를 참조한다.
- `expected`는 Canonical concern owner locator를, `observed`는 current baseline evidence를 참조한다.
- severity와 verdict vocabulary는 closed value를 사용한다.
- 다른 lane primary concern이면 finding을 복제하지 않고 `secondary_evidence_lane`과 handoff를 기록한다.
- remediation은 이번 framework와 audit 판정의 일부가 아니며 worker가 source를 수정하지 않는다.
- uncertainty는 finding으로 추측하지 않고 `unchecked.csv`에 남긴다.
- source-text hit, path 존재, historical finding만으로 finding을 만들 수 없다.
- duplicate candidate는 finding과 분리해 `04-duplicate-authority.csv`에 기록하고 X4 adjudication 전 global duplicate verdict를 확정하지 않는다.

Schema는 `framework/templates/finding-template.csv`를 따른다.
