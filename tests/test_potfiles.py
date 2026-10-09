import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRANSLATED = re.compile(r"\b(?:_|ngettext)\(\s*[\"']")


def test_every_module_with_translatable_text_is_in_potfiles():
    listed = set((ROOT / "po" / "POTFILES").read_text(encoding="utf-8").split())
    using = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / "harmonia").rglob("*.py")
        if TRANSLATED.search(path.read_text(encoding="utf-8"))
    }
    assert sorted(using - listed) == []
