# 04. Artifact Taxonomy

> Parent: Repository Architecture Source v1.1

Generic `DTO` naming is prohibited. The name must state the artifact’s actual role.

| Artifact | Canonical meaning |
|---|---|
| `Command` | state-changing Application input |
| `Query` | read-only Application input |
| `Result` | Use Case outcome |
| `Request` / `Response` | external/wire boundary only |
| `Candidate` | unvalidated local intermediate |
| `Draft` | reviewable/proposable artifact |
| `Snapshot` | immutable point-in-time binding |
| `Projection` | allowlisted downstream view |
| `Receipt` | durable evidence of an applied command/user decision |
| `Ref` | stable identity/reference |
| `Handle` | runtime-local opaque lookup |
| `Policy` | product allow/deny rule |
| `Guard` | Domain transition precondition |
| `Validator` | artifact/contract validity check |
| `Resolver` | deterministic meaning/target resolution |
| `Builder` | low-level artifact construction |
| `Assembler` | composition of prepared artifacts |
| `Mapper` | representation translation |
| `Normalizer` | semantic-preserving canonicalization |
| `Registry` | registered-set lookup authority |
| `Repository` | persistence abstraction only |
| `Port` | boundary abstraction |
| `Adapter` | concrete Port implementation only |

`Factory` is exceptional and requires true runtime-selected implementation creation.

## Candidate / Draft / Snapshot / Projection

These are not synonyms.

```text
Candidate  not yet validated/final
Draft      concrete proposal/review target
Snapshot   immutable factual binding at a point in time
Projection allowlisted view for another boundary/node
```

## Receipt / Token / Ref / Handle

```text
Receipt durable decision/application evidence
Token   opaque capability/authorization value
Ref     stable reference
Handle  runtime-local opaque lookup
```

`Approval`/`ApprovalSnapshot` are business facts. `claim_token` is execution authority. Do not invent `approval_token` as execution authority.
