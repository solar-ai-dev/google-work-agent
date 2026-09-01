# Lane Summary Template

- Product Source SHA:
- Audit Framework SHA:
- Lane:
- Worker:
- Input manifest hash:
- Output file hashes:
- Expected requirement rows:
- Accounted requirement rows:
- PASS requirement rows:
- FINDING requirement rows:
- UNCHECKED requirement rows:
- UNCLASSIFIED requirement rows:
- Evidence rows:
- Negative-evidence rows:
- Finding rows:
- Duplicate-candidate rows:
- Cross-lane handoffs:
- Scope exclusions:
- Lane completion gate: `NOT_EVALUATED`

Accounting invariant:

```text
EXPECTED = ACCOUNTED
ACCOUNTED = PASS + FINDING + UNCHECKED
UNCLASSIFIED = 0
```

이 template에는 current 결과를 기록하지 않는다.
