# Repository Architecture — Canonical Index

> Status: CANONICAL_FOR_REFACTOR  
> Version: 1.0  
> Effective: 2026-08-22

This directory owns **repository placement, naming grammar, dependency direction, and production-authority uniqueness**.

It does not redefine business behavior owned by other canonical documents.

## Read order

1. `01-spec-to-code-mapping.md`
2. `02-directory-ownership.md`
3. `03-naming-grammar.md`
4. `04-dependency-direction.md`
5. `05-langgraph-state-ownership.md`
6. `06-single-authority-legacy-policy.md`
7. `07-refactor-playbook.md`
8. `08-architecture-enforcement.md`

## Precedence

For semantic behavior:
- use the concern-specific canonical document,
- Domain/SQL executable constraints remain authoritative where applicable.

For **where code belongs, what it is named, what it may import, and whether duplicate production authority is allowed**, this repository-architecture contract is authoritative.

## Four invariants

```text
DIRECTORY TELLS OWNERSHIP
FILENAME TELLS RESPONSIBILITY
IMPORT TELLS DEPENDENCY DIRECTION
ONE CAPABILITY HAS ONE PRODUCTION AUTHORITY
```

## Target root

```text
src/google_work_agent/
├── domain/
├── application/
│   ├── agents/
│   ├── use_cases/
│   └── orchestration/
├── ports/
├── adapters/
│   ├── langgraph/
│   ├── persistence/
│   ├── connectors/
│   ├── llm/
│   └── mcp/
├── api/
├── launcher/
└── evaluation/
```

A current file being somewhere else does not make that location canonical.
