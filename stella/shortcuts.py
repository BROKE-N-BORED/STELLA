"""STELLA keyboard shortcuts: the one registry (R98).

Every keyboard shortcut Stella offers lives here, once: an id,
the keys, what it does, and where it works. The main window wires
its menu shortcuts and QShortcuts from this list, and the How to
Use "Shortcuts" topic is generated from it — so the help cannot
drift from the keys that actually work, and a key added here and
nowhere else fails the registry test instead of silently lying.

No em-dashes in this text (Stella rule U33) and no bare
ampersands (U11): the topic body is user-visible.
"""

from __future__ import annotations

# (id, keys, what it does, where it works). The ids are the stable
# handles the window wires from; the keys are QKeySequence text.
SHORTCUTS: list[tuple[str, str, str, str]] = [
    ("new-profile", "Ctrl+N", "New profile", "Main window"),
    ("new-project", "Ctrl+Shift+N", "New project", "Main window"),
    ("run-job", "Ctrl+G", "Run the picked job", "Main window"),
    (
        "save",
        "Ctrl+S",
        "Save the open window",
        "Main window, profile window and project window",
    ),
    ("howto", "F1", "Open How to Use Stella", "Main window"),
    ("rename", "F2", "Rename the picked row", "Main window"),
    ("chat", "F3", "Open the chat", "Main window"),
    ("quit", "Ctrl+Q", "Quit Stella", "Main window"),
]


def shortcut_for(shortcut_id: str) -> str:
    """The keys for one registered shortcut id (R98). Raises
    KeyError on an unknown id: a typo in the wiring fails loudly
    instead of registering a dead key."""
    for sid, keys, _action, _where in SHORTCUTS:
        if sid == shortcut_id:
            return keys
    raise KeyError(f"no shortcut called {shortcut_id!r}")


def shortcuts_topic_text() -> str:
    """The How to Use "Shortcuts" topic, generated from the one
    registry (R98) — never hand-written, so the help cannot drift
    from the keys that actually work."""
    lines = [
        "Everything in Stella works by clicking, but these keys "
        "do the same jobs faster. Each key works in the window "
        "named after it.",
        "",
    ]
    for _sid, keys, action, where in SHORTCUTS:
        lines.append(f"{keys}: {action}. Works in the {where}.")
    return "\n".join(lines)
