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
    assert (
        "contentItem: Kirigami.Icon"
        not in source.split("id: primaryPlayButton", 1)[1].split("Controls.ToolButton {", 1)[0]
    )


def test_lyrics_toolbar_forces_action_icons_to_monochrome_masks() -> None:
    source = (QML / "LyricsView.qml").read_text(encoding="utf-8")
    assert "id: providerButton" in source
    assert "id: translateButton" in source
    assert "id: copyButton" in source
    assert 'source: "accessories-dictionary"' in source
    assert source.count("isMask: true") >= 3
    assert source.count("color: Kirigami.Theme.textColor") >= 6


def test_lyrics_toolbar_uses_abstract_buttons_without_native_ghost_content() -> None:
    source = (QML / "LyricsView.qml").read_text(encoding="utf-8")
    assert "Layout.preferredHeight: childrenRect.height" in source
    assert source.count("Controls.AbstractButton {") >= 3
    assert "providerContent.implicitWidth + leftPadding + rightPadding" in source
    assert "translateContent.implicitWidth + leftPadding + rightPadding" in source
    assert "copyContent.implicitWidth + leftPadding + rightPadding" in source
    assert "property string actionText" in source


def test_sidebar_keeps_plasma_icons_native_sized_with_explicit_app_glyph_override() -> None:
    component = (QML / "SidebarButton.qml").read_text(encoding="utf-8")
    navigation = (QML / "NavigationSidebar.qml").read_text(encoding="utf-8")

    assert "property real iconSize: Kirigami.Units.iconSizes.small" in component
    assert "property bool monochromeIcon: false" in component
    assert "Layout.preferredWidth: root.iconSize" in component
    assert "Layout.preferredHeight: root.iconSize" in component
    assert "isMask: root.monochromeIcon" in component

    liked = navigation.split('text: "Músicas curtidas"', 1)[1].split("SidebarButton {", 1)[0]
    assert 'iconName: "love-symbolic"' in liked
    assert "iconSize: Kirigami.Units.iconSizes.smallMedium" in liked
    assert "monochromeIcon: true" in liked

    settings = navigation.split('text: "Preferências"', 1)[1].split("SidebarButton {", 1)[0]
    assert 'iconName: "settings-configure"' in settings
    assert 'fallbackIcon: "configure-symbolic"' in settings
    assert "iconSize:" not in settings
    assert "monochromeIcon:" not in settings


def test_sidebar_uses_recognizable_breeze_like_and_settings_icons() -> None:
    source = (QML / "NavigationSidebar.qml").read_text(encoding="utf-8")
    assert 'iconName: "love-symbolic"' in source
    assert 'fallbackIcon: "emblem-favorite-symbolic"' in source
    assert 'iconName: "settings-configure"' in source
    assert 'fallbackIcon: "configure-symbolic"' in source


def test_player_uses_clickable_shared_seek_slider_and_theme_driven_like_icon() -> None:
    compact = (QML / "PlayerBar.qml").read_text(encoding="utf-8")
    expanded = (QML / "ExpandedPlayer.qml").read_text(encoding="utf-8")
    seek = (QML / "SeekSlider.qml").read_text(encoding="utf-8")

    assert "Controls.Slider {" in seek
    assert "MouseArea {" in seek
    assert "root.setValueFromX(mouse.x)" in seek
    assert "root.seekRequested(Math.round(root.value))" in seek
    assert "if (!mouseSeeking)" in seek
    assert "preventStealing: true" in seek

    for source in (compact, expanded):
        assert "import org.kde.plasma.components" not in source
        assert "SeekSlider {" in source
        assert "playbackPosition: backend.position" in source
        assert "playbackDuration: backend.duration" in source
        assert "backend.seek(positionMs)" in source
        assert source.count("Controls.Slider {") >= 1
        assert "onPressedChanged: if (!pressed) backend.seek" not in source
        assert 'source: "love-symbolic"' in source
        assert "Kirigami.Theme.highlightColor" in source
        assert "palette.highlight:" not in source


def test_compact_player_bounds_seek_and_volume_widths() -> None:
    source = (QML / "PlayerBar.qml").read_text(encoding="utf-8")

    assert "readonly property bool showSecondaryControls: width >= 920" in source
    assert "readonly property bool showVolumeControls: width >= 1080" in source
    assert "readonly property real seekMinWidth:" in source
    assert "readonly property real seekPreferredWidth:" in source
    assert "readonly property real seekMaxWidth:" in source
    assert "Layout.minimumWidth: root.seekMinWidth" in source
    assert "Layout.preferredWidth: root.seekPreferredWidth" in source
    assert "Layout.maximumWidth: root.seekMaxWidth" in source
    assert "readonly property real volumeMinWidth:" in source
    assert "readonly property real volumePreferredWidth:" in source
    assert "readonly property real volumeMaxWidth:" in source
    assert "Layout.minimumWidth: root.volumeMinWidth" in source
    assert "Layout.preferredWidth: root.volumePreferredWidth" in source
    assert "Layout.maximumWidth: root.volumeMaxWidth" in source
    assert "spacing: Kirigami.Units.gridUnit" in source
    assert "id: centerRegion" in source
    assert "root.centerMaxWidth" in source


def test_expanded_media_visual_has_a_hard_maximum_and_replaces_cover_in_place() -> None:
    source = (QML / "ExpandedPlayer.qml").read_text(encoding="utf-8")
    assert "readonly property real mediaMaxWidth: 900" in source
    assert "readonly property real availableMediaHeight" in source
    assert "readonly property real mediaAspectWidth" in source
    assert "availableMediaHeight * mediaAspectWidth" in source
    assert "readonly property real boundedMediaWidth" in source
    assert "ColumnLayout {\n                        id: expandedContent" in source
    assert "id: detailsColumn" in source
    assert "anchors.top: parent.top" in source
    assert "Layout.fillWidth: false" in source
    assert "width: expandedContent.boundedMediaWidth" in source
    assert "Layout.maximumWidth: expandedContent.boundedMediaWidth" in source
    assert "Layout.maximumHeight: root.mediaMaxWidth" in source
    assert "clip: true" in source
    assert 'visible: videoBackend.mode !== "video" || videoBackend.loading' in source
    assert 'opacity: videoBackend.mode === "video" && !videoBackend.loading' in source
