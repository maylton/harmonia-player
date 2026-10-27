"""Worker threads hand their results to the main loop with deliver_to_main.

GLib.idle_add runs below the frame clock: on Windows' software renderer every
frame took longer than the refresh interval, idle callbacks never ran, and a
newly picked track never started (ui.deliver_to_main).
"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "harmonia"


def _thread_targets(tree: ast.AST) -> set[str]:
    """Names of the functions a module runs on a thread or an executor."""
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        candidates = [k.value for k in node.keywords if k.arg == "target"]
        if called in ("submit", "_optional_worker", "_social_worker"):
            candidates += node.args
        for value in candidates:
            if isinstance(value, ast.Name):
                names.add(value.id)
            elif isinstance(value, ast.Attribute):
                names.add(value.attr)
    return names


def _idle_adds_on_worker_threads(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    targets = _thread_targets(tree)
    found = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "idle_add"
            and not any(k.arg == "priority" for k in node.keywords)
        ):
            continue
        current = parents.get(node)
        while current is not None:
            if isinstance(current, ast.FunctionDef) and current.name in targets:
                found.append(f"{path.relative_to(PACKAGE)}:{node.lineno}")
                break
            current = parents.get(current)
    return found


def test_worker_threads_deliver_results_ahead_of_redraws():
    found = [
        site
        for path in sorted(PACKAGE.rglob("*.py"))
        for site in _idle_adds_on_worker_threads(path)
    ]
    assert found == [], "use ui.deliver_to_main for these"
