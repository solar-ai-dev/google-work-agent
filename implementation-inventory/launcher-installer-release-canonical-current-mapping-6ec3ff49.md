# Google Work Agent — Launcher / Installer / Release Canonical ↔ Current Mapping

**Repository:** `solar-ai-dev/google-work-agent`  
**Branch:** `refactor/canonical-architecture-migration`  
**Investigation SHA:** `6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d`  
**Current branch HEAD revalidated:** `a03432c8fa6d722c6ef93b54ff8de5aa16eeac0a`  
**HEAD moved since this mapping snapshot:** **YES**  
**Current-head reconciliation:** Launcher changed only marginally after `93f03a91`; `launcher/dev.py` remains a broad concrete bootstrap that directly composes API, LLM, LangGraph, persistence and connector pieces. The repaired Installer/Release NPA rows therefore remain required migration/artifact work. `STR-455` remains the one formal Bootstrap Secret producer row in this file.
**Mode:** `READ_ONLY_MAPPING`  
**Canonical documents modified:** **NO**

## 1. Scope closure

Canonical bounded universe from the Phase 1 Ledger:

- Repository roots: `STR-006`, `STR-008`, `STR-009` = **3**
- Launcher responsibilities: `STR-038..051` = **14**
- Installer / release responsibilities: `STR-052..061` = **10**
- Cross-manifest Bootstrap Secret row: `STR-455` = **1**
- **Total = 28 Ledger rows**

`STR-044` and `STR-455` intentionally point to the same canonical artifact (`launcher/bootstrap_secret.py`) from different structural concerns; both Ledger rows remain mapped.

At the fixed SHA, top-level canonical roots `launcher/`, `installer/`, `release/` are absent. **However, a misplaced development launcher island exists at `src/google_work_agent/launcher/`**, including broad `dev.py`, `connector_composition.py`, `development_readiness.py`, and `development_constants.py`. Exact canonical launcher/installer/release unit-test trees remain absent.

## 2. Canonical → Current mapping — 28/28

| ID | Canonical responsibility / target | Current implementation / reusable evidence | Behavior coverage | Structural coverage | Disposition | Required action |
|---|---|---|---|---|---|---|
| STR-006 | `launcher/` repository root | Canonical top-level root absent; misplaced `src/google_work_agent/launcher/` development island exists and owns broad bootstrap/composition/readiness material. | PARTIAL_MATERIAL | NONE | **MOVE/SPLIT + CREATE_MISSING** | Move/split production-worthy launcher responsibilities to top-level canonical root; do not promote dev-only concrete service composition into launcher business authority. |
| STR-008 | `installer/` repository root | No current installer source root found. | NONE | NONE | **CREATE_ROOT** | Create only from 10/09 installer contract; product runtime must never import it. |
| STR-009 | `release/` repository root | No current release-source root found; existing config/build inputs are implementation material, not release authority. | PARTIAL_MATERIAL | NONE | **CREATE_ROOT + MERGE_INPUTS** | Create canonical release tooling and consume existing build/config inputs without turning them into a second release authority. |
| STR-038 | `launcher/entrypoint.py → main()` | Broad development orchestration exists in `src/google_work_agent/launcher/dev.py`, including service/bootstrap/core wiring. | PARTIAL | NONE | **SPLIT + MOVE_RENAME + TARGETED_CORRECTION** | Extract only canonical launcher lifecycle into thin `entrypoint.py`; move concrete service composition to the single API composition root and keep dev-only setup isolated. |
| STR-039 | `acquire_single_instance()` | Repository-wide search found no single-instance/Named-Pipe lock implementation. | NONE | NONE | **CREATE** | Implement current-user single-instance lock contract from 10. |
| STR-040 | `verify_installation()` | No Release Manifest/signature/hash verifier found. | NONE | NONE | **CREATE** | Implement verification against signed Release Manifest; do not infer trust from file presence. |
| STR-041 | `SignedBuildConfigV1`, `load_signed_build_config()` | No verified Release-Manifest-derived build-config projection found. Existing config files are not trust authority. | NONE | NONE | **CREATE + REUSE CONFIG INPUTS** | Add typed projection after installation verification; preserve existing non-secret values as inputs only when manifest-covered. |
| STR-042 | `prepare_data_directory()` | `src/.../launcher/dev.py` performs development path/bootstrap preparation, but no production ACL initialization authority is closed. | PARTIAL_MATERIAL | NONE | **SPLIT + TARGETED_CORRECTION** | Reuse safe path preparation only; add Windows current-user ACL semantics in the canonical operation. |
| STR-043 | `allocate_dynamic_port()` | No canonical or equivalent loopback-port allocator found. | NONE | NONE | **CREATE** | Bind/probe loopback dynamic port without fixed/public fallback. |
| STR-044 | `create_bootstrap_secret()` | Broad dev launcher generates/provisions bootstrap secret with `secrets`; API has consumer/session infrastructure. Exact production operation absent. | NEAR_FULL_MATERIAL | NONE | **SPLIT + MOVE_RENAME** | Extract secret generation/lifetime from dev bootstrap into canonical launcher operation; API remains consumer only. |
| STR-045 | `create_service_instance_id()` | Dev launcher already materializes service instance identity from UUID primitives; generic UUID Port/adapter also exists. | NEAR_FULL_MATERIAL | NONE | **SPLIT + MOVE_RENAME** | Extract semantic launcher operation while keeping UUID generation boundary singular. |
| STR-046 | `start_service()` | Dev launcher directly boots FastAPI/core in-process for development; no verified production child-process start operation. | PARTIAL | NONE | **SPLIT + TARGETED_CORRECTION** | Reuse startup sequencing concepts but implement production child-process launch from verified artifact/config. |
| STR-047 | `wait_for_service_ready()` | `src/.../launcher/development_readiness.py` and dev bootstrap contain reusable readiness aggregation; exact launcher wait operation absent. | PARTIAL | NONE | **SPLIT + MOVE_RENAME + REUSE HEALTH CONTRACT** | Preserve readiness predicates, separate production launcher polling/wait from service-side readiness ownership. |
| STR-048 | `serve_instance_control()` | No current-user Named Pipe instance-control listener found. | NONE | NONE | **CREATE** | Implement current-user-only pipe listener; keep it launcher-local. |
| STR-049 | `request_existing_instance_ui()` | No second-launch Named Pipe client found. | NONE | NONE | **CREATE** | Implement UI-open request to existing launcher instance. |
| STR-050 | `open_product_ui()` | Existing `BrowserLauncherPort` + `DefaultBrowserLauncherAdapter.open(url)` are reusable system boundary material; launcher operation is absent. | NEAR_FULL_MATERIAL | NONE | **CREATE_THIN + REUSE** | Create thin launcher operation over BrowserLauncherPort; preserve existing adapter implementation. |
| STR-051 | `shutdown_service()` | Dev launcher has shutdown callbacks and existing ShutdownPort/ProcessShutdownAdapter provides system boundary; exact launcher operation absent. | PARTIAL_MATERIAL | NONE | **SPLIT + CREATE_THIN + REUSE** | Extract coordinated shutdown sequencing and use existing boundary; no duplicate process-shutdown implementation. |
| STR-052 | `installer/windows/installer_definition.py → WindowsInstallerDefinition` | No installer root/source found. | NONE | NONE | **CREATE** | Encode per-user Windows installer definition from 10/09; no ad-hoc packaging root. |
| STR-053 | `installer/windows/uninstall_definition.py → WindowsUninstallDefinition` | No uninstall source authority found. | NONE | NONE | **CREATE** | Encode credential-delete + DB/backup-preserve default semantics. |
| STR-054 | `installer/windows/upgrade_policy.py → WindowsUpgradePolicy` | No installer upgrade/downgrade policy source found. Migration engine is reusable implementation dependency, not installer policy. | PARTIAL_MATERIAL | NONE | **CREATE + REUSE MIGRATION CONTRACT** | Add signed in-place upgrade and downgrade-block definition without rewriting applied migrations. |
| STR-055 | `release/profiles/api_only.py → build_api_only_profile()` | Existing CPU/API-oriented requirements/config are useful inputs but no canonical profile builder authority exists. | PARTIAL_MATERIAL | NONE | **CREATE + MERGE_INPUTS** | Build exact API_ONLY artifact profile from verified inputs. |
| STR-056 | `release/profiles/local_capable.py → build_local_capable_profile()` | Existing GPU/local requirements/config and Ollama adapters are reusable inputs; no release profile builder. | PARTIAL_MATERIAL | NONE | **CREATE + MERGE_INPUTS** | Build LOCAL_CAPABLE profile without bundling Ollama/model. |
| STR-057 | `assemble_application_bundle()` | No One-folder bundle assembler found. Current frontend/backend artifacts are reusable bundle inputs. | PARTIAL_MATERIAL | NONE | **CREATE + MERGE_INPUTS** | Assemble exact release profile payload; no alternate scripts release authority. |
| STR-058 | `build_windows_installer()` | No Windows Installer build tooling found. | NONE | NONE | **CREATE** | Build from canonical installer definitions and assembled signed payload. |
| STR-059 | `ReleaseManifestV1`, `generate_release_manifest()` | No signed Release Manifest generator found. Runtime docs/contracts reference the artifact, but implementation authority is absent. | NONE | NONE | **CREATE** | Generate exact file-path/hash manifest before signing. |
| STR-060 | `ModelManifestV1`, `generate_model_manifest()` | Local-model runtime diagnostics exist, but no release-time model allowlist manifest generator. | PARTIAL_MATERIAL | NONE | **CREATE + REUSE RELEASE CONFIG** | Materialize release-approved model allowlist from current release/evaluation selection only. |
| STR-061 | `sign_release_artifacts()` | No code-signing/timestamp release operation found. | NONE | NONE | **CREATE** | Apply production signing/timestamp policy to required artifacts; signing private material remains outside product runtime. |
| STR-455 | Bootstrap Secret production → `launcher/bootstrap_secret.py` | Same current finding as STR-044; API-side bootstrap consumption exists, launcher producer absent. | PARTIAL_BOUNDARY | NONE | **CREATE + REUSE CONSUMER CONTRACT** | Same artifact as STR-044; do not create a duplicate bootstrap-secret producer. |


## 2.1 Non-Python / installed/runtime artifact rows — 9/9

| ID | Required artifact | Snapshot/current realization | Coverage | Disposition / closure |
|---|---|---|---|---|
| NPA-005 | `%INSTALL_ROOT%/manifests/installed-connectors-v1.json` | No canonical release/installer generator found; reusable connector descriptor metadata exists. | **PARTIAL_MATERIAL** | **CREATE GENERATED ARTIFACT + MERGE INPUTS**; link STR-302. |
| NPA-006 | `%INSTALL_ROOT%/manifests/signed-tool-registry-v1.json` | No canonical release artifact generator found; registry semantics exist in misplaced Domain implementation. | **PARTIAL_MATERIAL** | **MATERIALIZE AFTER STR-303 MOVE**; authenticate by release manifest hash. |
| NPA-007 | `%INSTALL_ROOT%/manifests/connectors/<connector_id>/tool-descriptor-projection-v1.json` | Exact projection absent; reusable tool/descriptor metadata exists. | **PARTIAL_MATERIAL** | **GENERATE FROM EXACT CONNECTOR SUBSET**; link STR-305. |
| NPA-008 | `release-manifest.json` | No canonical release manifest generator exists. | **MISSING** | **CREATE via STR-059**, using assembled bundle hashes. |
| NPA-009 | `release-manifest.sig` | No canonical signing/timestamp authority exists. | **MISSING** | **CREATE via STR-061**; signing private material stays outside product runtime. |
| NPA-010 | `%INSTALL_ROOT%/manifests/model-manifest-v1.json` | Runtime local-model diagnostics exist; release-time allowlist generator absent. | **PARTIAL_MATERIAL** | **CREATE/MERGE via STR-060**. |
| NPA-012 | `%LOCALAPPDATA%/GoogleWorkAgent/runtime/service-instance.json` | Dev launcher has service-instance identity material; exact production metadata artifact lifecycle not closed. | **PARTIAL_MATERIAL** | **SPLIT + MOVE + MATERIALIZE**; link STR-045. |
| NPA-013 | `%LOCALAPPDATA%/GoogleWorkAgent/runtime/service.lock` | Single-instance lock implementation absent. | **MISSING** | **CREATE with STR-039**; current-user scope only. |
| NPA-014 | `%LOCALAPPDATA%/GoogleWorkAgent/runtime/shutdown.marker` | Shutdown boundary/callback material exists, but exact crash/next-start marker authority is not closed. | **PARTIAL_MATERIAL** | **SPLIT + MATERIALIZE with STR-051**. |

## 3. Current → Canonical reverse mapping

| Current implementation/material | Canonical destination | Disposition / closure |
|---|---|---|
| `src/google_work_agent/launcher/dev.py` | Broad development bootstrap/composition/readiness/service lifecycle; hidden/misplaced launcher authority. | **SPLIT/MOVE** reusable launcher lifecycle pieces; concrete service wiring → `api/composition.py`; dev-only compatibility removed from production graph. |
| `src/google_work_agent/launcher/connector_composition.py` | Second concrete connector composition helper under launcher island. | **MERGE → `api/composition.py`**, then remove competing production composition authority. |
| `src/google_work_agent/launcher/development_readiness.py` | Reusable dev readiness logic. | **SPLIT/MOVE** production-safe readiness projection into canonical launcher/readiness dependencies; keep dev-only concerns separate. |
| `ports/system/browser_launcher_port.py` + `adapters/system/default_browser_launcher.py` | launcher `open_product_ui` dependency | **KEEP boundary**; launcher operation calls the Port, never moves adapter semantics into launcher. |
| `ports/system/shutdown_port.py` + `adapters/system/process_shutdown.py` | launcher `shutdown_service` dependency | **KEEP boundary**; add launcher coordination only. |
| `ports/system/uuid_port.py` + `adapters/system/uuid4.py` | `create_service_instance_id` implementation dependency | **KEEP** generic UUID authority; create semantic launcher operation. |
| API health/readiness routes/checks | launcher `wait_for_service_ready` remote/local-health contract | **KEEP + CONSUME**; API owns readiness projection, launcher owns wait lifecycle. |
| SQLite migration engine/history | installer upgrade + release verification dependency | **KEEP**; never move/rename applied migration history. |
| existing API/LLM/Ollama/Connector/front-end build/config inputs | API_ONLY / LOCAL_CAPABLE / bundle assembly inputs | **KEEP as inputs**, not independent release authority. |

No canonical top-level launcher root, installer root, release script tree, or alternate signing/manifest authority exists. The misplaced `src/google_work_agent/launcher/**` island is fully reverse-mapped above and must not survive as a second production composition/launcher authority after cut-over.

## 4. Test ownership

Canonical launcher tests (`tests/unit/launcher/**`), installer tests (`tests/installer/windows/**`), and release tests (`tests/release/**`) do not exist at the fixed SHA because the corresponding source roots are absent.

```text
EXACT CANONICAL TEST OWNERS = 0 / 24 operation rows
```

The three repository-root rows and duplicate STR-455 do not add independent test files.

## 5. Preservation-first implementation order

1. Create launcher root and thin orchestration seams while reusing Browser/Shutdown/UUID/Health abstractions.
2. Implement installation verification + SignedBuildConfig before service spawn.
3. Implement single-instance, data-dir/ACL, dynamic port, bootstrap secret, instance-control, start/readiness/shutdown sequence.
4. Add installer definitions and release profile builders.
5. Add bundle assembly → manifest/model manifest → signing → installer build in supply-chain order.
6. Add exact mirror tests as each operation lands.
7. Keep installer/release runtime imports at zero and enforce one launcher composition root.

## 6. Mapping verdict

```text
LAUNCHER / INSTALLER / RELEASE MAPPING = COMPLETE
CANONICAL -> CURRENT                  = CLOSED (28 STR + 9 NPA mapped)
CURRENT -> CANONICAL                  = CLOSED for inspected layer scope
AMBIGUOUS DISPOSITION                 = 0

IMPLEMENTATION COMPLETE               = NO
SINGLE AUTHORITY CLOSED               = NO
FROZEN                                = NO
INVESTIGATION SHA                     = 6ec3ff49a5f1e98afa5ff1b5a5ac4ff2fa9c5a3d
```
