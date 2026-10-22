"""Material Design 3 Expressive player controls, as Caelestia Shell's dashboard draws them.

The Material Design 3 theme turns the player bar into Caelestia's media
player: a wavy progress slider, artwork cut to a slowly turning cookie shape
and a row of buttons that morph and push their neighbours when pressed. The
geometry, timings and curves are Caelestia's (StyledSlider.qml, WavyLine,
CoverArt.qml, ButtonBase.qml, ButtonRow); colours come from CSS, so the
theme (and Caelestia's own scheme) decide them.

Every widget also works in the plain mode the other themes use: the slider
is then hidden in favour of the GtkScale it mirrors, the artwork is drawn
unclipped and the row lays its buttons out like a centred GtkBox.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import gi

gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Graphene, Gsk, Gtk  # noqa: E402

# Material 3 Expressive motion (Caelestia's Tokens.anim): duration in ms and
# the cubic Bézier of each curve; the spatial ones overshoot.
FAST_SPATIAL = (350, (0.42, 1.67, 0.21, 0.9))
DEFAULT_SPATIAL = (500, (0.38, 1.21, 0.22, 1.0))

# Caelestia's MaterialShape.Cookie9Sided (m3shapes, Apache-2.0): a 9-point star
# with inner radius 0.8 and corners rounded by half, rotated -90° and fitted to
# the unit square, as cubic Béziers (x0, y0, c0x, c0y, c1x, c1y, x1, y1).
COOKIE_9 = (
    (0.500000, 0.014151, 0.536488, 0.014151, 0.572976, 0.027260, 0.601873, 0.053477),
    (0.601873, 0.053477, 0.631269, 0.080147, 0.669950, 0.094226, 0.709611, 0.092691),
    (0.709611, 0.092691, 0.787589, 0.089672, 0.855122, 0.146339, 0.865690, 0.223657),
    (0.865690, 0.223657, 0.871066, 0.262982, 0.891648, 0.298631, 0.923016, 0.322948),
    (0.923016, 0.322948, 0.984692, 0.370760, 1.000000, 0.457578, 0.958397, 0.523600),
    (0.958397, 0.523600, 0.937237, 0.557180, 0.930089, 0.597718, 0.938488, 0.636510),
    (0.938488, 0.636510, 0.955001, 0.712780, 0.910922, 0.789127, 0.836614, 0.812960),
    (0.836614, 0.812960, 0.798820, 0.825083, 0.767286, 0.851542, 0.748785, 0.886657),
    (0.748785, 0.886657, 0.712410, 0.955698, 0.629569, 0.985849, 0.557326, 0.956343),
    (0.557326, 0.956343, 0.520582, 0.941335, 0.479418, 0.941335, 0.442674, 0.956343),
    (0.442674, 0.956343, 0.370431, 0.985849, 0.287589, 0.955698, 0.251214, 0.886657),
    (0.251214, 0.886657, 0.232714, 0.851542, 0.201180, 0.825082, 0.163386, 0.812960),
    (0.163386, 0.812960, 0.089078, 0.789127, 0.044999, 0.712780, 0.061512, 0.636510),
    (0.061512, 0.636510, 0.069911, 0.597718, 0.062763, 0.557180, 0.041603, 0.523600),
    (0.041603, 0.523600, 0.000000, 0.457578, 0.015309, 0.370759, 0.076984, 0.322948),
    (0.076984, 0.322948, 0.108353, 0.298631, 0.128935, 0.262982, 0.134310, 0.223657),
    (0.134310, 0.223657, 0.144878, 0.146339, 0.212411, 0.089672, 0.290389, 0.092691),
    (0.290389, 0.092691, 0.330050, 0.094226, 0.368731, 0.080147, 0.398127, 0.053477),
    (0.398127, 0.053477, 0.427024, 0.027260, 0.463512, 0.014151, 0.500000, 0.014151),
)


def cubic_bezier(x1: float, y1: float, x2: float, y2: float) -> Callable[[float], float]:
    """The easing function of CSS's cubic-bezier(); y may overshoot."""

    def sample(t: float, a: float, b: float) -> float:
        return 3 * a * (1 - t) ** 2 * t + 3 * b * (1 - t) * t**2 + t**3

    def solve(x: float) -> float:
        low, high, t = 0.0, 1.0, x
        for _ in range(24):
            value = sample(t, x1, x2)
            if abs(value - x) < 1e-5:
                return t
            if value < x:
                low = t
            else:
                high = t
            t = (low + high) / 2
        return t

    def ease(x: float) -> float:
        if x <= 0:
            return 0.0
        if x >= 1:
            return 1.0
        return sample(solve(x), y1, y2)

    return ease


class Tween:
    """One animated number, stepped by a widget's frame clock."""

    def __init__(self, widget: Gtk.Widget, value: float, motion, on_change: Callable[[], None]):
        self.widget = widget
        self.value = self.target = value
        self.duration_us = motion[0] * 1000
        self.ease = cubic_bezier(*motion[1])
        self.on_change = on_change
        self._start = value
        self._started = 0
        self._tick = 0

    def animate_to(self, target: float) -> None:
        if target == self.target and not self._tick:
            return
        self.target = target
        clock = self.widget.get_frame_clock()
        if clock is None or not self.widget.get_mapped():
            self.jump_to(target)
            return
        self._start, self._started = self.value, clock.get_frame_time()
        if not self._tick:
            self._tick = self.widget.add_tick_callback(self._step)

    def jump_to(self, value: float) -> None:
        if self._tick:
            self.widget.remove_tick_callback(self._tick)
            self._tick = 0
        self.value = self.target = value
        self.on_change()

    def _step(self, _widget, clock) -> bool:
        progress = min(1.0, (clock.get_frame_time() - self._started) / self.duration_us)
        self.value = self._start + (self.target - self._start) * self.ease(progress)
        self.on_change()
        if progress >= 1:
            self._tick = 0
            return False
        return True


class FrameLoop:
    """``step(elapsed_us)`` and a redraw on every frame while running and on screen."""

    def __init__(self, widget: Gtk.Widget, step: Callable[[int], None]) -> None:
        self.widget = widget
        self.step = step
        self.running = False
        self._tick = 0
        self._last_frame = 0
        widget.connect("map", lambda *_: self._update())
        widget.connect("unmap", lambda *_: self._update())

    def set_running(self, running: bool) -> None:
        self.running = running
        self._update()

    def _update(self) -> None:
        active = self.running and self.widget.get_mapped()
        if active and not self._tick:
            self._last_frame = 0
            self._tick = self.widget.add_tick_callback(self._frame)
        elif not active and self._tick:
            self.widget.remove_tick_callback(self._tick)
            self._tick = 0

    def _frame(self, _widget, clock) -> bool:
        now = clock.get_frame_time()
        self.step(now - self._last_frame if self._last_frame else 0)
        self._last_frame = now
        self.widget.queue_draw()
        return True


def point(x: float, y: float) -> Graphene.Point:
    value = Graphene.Point()
    value.init(x, y)
    return value


def rect(x: float, y: float, width: float, height: float) -> Graphene.Rect:
    return Graphene.Rect().init(x, y, max(0.0, width), max(0.0, height))


def _place(child: Gtk.Widget, x: float, y: float, width: float, height: float) -> None:
    transform = Gsk.Transform.new().translate(point(x, y))
    child.allocate(max(0, round(width)), max(0, round(height)), -1, transform)


class ExpressiveSlider(Gtk.Widget):
    """Caelestia's StyledSlider, over the GtkAdjustment of a GtkScale.

    The filled part is a wavy line (or a bar when ``wavy`` is off), then a gap,
    the tall handle, another gap and the track, which ends in a stop dot. The
    fill eases to each new value with an overshoot; dragging moves it
    directly. ``on_interaction(fraction)`` reports where the user put it:
    while dragging when ``interaction_on_move``, otherwise on release.
    """

    __gtype_name__ = "HarmoniaExpressiveSlider"

    TRACK = 12  # implicitHeight
    HANDLE_WIDTH = 4
    GAP = 4  # Tokens.spacing.extraSmall
    WAVE_FREQUENCY = 5
    WAVE_DURATION_US = 2_000_000

    def __init__(
        self,
        adjustment: Gtk.Adjustment,
        *,
        wavy: bool,
        interaction_on_move: bool = True,
        on_interaction: Callable[[float], None] | None = None,
        on_drag: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__()
        self.add_css_class("md-slider")
        self.adjustment = adjustment
        self.wavy = wavy
        self.interaction_on_move = interaction_on_move
        self.on_interaction = on_interaction
        self.on_drag = on_drag
        self.set_hexpand(True)
        self.set_valign(Gtk.Align.CENTER)
        self.set_cursor_from_name("pointer")
        self._parts = {}
        for name in ("fill", "handle", "track", "stop"):
            part = Gtk.Box()
            part.add_css_class(f"md-slider-{name}")
            part.set_can_target(False)
            part.set_parent(self)
            self._parts[name] = part
        self._parts["fill"].set_visible(not wavy)
        self._dragging = False
        self._press_x = 0.0
        self._press_fraction = 0.0
        self._drag_fraction = 0.0
        self.fill = Tween(self, self._fraction(), DEFAULT_SPATIAL, self.queue_allocate)
        self.handle_scale = Tween(self, 3.0, FAST_SPATIAL, self.queue_allocate)
        self._phase = 0.0
        self._wave = FrameLoop(self, self._advance_wave)
        adjustment.connect("value-changed", lambda *_: self._value_changed())
        adjustment.connect("changed", lambda *_: self._value_changed())
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.add_controller(drag)

    def do_dispose(self) -> None:
        for part in self._parts.values():
            part.unparent()
        self._parts = {}
        Gtk.Widget.do_dispose(self)

    # --- State ------------------------------------------------------------

    def _fraction(self) -> float:
        lower, upper = self.adjustment.get_lower(), self.adjustment.get_upper()
        if upper - lower <= 0:
            return 0.0
        return min(1.0, max(0.0, (self.adjustment.get_value() - lower) / (upper - lower)))

    def _value_changed(self) -> None:
        if not self._dragging:
            self.fill.animate_to(self._fraction())

    def set_animate_wave(self, animate: bool) -> None:
        """The wave flows while the music plays and holds still when it pauses."""
        self._wave.set_running(animate and self.wavy)

    def _advance_wave(self, elapsed_us: int) -> None:
        self._phase = (self._phase + elapsed_us / self.WAVE_DURATION_US) % 1.0

    # --- Input ------------------------------------------------------------

    def _drag_begin(self, _gesture, x: float, _y: float) -> None:
        if not self.is_sensitive():
            return
        self._dragging = True
        self._press_x = x
        self._press_fraction = self._drag_fraction = self.fill.value
        self.handle_scale.animate_to(3.5)

    def _drag_update(self, _gesture, dx: float, _dy: float) -> None:
        if not self._dragging:
            return
        width = max(1, self.get_width())
        self._drag_fraction = min(1.0, max(0.0, self._press_fraction + dx / width))
        self.fill.jump_to(self._drag_fraction)
        if self.on_drag:
            self.on_drag(self._drag_fraction)
        if self.interaction_on_move and self.on_interaction:
            self.on_interaction(self._drag_fraction)

    def _drag_end(self, _gesture, dx: float, _dy: float) -> None:
        if not self._dragging:
            return
        width = max(1, self.get_width())
        final = self._drag_fraction if dx != 0 else min(1.0, max(0.0, (self._press_x + dx) / width))
        self._dragging = False
        self.handle_scale.animate_to(3.0)
        self.fill.animate_to(final)
        if self.on_interaction:
            self.on_interaction(final)

    # --- Layout and drawing ----------------------------------------------

    def do_measure(self, orientation, _for_size):
        if orientation == Gtk.Orientation.HORIZONTAL:
            return 48, 200, -1, -1
        # The handle (three tracks tall) overflows the slider, as in Caelestia.
        return self.TRACK * 2, self.TRACK * 2, -1, -1

    def _geometry(self) -> tuple[float, float, float]:
        """Width the fill can use, the fill's width and the handle's x."""
        usable = max(0.0, self.get_width() - self.HANDLE_WIDTH - self.GAP)
        filled = usable * self.fill.value
        return usable, filled, filled + self.GAP

    def do_size_allocate(self, width: int, height: int, _baseline: int) -> None:
        track = self.TRACK
        center = height / 2
        _usable, filled, handle_x = self._geometry()
        handle_height = track * self.handle_scale.value
        _place(
            self._parts["handle"],
            handle_x,
            center - handle_height / 2,
            self.HANDLE_WIDTH,
            handle_height,
        )
        track_x = handle_x + self.HANDLE_WIDTH + self.GAP
        remaining = max(0.0, width - track_x)
        opacity = min(remaining, track) / track
        self._parts["track"].set_opacity(opacity)
        _place(
            self._parts["track"], track_x, center - track * opacity / 2, remaining, track * opacity
        )
        dot = 4 * opacity
        self._parts["stop"].set_opacity(opacity)
        _place(self._parts["stop"], width - dot - 4 * opacity, center - dot / 2, dot, dot)
        _place(self._parts["fill"], 0, center - track / 2, filled, track)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        if self.wavy:
            self._snapshot_wave(snapshot)
        for part in self._parts.values():
            if part.get_visible():
                self.snapshot_child(part, snapshot)

    def _snapshot_wave(self, snapshot: Gtk.Snapshot) -> None:
        """WavyLine.paintLinear: a sine of the full length, drawn up to the fill."""
        line = int(self.TRACK * 0.7)
        usable, filled, _handle_x = self._geometry()
        if filled < line:
            return
        amplitude = line * 0.5
        phase = self._phase * 2 * math.pi
        center = self.get_height() / 2
        frequency = self.WAVE_FREQUENCY * 2 * math.pi / (usable or 1)
        builder = Gsk.PathBuilder.new()
        x = line // 2
        end = filled - line / 2
        builder.move_to(x, center + amplitude * math.sin(phase + frequency * x))
        while x + 1 <= end:
            x += 1
            builder.line_to(x, center + amplitude * math.sin(phase + frequency * x))
        stroke = Gsk.Stroke.new(line)
        stroke.set_line_cap(Gsk.LineCap.ROUND)
        stroke.set_line_join(Gsk.LineJoin.ROUND)
        snapshot.append_stroke(builder.to_path(), stroke, self.get_color())


def cookie_path(size: float, angle: float, x: float = 0.0, y: float = 0.0) -> Gsk.Path:
    """COOKIE_9 scaled to ``size``, turned ``angle`` degrees about its centre."""
    radians = math.radians(angle)
    cos, sin = math.cos(radians), math.sin(radians)
    half = size / 2

    def at(u: float, v: float) -> tuple[float, float]:
        dx, dy = (u - 0.5) * size, (v - 0.5) * size
        return x + half + dx * cos - dy * sin, y + half + dx * sin + dy * cos

    builder = Gsk.PathBuilder.new()
    builder.move_to(*at(COOKIE_9[0][0], COOKIE_9[0][1]))
    for _x0, _y0, c0x, c0y, c1x, c1y, x1, y1 in COOKIE_9:
        builder.cubic_to(*at(c0x, c0y), *at(c1x, c1y), *at(x1, y1))
    builder.close()
    return builder.to_path()


class CookieCover(Gtk.Widget):
    """Caelestia's CoverArt: the artwork masked by a cookie that turns while playing.

    The shape turns, not the picture: one turn every 23.5 s, backwards, and it
    stops where it is on pause. A faint outline separates it from the
    background (the CSS ``color``).
    """

    __gtype_name__ = "HarmoniaCookieCover"

    TURN_US = 23_500_000

    def __init__(self, child: Gtk.Widget) -> None:
        super().__init__()
        self.add_css_class("md-cover")
        self.child = child
        child.set_parent(self)
        self.shaped = False
        self.angle = 0.0
        self._spinning = False
        self._spin = FrameLoop(self, self._turn)

    def do_dispose(self) -> None:
        if self.child is not None:
            self.child.unparent()
            self.child = None
        Gtk.Widget.do_dispose(self)

    def set_shaped(self, shaped: bool) -> None:
        self.shaped = shaped
        self._spin.set_running(shaped and self._spinning)
        self.queue_draw()

    def set_spinning(self, spinning: bool) -> None:
        self._spinning = spinning
        self._spin.set_running(self.shaped and spinning)

    def _turn(self, elapsed_us: int) -> None:
        self.angle = (self.angle - 360 * elapsed_us / self.TURN_US) % 360

    def do_measure(self, orientation, for_size):
        return self.child.measure(orientation, for_size)

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        self.child.allocate(width, height, baseline, None)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        if not self.shaped:
            self.snapshot_child(self.child, snapshot)
            return
        width, height = self.get_width(), self.get_height()
        size = min(width, height)
        path = cookie_path(size, self.angle, (width - size) / 2, (height - size) / 2)
        snapshot.append_stroke(path, Gsk.Stroke.new(2), self.get_color())
        snapshot.push_fill(path, Gsk.FillRule.WINDING)
        self.snapshot_child(self.child, snapshot)
        snapshot.pop()


class ButtonRow(Gtk.Widget):
    """Caelestia's ButtonRow: one height for all, and a pressed button pushes its neighbours.

    In the expressive mode a pressed button grows by 24 px (shapeMorph); the
    buttons beside it give the width back, by half when they are in the
    middle of the row. Buttons marked ``fill`` share the width that is left.
    Out of it, the row is a centred GtkBox.
    """

    __gtype_name__ = "HarmoniaButtonRow"

    HEIGHT = 48  # a large icon (32 px) and Tokens.padding.small around it
    MEDIUM = 40  # the same with a medium icon
    MORPH = 24
    WIDTH = 344

    def __init__(self, spacing: int = 10, expressive_spacing: int = 4, width: int = WIDTH) -> None:
        super().__init__()
        self.add_css_class("md-button-row")
        self.set_halign(Gtk.Align.CENTER)
        self.spacing = spacing
        self.width = width
        self.expressive_spacing = expressive_spacing
        self.expressive = False
        self._children: list[Gtk.Widget] = []
        self._fill: set[Gtk.Widget] = set()
        self._narrow: set[Gtk.Widget] = set()
        self._morph: dict[Gtk.Widget, Tween] = {}

    def append(self, child: Gtk.Widget, *, fill: bool = False, narrow: bool = False) -> None:
        """``narrow``: a toggle with a medium icon, 0.9 times as wide as tall."""
        child.set_parent(self)
        self._children.append(child)
        if fill:
            # The Filled button of the row (play); the others are tonal.
            self._fill.add(child)
            child.add_css_class("md-fill")
        if narrow:
            self._narrow.add(child)
            child.add_css_class("md-narrow")
        self._morph[child] = Tween(child, 0.0, FAST_SPATIAL, self.queue_allocate)
        child.connect("state-flags-changed", self._pressed_changed)
        child.connect("notify::visible", lambda *_: self.queue_resize())

    def do_dispose(self) -> None:
        for child in self._children:
            child.unparent()
        self._children = []
        Gtk.Widget.do_dispose(self)

    def set_expressive(self, expressive: bool) -> None:
        self.expressive = expressive
        self.set_hexpand(expressive)
        for child, tween in self._morph.items():
            tween.jump_to(0.0)
            # The row gives every button its height; centred, GTK would
            # shrink them back to their icons.
            child.set_valign(Gtk.Align.FILL if expressive else Gtk.Align.CENTER)
        self.queue_resize()

    def _pressed_changed(self, child: Gtk.Widget, _previous) -> None:
        if not self.expressive:
            return
        pressed = bool(child.get_state_flags() & Gtk.StateFlags.ACTIVE)
        self._morph[child].animate_to(self.MORPH if pressed and child.is_sensitive() else 0.0)

    def _shown(self) -> list[Gtk.Widget]:
        return [child for child in self._children if child.get_visible()]

    def _base_width(self, child: Gtk.Widget) -> int:
        return round(self.MEDIUM * 0.9) if child in self._narrow else self.HEIGHT

    def do_measure(self, orientation, _for_size):
        children = self._shown()
        if self.expressive:
            if orientation == Gtk.Orientation.VERTICAL:
                return self.HEIGHT, self.HEIGHT, -1, -1
            spacing = self.expressive_spacing * max(0, len(children) - 1)
            minimum = sum(self._base_width(child) for child in children) + spacing
            return minimum, max(minimum, self.width), -1, -1
        sizes = [child.measure(orientation, -1)[:2] for child in children]
        if orientation == Gtk.Orientation.VERTICAL:
            return (
                max((s[0] for s in sizes), default=0),
                max((s[1] for s in sizes), default=0),
                -1,
                -1,
            )
        spacing = self.spacing * max(0, len(children) - 1)
        return (
            sum(s[0] for s in sizes) + spacing,
            sum(s[1] for s in sizes) + spacing,
            -1,
            -1,
        )

    def do_size_allocate(self, width: int, height: int, _baseline: int) -> None:
        children = self._shown()
        if not self.expressive:
            natural = [child.measure(Gtk.Orientation.HORIZONTAL, -1)[1] for child in children]
            x = max(0, (width - sum(natural) - self.spacing * max(0, len(children) - 1)) / 2)
            for child, child_width in zip(children, natural, strict=True):
                child_height = child.measure(Gtk.Orientation.VERTICAL, child_width)[1]
                _place(child, x, (height - child_height) / 2, child_width, child_height)
                x += child_width + self.spacing
            return
        count = len(children)
        spacing = self.expressive_spacing * max(0, count - 1)
        row = min(width, max(self.width, self.do_measure(Gtk.Orientation.HORIZONTAL, -1)[0]))
        reserved = sum(self._base_width(c) for c in children if c not in self._fill)
        fills = max(1, sum(1 for c in children if c in self._fill))
        per_fill = (row - spacing - reserved) / fills
        bases = [per_fill if c in self._fill else self._base_width(c) for c in children]
        x = (width - row) / 2
        y = (height - self.HEIGHT) / 2
        for index, child in enumerate(children):
            previous = self._morph[children[index - 1]].value if index > 0 else 0.0
            following = self._morph[children[index + 1]].value if index < count - 1 else 0.0
            # Edge items push by the full amount, items in the middle by half.
            if index > 1:
                previous /= 2
            if index < count - 2:
                following /= 2
            child_width = bases[index] + self._morph[child].value - previous - following
            _place(child, x, y, child_width, self.HEIGHT)
            x += child_width + self.expressive_spacing
