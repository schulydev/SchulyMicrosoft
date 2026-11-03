"""The onion rule, read from the imports of every file under src/: dependencies only point inward."""

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
THIRD_PARTY_FOR = {
    "domain": set(),
    "application": {"mediatorx", "pydantic"},
}
# The composition root: the only part of `api` that may name concrete infrastructure classes.
COMPOSITION_ROOT = SRC / "api" / "extensions"


def imports_of(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def ring_of(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if parts[0] == "src" and len(parts) > 1 else None


def broken_rules(path: Path, ring: str) -> list[str]:
    broken = []
    for module in imports_of(path):
        target = ring_of(module)
        top = module.split(".")[0]
        if target is None and top != "src":
            if ring in THIRD_PARTY_FOR and top not in sys.stdlib_module_names and top not in THIRD_PARTY_FOR[ring]:
                broken.append(f"{ring} imports {module}")
            continue
        if ring == "domain" and target != "domain":
            broken.append(f"domain imports {module}")
        elif ring == "application" and target not in ("domain", "application"):
            broken.append(f"application imports {module}")
        elif ring == "infrastructure" and target == "api":
            broken.append(f"infrastructure imports {module}")
        elif ring == "api" and target == "infrastructure" and COMPOSITION_ROOT not in path.parents:
            broken.append(f"api outside the composition root imports {module}")
    return broken


def test_dependencies_only_point_inward():
    broken = {}
    for ring in ("domain", "application", "infrastructure", "api"):
        for path in (SRC / ring).rglob("*.py"):
            rules = broken_rules(path, ring)
            if rules:
                broken[str(path.relative_to(SRC))] = rules
    assert broken == {}


def test_every_file_under_src_belongs_to_a_ring():
    strays = [p.relative_to(SRC) for p in SRC.rglob("*.py") if p.relative_to(SRC).parts[0] not in ("domain", "application", "infrastructure", "api") and p.name != "__init__.py"]
    assert strays == []


def test_the_rule_catches_a_violation(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text("from src.infrastructure.logging_config import LoggerNames\nimport fastapi\nfrom outnote import GraphError\n", encoding="utf-8")
    assert len(broken_rules(bad, "application")) == 3
    assert len(broken_rules(bad, "domain")) == 3
    assert any("infrastructure" in rule for rule in broken_rules(bad, "api"))
