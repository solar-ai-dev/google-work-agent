# User Prompt Catalog v1.10.0 / R8.2

- `canonical-core-stress-v1.10.0.jsonl`: Core 60 + Stress 20 canonical user prompts.
- `canonical-holdout-locked-v1.10.0.jsonl`: locked Holdout 12 catalog. **Prompt tuning input으로 사용 금지**.
- 두 catalog을 합치면 Canonical User Prompt는 92개다.
- `finalist-paraphrases-v1.10.0.jsonl`: Finalist Core20 × 2 robustness variants. 각 Case는 한국어 1개 + 영어 1개로 구성해 제품의 ko/en 입력 계약을 점검한다.
- Source of truth for Gold remains the canonical case / paraphrase dataset files.
- Holdout는 catalog가 존재하더라도 `LOCKED_HOLDOUT`이며 DEV Prompt·Threshold 튜닝에 노출하지 않는다.
