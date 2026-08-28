from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QML = ROOT / "src" / "harmonia" / "qml"


def test_compact_navigation_reuses_the_real_sidebar_in_an_overlay_drawer() -> None:
    source = (QML / "Main.qml").read_text(encoding="utf-8")

    assert "globalDrawer:" not in source
    assert "Kirigami.GlobalDrawer" not in source
    assert "Controls.Drawer {" in source
    assert "id: compactNavigationDrawer" in source
    assert "parent: Controls.Overlay.overlay" in source
    assert "edge: Qt.LeftEdge" in source
    assert "modal: true" in source
    assert "interactive: !root.wideLayout" in source
    assert "contentItem: NavigationSidebar {" in source
    assert "onNavigationRequested: compactNavigationDrawer.open()" in source
    assert source.count("compactNavigationDrawer.close()") >= 4
    assert source.count("NavigationSidebar {") == 2


def test_compact_navigation_button_has_a_visible_breeze_fallback() -> None:
    source = (QML / "AppTopBar.qml").read_text(encoding="utf-8")
    button = source.split("id: navigationButton", 1)[1].split("Controls.ToolButton {", 1)[0]

    assert "visible: !root.wideLayout" in button
    assert 'source: "application-menu"' in button
    assert 'fallback: "view-list"' in button
    assert "isMask: false" in button
    assert "sidebar-show" not in source


def test_compact_navigation_does_not_reintroduce_starred_likes() -> None:
    source = (QML / "Main.qml").read_text(encoding="utf-8")
    assert '"starred"' not in source
