"""STELLA's own look (T81): one stylesheet, applied by main().

Drawn from the icon: gold sparkles (#e8a90c stroke, #ffc93c fill)
on dark surfaces. One accent, dark panels, light text — never
generic Qt grey, never pure white (entry 023: pure white glows
and blooms). Every window carries the look because the sheet is
applied to the application, not to one window.

Motion is cheap on purpose (audit #9, entries 001/002): the only
animation is the button press dip — scale to 0.97 over 150 ms,
a short geometry animation on press only. No per-frame blur, no
layout thrash, nothing that costs frames on the Vega 3.

Qt-free to import except for the dip filter, which needs QtCore /
QtWidgets: the stylesheet itself is a plain string so tests can
read it without a QApplication.
"""

from __future__ import annotations

# The palette, from the icon (assets/stella.svg).
GOLD = "#e8a90c"          # icon stroke: the one accent
LIGHT_GOLD = "#ffc93c"    # icon fill: highlights
SURFACE = "#1c1c1c"       # window background
PANEL = "#262626"         # cards, menus
INPUT = "#2e2e2e"         # fields, lists
BORDER = "#3d3d3d"         # quiet borders
TEXT = "#e6e6e6"           # main text (not pure white)
MUTED = "#9a9a9a"          # help lines, hints
DISABLED = "#777777"      # greyed-out text

STELLA_STYLESHEET = f"""
QMainWindow, QDialog {{
    background-color: {SURFACE};
    color: {TEXT};
}}
QWidget {{
    /* The base (T81): EVERY plain widget carries the dark surface.
       Without this, bare pages and scroll viewports keep Fusion's
       light background while labels render light text - the
       session header band went light-on-light (drive 2026-11-14).
       Specific rules below win for their widgets (same
       specificity, later in the sheet). */
    background-color: {SURFACE};
    color: {TEXT};
}}
QLabel {{
    background-color: transparent;
}}
QToolTip {{
    background-color: #333333;
    color: {TEXT};
    border: 1px solid #555555;
}}
QFrame#card {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
QPushButton {{
    background-color: #333333;
    border: 1px solid #4a4a4a;
    border-radius: 4px;
    padding: 6px 12px;
    color: {TEXT};
}}
QPushButton:hover {{
    border: 1px solid {GOLD};
}}
QPushButton:pressed {{
    background-color: #242424;
}}
QPushButton:disabled {{
    color: {DISABLED};
    border-color: #333333;
}}
QPushButton:checked {{
    border: 2px solid {GOLD};
    background-color: #3a3016;
}}
QPushButton#goButton {{
    background-color: {GOLD};
    color: #1c1c1c;
    border: 1px solid {GOLD};
}}
QPushButton#goButton:hover {{
    background-color: {LIGHT_GOLD};
    border: 1px solid {LIGHT_GOLD};
}}
QPushButton#goButton:disabled {{
    background-color: #333333;
    color: {DISABLED};
    border-color: #333333;
}}
QPushButton#sectionHeader {{
    background-color: transparent;
    border: none;
    text-align: left;
    font-weight: bold;
    padding: 4px 2px;
}}
QPushButton#sectionHeader:hover {{
    border: none;
    color: {LIGHT_GOLD};
}}
QPushButton#sectionHeader:checked {{
    border: none;
    background-color: transparent;
}}
QLineEdit, QPlainTextEdit, QTextBrowser {{
    background-color: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px;
    selection-background-color: {GOLD};
    selection-color: #1c1c1c;
}}
QComboBox {{
    background-color: {INPUT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px;
}}
QComboBox QAbstractItemView {{
    background-color: {INPUT};
    selection-background-color: {GOLD};
    selection-color: #1c1c1c;
}}
QTreeWidget, QListWidget {{
    background-color: #232323;
    border: 1px solid {BORDER};
    border-radius: 4px;
    alternate-background-color: #282828;
}}
QTreeWidget::item:selected, QListWidget::item:selected {{
    background-color: {GOLD};
    color: #1c1c1c;
}}
QTreeWidget::item:hover, QListWidget::item:hover {{
    background-color: #333333;
}}
QProgressBar {{
    background-color: #333333;
    border: 1px solid {BORDER};
    border-radius: 4px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{
    background-color: {GOLD};
    border-radius: 3px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid #555555;
    border-radius: 3px;
    background-color: {INPUT};
}}
QCheckBox::indicator:checked {{
    background-color: {GOLD};
    border: 1px solid {GOLD};
}}
QMenuBar {{
    background-color: {SURFACE};
    color: {TEXT};
}}
QMenuBar::item:selected {{
    background-color: #333333;
}}
QMenu {{
    background-color: {PANEL};
    border: 1px solid {BORDER};
}}
QMenu::item:selected {{
    background-color: {GOLD};
    color: #1c1c1c;
}}
QScrollArea {{
    border: none;
    background-color: transparent;
}}
QScrollBar:vertical, QScrollBar:horizontal {{
    background-color: {PANEL};
    border: none;
}}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
    background-color: #4a4a4a;
    border-radius: 4px;
    min-height: 20px;
    min-width: 20px;
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
    width: 0px;
}}
QSplitter::handle {{
    background-color: {BORDER};
}}
/* The focus ring (T82, entry 023): unmistakable, 2 px gold, on
   every focusable family - never the faint default outline. */
QPushButton:focus, QLineEdit:focus, QComboBox:focus,
QTreeWidget:focus, QListWidget:focus, QTextBrowser:focus,
QPlainTextEdit:focus, QCheckBox:focus {{
    border: 2px solid {GOLD};
    outline: none;
}}
QPushButton#sectionHeader:focus {{
    border: none;
    color: {LIGHT_GOLD};
}}
"""


def apply_stella_style(app) -> None:
    """Apply the one stylesheet to the application (T81)."""
    app.setStyleSheet(STELLA_STYLESHEET)


# The reduced-motion flag (T145/T149): when set, the finish
# moment and the job-picker morph are plain instant swaps, and
# the press dip does not run. T147 wires this flag to the
# Settings "Ease of use" preset; until then it defaults off.
_REDUCED_MOTION = False


def set_reduced_motion(value: bool) -> None:
    """Set the reduced-motion flag (T147's preset writes it)."""
    global _REDUCED_MOTION
    _REDUCED_MOTION = bool(value)


def reduced_motion() -> bool:
    """True when reduced motion is on."""
    return _REDUCED_MOTION


# The app font before any text-size preset (T147): captured on
# the first apply_text_size call, so the preset is idempotent —
# turning larger text on twice never grows the font twice.
_BASE_FONT = None


def apply_text_size(app, larger: bool) -> None:
    """Larger text (T147): the app font grows by 3 points, or
    returns to the default. The default family is kept; widgets
    with explicit px sizes stay as they are (they are already
    large)."""
    global _BASE_FONT
    if _BASE_FONT is None:
        _BASE_FONT = app.font()
    from PySide6.QtGui import QFont

    font = QFont(_BASE_FONT)
    if larger:
        if _BASE_FONT.pointSize() > 0:
            font.setPointSize(_BASE_FONT.pointSize() + 3)
        else:
            font.setPixelSize(_BASE_FONT.pixelSize() + 4)
    app.setFont(font)


class PressDipFilter:
    """Button press dip (entry 001): scale to 0.97 over 150 ms.

    Installed as an event filter on the QApplication by main(), so
    every button in every window dips. The dip is one short geometry
    animation — 75 ms down to 97%, 75 ms back — on press only. The
    animation ends at the original geometry, so layout state is
    untouched and nothing re-lays-out mid-press.

    Implemented as a plain object holding a QObject filter so this
    module stays importable without Qt: the Qt classes are imported
    lazily in install().
    """

    def __init__(self, app):
        from PySide6.QtCore import QEvent, QObject, QPropertyAnimation
        from PySide6.QtWidgets import QPushButton

        self._QEvent = QEvent
        self._QObject = QObject
        self._QPropertyAnimation = QPropertyAnimation
        self._QPushButton = QPushButton
        self._animations: dict = {}
        self._filter = self._make_filter()
        app.installEventFilter(self._filter)

    def _make_filter(self):
        outer = self

        class _Filter(self._QObject):
            def eventFilter(self, obj, event):  # noqa: N802 - Qt name
                if (
                    event.type() == outer._QEvent.MouseButtonPress
                    and isinstance(obj, outer._QPushButton)
                    and obj.isEnabled()
                ):
                    outer._dip(obj)
                return super().eventFilter(obj, event)

        return _Filter()

    def _dip(self, button):
        if reduced_motion():
            return  # the Less motion preset (T147): no dip
        if button in self._animations:
            return  # already dipping; one dip per press
        rect = button.geometry()
        if rect.width() <= 0 or rect.height() <= 0:
            return
        shrunk = rect.adjusted(
            int(rect.width() * 0.015),
            int(rect.height() * 0.015),
            -int(rect.width() * 0.015),
            -int(rect.height() * 0.015),
        )
        animation = self._QPropertyAnimation(button, b"geometry")
        animation.setDuration(150)
        animation.setKeyValueAt(0.0, rect)
        animation.setKeyValueAt(0.5, shrunk)
        animation.setKeyValueAt(1.0, rect)
        animation.finished.connect(
            lambda: self._animations.pop(button, None)
        )
        self._animations[button] = animation
        animation.start()


def install_press_dips(app) -> PressDipFilter:
    """Install the button press dip on the application (T81)."""
    return PressDipFilter(app)
