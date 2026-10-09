import re
from pathlib import Path

import pytest

QML = Path(__file__).resolve().parents[1] / "src" / "harmonia" / "qml"
LITERAL = re.compile(r'"((?:[^"\\]|\\.)*)"')
TRANSLATED = re.compile(r'i18n\.n?trf?\(\s*$|i18n\.n?trf?\("(?:[^"\\]|\\.)*",\s*$')
# Brand names, units and symbols stay the same in every language.
UNTRANSLATED = {
    "YouTube Music",
    "YouTube",
    "LRCLIB",
    "LyricsPlus",
    "AudD",
    "0:00",
    "0 ms",
    " ms",
    " st",
    "%",
}


def _user_facing(text: str) -> bool:
    if text in UNTRANSLATED or not re.search(r"[A-Za-zÀ-ú]{2}", text):
        return False
    # Icon names, keys, ids and URLs start lowercase and have no spaces.
    return not re.fullmatch(r"[a-z0-9][\w.:/-]*", text) or bool(re.search(r"[À-ú]", text))


def test_qml_text_goes_through_gettext():
    leftovers = []
    for path in sorted(QML.glob("*.qml")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.strip()
            if code.startswith(("import ", "//")):
                continue
            for match in LITERAL.finditer(line):
                before = line[: match.start()]
                if TRANSLATED.search(before) or re.search(r"(===|!==|==|indexOf\()\s*$", before):
                    continue
                if re.search(
                    r"\b(icon\.name|iconName|fallbackIcon|source|url|placeholderText)\s*:", before
                ):
                    continue
                if _user_facing(match.group(1)):
                    leftovers.append(f"{path.name}:{number}: {match.group(1)}")
    assert not leftovers, "textos sem i18n:\n" + "\n".join(leftovers)


def test_qml_status_errors_do_not_depend_on_the_message_language():
    main = (QML / "Main.qml").read_text(encoding="utf-8")
    login = (QML / "LoginDialog.qml").read_text(encoding="utf-8")
    assert "statusText.indexOf" not in main + login
    assert "backend.statusIsError" in main and "backend.statusIsError" in login


def test_qml_gettext_bridge_formats_and_survives_broken_translations():
    pytest.importorskip("PySide6")
    from harmonia.qt_i18n import QtI18n, _format

    i18n = QtI18n()
    assert i18n.trf("Carregando {title}…", {"title": "Elis & Tom"}) == "Carregando Elis & Tom…"
    assert i18n.ntr("{count} faixa", "{count} faixas", 3) == "3 faixas"
    assert i18n.ntrf("{count} item · {size}", "{count} itens · {size}", 1, {"size": "2 MB"}) == (
        "1 item · 2 MB"
    )
    assert _format("Olá {nome}", {}) == "Olá {nome}"
