# User Prompt Catalog — R8.4

Source of truth는 Canonical Case와 Paraphrase JSON이다. Catalog는 **수동 편집하지 않고 재생성**한다.

- Canonical Core+Stress: `canonical-core-stress-v1.14-r8.4.jsonl` (80 rows)
- Finalist paraphrases: `finalist-paraphrases-v1.14-r8.4.jsonl` (40 rows)
- G00 필수: 동일 ID의 text/language/case_id/split/hash parity가 모두 일치해야 한다.
- Catalog drift가 1건이라도 있으면 실험 시작 금지.
