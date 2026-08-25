from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "src" / "harmonia" / "qml"


def test_settings_page_uses_grouped_reusable_sections() -> None:
    source = (QML / "SettingsPage.qml").read_text(encoding="utf-8")
    assert source.count("SettingsSection {") == 5
    assert 'title: "Conta"' in source
    assert 'title: "Aparência"' in source
    assert 'title: "Streaming"' in source
    assert 'title: "Áudio"' in source
    assert 'title: "Dados e backup"' in source
    assert "Kirigami.Separator { width: parent.width }" not in source


def test_settings_section_keeps_native_kde_theme_and_symbolic_icon() -> None:
    source = (QML / "SettingsSection.qml").read_text(encoding="utf-8")
    assert "default property alias contentData: body.data" in source
    assert "Kirigami.Theme.alternateBackgroundColor" in source
    assert "Kirigami.Theme.highlightColor" in source
    assert "isMask: true" in source
    assert "Kirigami.Separator" in source


def test_account_settings_reuses_profile_exposed_for_top_bar() -> None:
    source = (QML / "SettingsPage.qml").read_text(encoding="utf-8")
    assert "backend.accountAvatarUrl" in source
    assert "backend.accountName" in source
    assert "backend.accountEmail" in source
