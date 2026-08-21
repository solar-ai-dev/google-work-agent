# Repository Architecture v1.1 — Normative Detail

> **Parent Source:** `../16-repository-architecture-source.md` v1.1  
> **Status:** NORMATIVE_SUBORDINATE_DETAIL  
> **Effective:** 2026-08-22  
> **Project Source count:** this directory does **not** add separate Project Source entries.

## Authority

This directory expands Repository Architecture v1.1. If a subordinate detail conflicts with the parent Source, the parent Source wins.

Behavioral semantics remain owned by 01–15, Domain State Transition Contract, State Transition Test Matrix, and executable SQL constraints.

## Read order

```text
01-spec-to-code-mapping.md
02-directory-ownership.md
03-naming-grammar.md
04-artifact-taxonomy.md
05-dependency-import-export-rules.md
06-langgraph-state-ownership.md
07-connector-api-persistence-grammar.md
08-single-authority-compat.md
09-test-fixture-migration-grammar.md
10-error-event-configuration-naming.md
11-refactor-playbook.md
12-architecture-enforcement.md
13-exception-registry.md
```

## Frozen decisions

```text
D1 semantic-owner Domain organization
D2 operation-per-file Domain lifecycle/guards
D3 <Verb><Object>Handler Application use cases
D4 owner-local contracts
D5 _compat forbidden on main
```

## Mandatory implementation sequence

```text
SPEC TERM
→ CANONICAL TERM
→ SEMANTIC OWNER
→ LAYER
→ OPERATION
→ PATH
→ FILE
→ SYMBOL
→ TEST PATH
→ semantic repository search
→ single production authority confirmation
```

A new implementation must not be created beside an existing semantic authority. Report `SEMANTIC_AUTHORITY_COLLISION` instead.
