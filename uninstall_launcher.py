#!/usr/bin/env python3
"""Double-click uninstall launcher (R63).

"Uninstall Stella.desktop" runs this file with the system python3;
it runs uninstall.sh from this folder with bash, then waits for
Enter so the result stays on screen after the terminal would
otherwise close. The script itself asks about the data in
~/.stella first (default: keep it) — the terminal the desktop
file asks for is what makes the question answerable by clicking.

Stdlib only: the venv is gone by the time this finishes, and may
already be broken when it starts.
"""

import os
import subprocess
import sys


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    rc = subprocess.call(["bash", os.path.join(here, "uninstall.sh")])
    print()
    if rc == 0:
        print("Uninstall finished. Press Enter to close this window.")
    else:
        print("Uninstall did not finish (see above). Press Enter to close.")
    try:
        input()
    except EOFError:
        # No terminal attached (scripted run): do not hang, and do
        # not die with a traceback either.
        pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
