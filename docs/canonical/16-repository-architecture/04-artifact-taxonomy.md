# 04. Artifact Taxonomy

**Normative detail of the current Repository Architecture Source.**

Generic `DTO` naming is prohibited. Use the actual artifact role.

- `Command`: state-changing application input
- `Query`: read-only application input
- `Result`: use-case outcome
- `Request` / `Response`: wire/API boundary only
- `Candidate`: unvalidated local intermediate
- `Draft`: reviewable/proposable artifact
- `Snapshot`: immutable point-in-time binding
- `Projection`: allowlisted downstream view
- `Receipt`: durable evidence of applied command/user decision
- `Ref`: stable reference
- `Handle`: runtime-local opaque lookup
- `Policy`: product allow/deny rule
- `Guard`: domain transition precondition
- `Validator`: artifact/contract validity check
- `Resolver`: deterministic meaning/target resolution
- `Builder`: low-level construction
- `Assembler`: composition of prepared artifacts
- `Mapper`: representation translation
- `Normalizer`: semantic-preserving canonicalization
- `Registry`: registered-set lookup authority
- `Repository`: persistence abstraction only
- `Port`: boundary abstraction
- `Adapter`: concrete Port implementation

`Factory` is exceptional and requires true runtime-selected implementation creation.
