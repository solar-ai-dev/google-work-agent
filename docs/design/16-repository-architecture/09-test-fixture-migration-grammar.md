# 09. Test · Fixture · Migration Grammar

> Parent: Repository Architecture Source v1.4  
> Behavioral test requirements remain owned by 12 Test.

## Unit-test mirror

```text
src/.../<verb>_<object>.py
→ tests/unit/.../test_<verb>_<object>.py
```

Test function grammar:

```text
test_<operation>_<object>__<condition>__<expected>
```

Existing `TST-<AREA>-<NNN>` identifiers remain traceability IDs and must not become production filenames.

## Integration tests

Integration tests are organized by boundary/scenario owner rather than mirroring one implementation file:

```text
tests/integration/workflow/
tests/integration/persistence/
tests/integration/connectors/
tests/integration/api/
```

## Code fixtures

```text
tests/fixtures/<area>/<semantic_noun>.py
make_<noun>()
```

## Static fixture data

```text
tests/fixtures/data/<provider>/<resource>/<scenario>.<ext>
```

Evaluation datasets remain separate from product regression fixtures.

## Migration naming

```text
NNNN_<semantic_change>.sql
```

Do not use vague names such as `fix`, `update`, or `final`.

Applied migrations are immutable historical/checksum artifacts. Structural refactoring must not rename or rewrite existing applied migrations.
