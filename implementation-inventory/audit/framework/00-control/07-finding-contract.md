# Finding Contract

Finding은 향후 lane worker가 자기 lane의 atomic requirement에 대해서만 작성한다.

- finding은 하나 이상의 requirement ID와 재현 가능한 evidence ID를 참조한다.
- `expected`는 Canonical concern owner locator를, `observed`는 current baseline evidence를 참조한다.
- severity와 verdict vocabulary는 closed value를 사용한다.
- 다른 lane primary concern이면 finding을 복제하지 않고 `secondary_evidence_lane`과 handoff를 기록한다.
- remediation은 Audit 판정의 일부가 아니며 worker가 source를 수정하지 않는다.
- uncertainty는 finding으로 추측하지 않고 `unchecked.csv`에 남긴다.
- source-text hit, path 존재, historical finding만으로 finding을 만들 수 없다.
- duplicate candidate는 finding과 분리해 `04-duplicate-authority.csv`에 기록하고 X4 adjudication 전 global duplicate verdict를 확정하지 않는다.

## Requirement disposition accounting

각 `01-requirements.csv` row는 완료 시 정확히 하나의 `audit_disposition`을 가진다.

- `PASS`: 요구된 positive evidence와 적용 가능한 non-vacuous negative proof가 모두 충족되고 linked finding/unchecked가 없다.
- `FINDING`: 하나 이상의 linked finding이 존재한다. finding row 수와 requirement row 수는 동일하다고 가정하지 않는다.
- `UNCHECKED`: 필요한 증거를 끝내 확보하지 못했고 하나 이상의 linked unchecked row가 존재한다.
- 작업 중 `UNCLASSIFIED`는 허용하지만 lane completion 시 0이어야 한다.

Lane accounting은 finding 개수를 더하는 방식이 아니라 requirement disposition 개수를 사용한다.

```text
EXPECTED_REQUIREMENTS = ACCOUNTED_REQUIREMENTS
ACCOUNTED_REQUIREMENTS = PASS_REQUIREMENTS + FINDING_REQUIREMENTS + UNCHECKED_REQUIREMENTS
UNCLASSIFIED_REQUIREMENTS = 0
```

Schema는 `framework/templates/atomic-requirement-template.csv`, `finding-template.csv`, `unchecked-template.csv`를 따른다.
