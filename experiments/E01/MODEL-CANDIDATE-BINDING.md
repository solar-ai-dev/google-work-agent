# E01 API Model Candidate Binding — Resolved v1.0

## Decision
Main E01 screening uses one provider and changes only the model identity. This avoids provider transport / schema implementation differences becoming a second independent variable.

| Candidate | Provider | Model | Role | Reasoning | Temperature |
|---|---|---|---|---|---|
| CAND-E01-API-A | OpenAI | `gpt-5.6-sol` | quality ceiling | medium | unset |
| CAND-E01-API-B | OpenAI | `gpt-5.6-terra` | balanced | medium | unset |
| CAND-E01-API-C | OpenAI | `gpt-5.6-luna` | cost-sensitive | medium | unset |

Common runtime: Responses API, standard processing, `reasoning.context=current_turn`, JSON-Schema structured output, pro mode OFF.

A cross-provider benchmark is deliberately deferred. It becomes a separate extension only after provider adapters are implemented and held to the same schema / privacy / retry contract.

The GPT-5.6 catalog exposed only aliases in the retrieved snapshot listing, so the runner must record request time, model id, response metadata, SDK version, and any provider-returned effective version for reproducibility.
