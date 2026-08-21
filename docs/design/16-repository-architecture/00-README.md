# Repository Architecture v1.4 — Normative Detail

> **Parent Source:** `../16-repository-architecture-source.md` v1.4  
> **Status:** NORMATIVE_SUBORDINATE_DETAIL  
> **Effective:** 2026-08-22  
> **Project Source count:** this directory does **not** add separate Project Source entries.

## Authority

This directory expands Repository Architecture v1.4. If a subordinate detail conflicts with the parent Source, the parent Source wins.

Behavioral semantics remain owned by 01–15, Domain State Transition Contract, State Transition Test Matrix, and executable SQL constraints.

Repository naming/placement/import-export realization/single-production-authority questions are owned only by Repository Architecture Source 16. Other Project Sources may define semantic identifiers they own, but do not create an independent repository naming authority.

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
D2 operation-per-file Domain lifecycle transitions and guards
D3 <Verb><Object>Handler Application use cases
D4 owner-local contracts; no global catch-all contracts package
D5 _compat forbidden on main
D6 Agent semantic responsibility operation-per-file
D7 LangGraph routing operation-per-file under routing/route_after_<stage>.py
D8 closed-world naming: no undocumented naming/placement discretion
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

If a construct cannot be mapped by the published grammar, stop and version the Exception Registry rather than inventing a local convention.
