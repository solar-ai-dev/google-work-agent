# Spec → Code Mapping Rules

## 1. Purpose

An Agent must be able to convert a specification term into a target code path without first browsing for similar filenames.

Canonical algorithm:

```text
SPEC TERM
→ CANONICAL DOMAIN TERM
→ LAYER
→ OWNER PACKAGE
→ OPERATION
→ FILENAME
→ SYMBOL
```

## 2. Canonical vocabulary

| Specification term | Code token |
|---|---|
| Run | `run` |
| Plan | `plan` |
| Action | `action` |
| Approval | `approval` |
| Claim | `claim` |
| ExecutionAttempt | `execution_attempt` |
| Verification | `verification` |
| Recovery | `recovery` |
| ResourceRef | `resource_ref` |
| Conversation | `conversation` |
| Request Understanding | `request_understanding` |
| Tool Route | `tool_routing` |
| Retrieval | `retrieval` |
| Work Analysis | `work_analysis` |
| Planning | `planning` |
| Review | `review` |

Do not invent alternate nouns for these concepts.

## 3. Deterministic path formulas

### Domain semantic rule

```text
<Aggregate> invariant
→ domain/<aggregate>/invariants.py

<Aggregate> transition
→ domain/<aggregate>/transitions.py

<Aggregate> command semantics
→ domain/<aggregate>/commands.py
```

### Application command

```text
<Verb><Object>
→ application/use_cases/<owner>/<verb>_<object>.py
```

Examples:

```text
BlockRun
→ application/use_cases/run/block_run.py

ApproveAction
→ application/use_cases/approval/approve_action.py

RecoverUnknownResult
→ application/use_cases/recovery/recover_unknown_result.py
```

### Agent semantic stage

```text
Request Understanding → application/agents/request_understanding/
Tool Route            → application/agents/tool_routing/
Retrieval             → application/agents/retrieval/
Work Analysis         → application/agents/work_analysis/
Planning              → application/agents/planning/
Review                → application/agents/review/
```

### LangGraph node

```text
<role>.<operation>
→ adapters/langgraph/subgraphs/<role>/nodes/<operation>_node.py
```

### Repository

```text
<Aggregate>Repository port
→ ports/persistence/<aggregate>_repository.py

SQLite implementation
→ adapters/persistence/sqlite/repositories/<aggregate>_repository.py
```

### Provider/connector operation

```text
<provider>/<product>/<resource>/<verb>
→ adapters/connectors/<provider>/<product>/<resource>/<verb>_<resource>.py
```

Example:

```text
Google Gmail Message CREATE
→ adapters/connectors/google/gmail/messages/create_message.py
```

## 4. Semantic search rule

Filename search is only the first hint.

Before concluding a capability is absent, search by:

- Domain aggregate mutation,
- repository mutation,
- state-field writer,
- tool/effect enum,
- external endpoint/effect,
- transition/result code,
- caller chain,
- exports/re-exports.

Different names can still mean duplicate authority.

## 5. Stop condition

If more than one existing implementation has equivalent semantics:

```text
SEMANTIC_AUTHORITY_COLLISION
```

Do not create a third.
