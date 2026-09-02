from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

INSTALLER_FILES = {
    "installer/windows/installer_definition.py": {"WindowsInstallerDefinition"},
    "installer/windows/uninstall_definition.py": {"WindowsUninstallDefinition"},
    "installer/windows/upgrade_policy.py": {"WindowsUpgradePolicy"},
}
RELEASE_FILES = {
    "release/profiles/api_only.py": {"build_api_only_profile"},
    "release/profiles/local_capable.py": {"build_local_capable_profile"},
    "release/assemble_application_bundle.py": {"assemble_application_bundle"},
    "release/build_windows_installer.py": {"build_windows_installer"},
    "release/generate_release_manifest.py": {
        "ReleaseManifestFileV1",
        "ReleaseManifestV1",
        "generate_release_manifest",
    },
    "release/generate_model_manifest.py": {
        "ApprovedModelEntryV1",
        "ModelManifestV1",
        "generate_model_manifest",
    },
    "release/sign_release_artifacts.py": {"sign_release_artifacts"},
}


def test_canonical_installer_release__files_and_symbols__exist_exactly_once() -> None:
    for relative, symbols in {**INSTALLER_FILES, **RELEASE_FILES}.items():
        path = REPO_ROOT / relative
        assert path.is_file(), relative
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = {
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        }
        assert symbols <= found


def test_legacy_release_authority__and_product_runtime__imports_are_absent() -> None:
    assert not (REPO_ROOT / "src/google_work_agent/adapters/runtime/build_manifest.py").exists()
    assert not (REPO_ROOT / "src/google_work_agent/adapters/runtime/paths.py").exists()
    script_tree = ast.parse((REPO_ROOT / "scripts/build_release.py").read_text(encoding="utf-8"))
    script_functions = {node.name for node in script_tree.body if isinstance(node, ast.FunctionDef)}
    assert script_functions == {"main"}
    for path in (REPO_ROOT / "src/google_work_agent").rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert "import release" not in content
        assert "from release" not in content
        assert "import installer" not in content
        assert "from installer" not in content


def test_release_cli_uses__only_the_launcher__embedded_manifest_trust_root() -> None:
    source = (REPO_ROOT / "scripts/build_release.py").read_text(encoding="utf-8")

    assert "EMBEDDED_RELEASE_PUBLIC_KEY_PEM" in source
    assert "--embedded-release-public-key" not in source
