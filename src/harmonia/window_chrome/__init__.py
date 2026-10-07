"""The window's fixed parts: header, navigation pane, player bar, expanded player."""

from .expanded_player import build_expanded_player
from .header import build_header
from .player_bar import build_player_bar
from .sidebar import build_sidebar

__all__ = ["build_expanded_player", "build_header", "build_player_bar", "build_sidebar"]
