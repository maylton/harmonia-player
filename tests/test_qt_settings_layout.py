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


def test_settings_section_preserves_native_kde_icon_without_badge_background() -> None:
    source = (QML / "SettingsSection.qml").read_text(encoding="utf-8")
    assert "default property alias contentData: body.data" in source
    assert "Kirigami.Theme.alternateBackgroundColor" in source
    assert "Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium" in source
    assert "isMask: false" in source
    assert "source: root.iconName" in source
    assert "Kirigami.Theme.highlightColor" not in source
    assert "radius: width / 2" not in source
    assert source.count("Rectangle {") == 1
    assert "Kirigami.Separator" in source


def test_account_settings_reuses_profile_exposed_for_top_bar() -> None:
    source = (QML / "SettingsPage.qml").read_text(encoding="utf-8")
    assert "backend.accountAvatarUrl" in source
    assert "backend.accountName" in source
    assert "backend.accountEmail" in source


def test_backup_restore_requires_confirmation_before_destructive_action() -> None:
    source = (QML / "SettingsPage.qml").read_text(encoding="utf-8")
    restore_dialog = source.split("id: restoreDialog", 1)[1]

    assert "root.pendingRestoreUrl = selectedFile" in restore_dialog
    assert "restoreConfirmDialog.open()" in restore_dialog
    assert "id: restoreConfirmDialog" in source
    assert 'title: "Restaurar backup?"' in source
    assert "Controls.Dialog.Ok | Controls.Dialog.Cancel" in source
    assert "backend.restoreBackup(root.pendingRestoreUrl.toString())" in source
    assert "onAccepted: backend.restoreBackup(selectedFile.toString())" not in source


def test_listen_together_share_link_has_explicit_copy_action() -> None:
    source = (QML / "IntegrationsSettings.qml").read_text(encoding="utf-8")
    assert "id: sessionLinkField" in source
    assert 'text: "Copiar"' in source
    assert 'icon.name: "edit-copy"' in source
    assert "sessionLinkField.selectAll()" in source
    assert "sessionLinkField.copy()" in source
    assert "sessionLinkField.deselect()" in source
