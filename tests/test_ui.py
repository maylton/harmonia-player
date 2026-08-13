import pytest
from gi.repository import Gtk

from harmonia.ui import (
    ACTION_ROLES,
    ICON_SIZES,
    menu_action_button,
    set_action_role,
    set_menu_action_content,
)


class CssStub:
    def __init__(self):
        self.classes = set()

    def add_css_class(self, value):
        self.classes.add(value)

    def remove_css_class(self, value):
        self.classes.discard(value)


def test_action_role_is_exclusive():
    widget = CssStub()
    widget.classes.update({"app-action", "app-action-primary"})
    set_action_role(widget, "destructive")
    assert widget.classes == {"app-action", "app-action-destructive"}


def test_visual_primitive_scales_are_intentionally_small():
    assert {"primary", "accent", "secondary", "destructive"} == ACTION_ROLES
    assert {"sm", "md", "lg"} == ICON_SIZES


def test_unknown_action_role_is_rejected():
    with pytest.raises(ValueError):
        set_action_role(CssStub(), "special")


def test_menu_action_keeps_icon_and_visible_text_together():
    button = menu_action_button("Adicionar à playlist", "list-add-symbolic")
    content = button.get_child()

    assert isinstance(content.get_first_child(), Gtk.Image)
    assert content.get_last_child().get_label() == "Adicionar à playlist"

    set_menu_action_content(button, "Remover", "list-remove-symbolic")
    updated = button.get_child()
    assert updated.get_first_child().get_icon_name() == "list-remove-symbolic"
    assert updated.get_last_child().get_label() == "Remover"
