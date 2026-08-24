# 09. Test · Fixture · Migration Grammar

**Normative detail of the current Repository Architecture Source.**

Unit tests mirror production ownership.

```
src/.../<verb>_<object>.py
→ tests/unit/.../test_<verb>_<object>.py
```

Frontend/release-source exceptions are exact and owned by `02 Directory Ownership` manifests:

```text
frontend/src/app/<responsibility>.ts(x)
→ frontend/tests/app/<responsibility>.test.ts(x)

frontend/src/features/<owner>/<responsibility>.ts(x)
→ frontend/tests/features/<owner>/<responsibility>.test.ts(x)

frontend/src/features/<owner>/api/<verb>_<object>.ts
→ frontend/tests/features/<owner>/api/<verb>_<object>.test.ts

installer/windows/<responsibility>.py
→ tests/installer/windows/test_<responsibility>.py

release/<responsibility>.py | release/profiles/<profile>.py
→ tests/release/test_<responsibility>.py | tests/release/profiles/test_<profile>.py
```

Test functions:

```
test_<operation>_<object>__<condition>__<expected>
```

Existing `TST-<AREA>-<NNN>` IDs remain traceability identifiers and must not become production filenames.

Code fixtures live under semantic `tests/fixtures/<area>/`. Current checked-in provider/resource static fixtures use exactly:

```text
tests/fixtures/data/<provider>/<resource>/<scenario>.json
```

The serialization is UTF-8 strict JSON; `.yaml`, `.toml`, `.pickle`, ad-hoc extensionless blobs, and a second generic fixture root are not current static-fixture authorities. `provider`, `resource`, and the semantic fixture family/required boundary are derived from 12 Test; `<scenario>` is a stable lower-snake-case test-data instance identifier.

**Concrete `<scenario>` filenames are not a closed Repository Architecture identifier set.** They are verification-data instances that may grow when 12 adds a new case while preserving the same ownership/serialization grammar. Canonical architecture closes the static-fixture grammar and the 12-owned required fixture families; it does not require every individual scenario filename to be enumerated. A concrete filename becomes normative only when a current owner document explicitly names that file.

Evaluation datasets are not test fixtures and live only under the `evaluation/` root defined by 13/16.

Migration filename grammar is `NNNN_<semantic_change>.sql`. Applied migrations are immutable; structural refactoring never renames or rewrites them.

## Structural test ownership and migration rules

Test migration follows production semantic ownership; keeping legacy-path tests as the primary behavioral owner means the capability migration is incomplete.

Final closure requires:

```
canonical unit-test owner path exists
+ behavior/contract coverage preserved
+ legacy test imports of migrated production paths = 0
+ legacy test ownership tree for migrated capability = 0
```

An architecture test may contain an old path or banned filename as a literal negative assertion. Such a literal is enforcement evidence, not a production/test ownership exception.

Applied SQL migrations remain immutable. Structural refactoring must not rename, rewrite, squash, or relocate an applied migration to make repository naming look canonical. New persistent invariants require a new migration in numeric order. Therefore structural closure and DB migration history closure are separate checks:

- repository code/tests must satisfy current canonical ownership;
- executable applied migration history remains intact and checksum-valid.

### Required-operation manifest enforcement

Repository validation must consume a **canonical required-operation manifest** derived from the current semantic mapping authority, not from files discovered in the implementation tree.

For Application use cases, the manifest key is:

```
semantic_owner + operation + canonical_path + canonical_symbol + canonical_test_path
```

For Agent semantic operations, the manifest key additionally preserves the current 06/15 responsibility identity mapping.

Validation uses closed-set comparison:

```
required manifest operations
= canonical production authorities found
= canonical test owners expected
```

Missing required operations, unexpected extra live authorities, or multiple files satisfying one manifest capability are structural failures. A scaffold-only file does not satisfy the manifest unless the canonical symbol is live and the intended callers are closed.
