# 07. Connector · API · Persistence Grammar

> Parent: Repository Architecture Source v1.1  
> Wire/tool semantics remain owned by 07 Interface and concern-specific security/policy contracts.

## Connector operation

```text
adapters/connectors/<provider>/<product>/<resource>/<verb>_<resource>.py
<Verb><Resource>Operation
```

Examples:

```text
gmail_create_draft
→ adapters/connectors/google/gmail/drafts/create_draft.py
→ CreateDraftOperation

gmail_search_threads
→ adapters/connectors/google/gmail/threads/search_threads.py
→ SearchThreadsOperation

calendar_query_freebusy
→ adapters/connectors/google/calendar/freebusy/query_freebusy.py
→ QueryFreeBusyOperation
```

Existing MCP wire Tool IDs remain interface-contract identifiers and are not renamed solely for repository cleanup.

A connector operation file owns one operation. Search/create/update/delete/send do not share a mixed-responsibility operation module.

## API

```text
api/routes/<plural_resource>.py
api/schemas/<plural_resource>/<verb>_<object>.py
api/dependencies/<concern>.py
```

API owns transport concerns, authentication/session dependencies, wire schema validation, and projection. It does not own Domain state transitions or business semantics.

## Persistence Port

```text
ports/persistence/<owner>_repository.py
<Owner>Repository
```

## SQLite implementation

```text
adapters/persistence/sqlite/repositories/<owner>_repository.py
SQLite<Owner>Repository
```

`Repository` is reserved for persistence abstraction/implementation. A Repository must not become a workflow/Application service.
