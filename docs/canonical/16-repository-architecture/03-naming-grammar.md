# 03. Naming Grammar

**Normative detail of the current Repository Architecture Source.**

Python files/packages/functions/variables use `snake_case`; classes/types use `PascalCase`; constants and enum/error-code values use `UPPER_SNAKE_CASE`.

Application capability:

```
<verb>_<object>.py
<Verb><Object>Command | Query
<Verb><Object>Result
<Verb><Object>Handler
```

Deterministic/domain operation:

```
<verb>_<object>.py
<verb>_<object>()
```

Domain transition symbols use `transition_<verb>_<object>()`; Domain guard symbols use `guard_<verb>_<object>()`.

Agent semantic operations use `application/agents/<role>/<verb>_<object>.py` with the same `<verb>_<object>()` symbol.

Router:

```
routing/route_after_<stage>.py
route_after_<stage>()
```

Projection:

```
projections/<scope>_projection.py
project_<scope>_input()
```

Connector operation:

```
<verb>_<resource>.py
<Verb><Resource>Operation
```

LangGraph node:

```
<verb>_<object>_node.py
<verb>_<object>_node()
```

Production implementation generation/version prefixes/suffixes are prohibited: `canonical_*`, `production_*`, `legacy_*`, `new_*`, `old_*`, `final_*`, `*_v2.py`, `*_v3.py`, `*_r2.py`, `*_r21.py`. Contract type versions remain allowed.

Generic production filenames `runtime.py`, `service.py`, `manager.py`, `processor.py`, `engine.py`, `handler.py`, `helpers.py`, `utils.py`, `common.py`, `shared.py`, `misc.py`, `config.py`, and broad `errors.py` are prohibited unless an explicit architecture-role grammar or Exception Registry entry allows the exact path.

Owner-local role nouns follow deterministic grammar: `<subject>_registry.py → <Subject>Registry`; `<subject>_<condition>_error.py → <Subject><Condition>Error`. Validator/resolver/builder/assembler/mapper/normalizer operations use their semantic verb as the filename and function prefix rather than generic role buckets.
