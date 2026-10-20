"""Architecture checks for the app-owned project layout."""

import ast
from pathlib import Path

from capacity_twin_core.runtime.database_paths import PROJECT_ROOT, load_config

APPLICATION_NAMES = {
    "capacity_home",
    "capacity_assistant",
    "data_explorer",
    "data_operations",
    "decision_intelligence",
}
INTERNAL_PACKAGES = APPLICATION_NAMES | {"capacity_twin_core"}


def test_every_app_owns_config_and_readme() -> None:
    """Keep app documentation and settings beside the app."""
    for app_name in APPLICATION_NAMES:
        app_dir = PROJECT_ROOT / app_name
        assert (app_dir / "config.yaml").is_file()
        assert (app_dir / "README.md").is_file()
    for module_name in ("generator", "pipeline"):
        module_dir = PROJECT_ROOT / "data_operations" / module_name
        assert (module_dir / "config.yaml").is_file()
        assert (module_dir / "README.md").is_file()
    core_dir = PROJECT_ROOT / "src" / "capacity_twin_core"
    assert (core_dir / "config.yaml").is_file()
    assert (core_dir / "README.md").is_file()


def test_obsolete_containers_are_absent() -> None:
    """Keep applications at the root and shared code under the src package."""
    for folder_name in (
        "apps",
        "agentic",
        "backend",
        "config",
        "frontend",
        "data_generator",
        "data_pipeline",
        "ml_workflows",
    ):
        assert not (PROJECT_ROOT / folder_name).exists()


def test_default_runtime_data_stays_outside_repository() -> None:
    """Generated databases and logs must not dirty the Git project."""
    config = load_config()
    runtime_home = Path(config["paths"]["runtime_home"]).resolve()
    assert runtime_home != PROJECT_ROOT.resolve()
    assert PROJECT_ROOT.resolve() not in runtime_home.parents


def test_apps_do_not_import_other_apps_private_code() -> None:
    """Keep root applications separate, except for the home composition layer."""
    violations: list[str] = []

    for owner in APPLICATION_NAMES:
        allowed = {owner, "capacity_twin_core"}
        if owner == "capacity_home":
            allowed.update(
                {
                    "capacity_assistant",
                    "data_explorer",
                    "data_operations",
                    "decision_intelligence",
                }
            )

        for source_path in (PROJECT_ROOT / owner).rglob("*.py"):
            if "tests" in source_path.parts:
                continue
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            imported_modules = [
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            ]
            imported_modules.extend(
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            for module_name in imported_modules:
                imported_owner = module_name.split(".", maxsplit=1)[0]
                if imported_owner in INTERNAL_PACKAGES and imported_owner not in allowed:
                    violations.append(
                        f"{source_path.relative_to(PROJECT_ROOT)} imports {module_name}"
                    )

    assert violations == []
