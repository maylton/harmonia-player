from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "src" / "harmonia" / "qml"


def test_expanded_player_primary_control_uses_native_centered_icon() -> None:
    source = (QML / "ExpandedPlayer.qml").read_text(encoding="utf-8")
    assert "id: primaryPlayButton" in source
    assert "background: Rectangle" in source
    assert "Layout.preferredWidth: Kirigami.Units.gridUnit * 3" in source
    assert "icon.width: Kirigami.Units.iconSizes.medium" in source
    assert "icon.height: Kirigami.Units.iconSizes.medium" in source
    assert "icon.color: Kirigami.Theme.textColor" in source
    assert "contentItem: Kirigami.Icon" not in source


def test_lyrics_toolbar_forces_action_icons_to_monochrome_masks() -> None:
    source = (QML / "LyricsView.qml").read_text(encoding="utf-8")
    assert "id: providerButton" in source
    assert "id: translateButton" in source
    assert "id: copyButton" in source
    assert 'source: "accessories-dictionary"' in source
    assert source.count("isMask: true") >= 3
    assert source.count("color: Kirigami.Theme.textColor") >= 6


def test_lyrics_toolbar_reserves_space_for_custom_button_content() -> None:
    source = (QML / "LyricsView.qml").read_text(encoding="utf-8")
    assert "Layout.preferredHeight: childrenRect.height" in source
    assert "providerContent.implicitWidth + leftPadding + rightPadding" in source
    assert "translateContent.implicitWidth + leftPadding + rightPadding" in source
    assert "copyContent.implicitWidth + leftPadding + rightPadding" in source


def test_sidebar_glyphs_share_a_slightly_larger_box() -> None:
    source = (QML / "SidebarButton.qml").read_text(encoding="utf-8")
    assert "Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium" in source
    assert "Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium" in source
    assert "Layout.preferredWidth: Kirigami.Units.iconSizes.small\n" not in source
