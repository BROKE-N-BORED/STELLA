#!/usr/bin/env python3
"""Double-click install launcher (T64).

"Install Stella.desktop" runs this file with the system python3; it
runs install.sh from this folder with bash, then waits for Enter so
the result stays on screen after the terminal would otherwise close.

Stdlib only: the venv does not exist yet when this runs.
"""

import os
import subprocess
import sys


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    rc = subprocess.call(["bash", os.path.join(here, "install.sh")])
    print()
    if rc == 0:
        print("Install finished. Press Enter to close this window.")
    else:
        print("Install did not finish (see above). Press Enter to close.")
    try:
        input()
    except EOFError:
        # No terminal attached (scripted run): do not hang, and do
        # not die with a traceback either.
        pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
