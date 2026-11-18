#!/usr/bin/env python3
"""Double-click repair launcher (R121).

"Repair Stella.desktop" runs this file with the system python3;
it runs the doctor (stella.doctor, stdlib only) from this folder
with bash-free system Python, then waits for Enter so the result
stays on screen after the terminal would otherwise close.

Stdlib only, and it never assumes a working venv: the doctor
module runs under the system python3, not the venv python — a
broken venv is exactly what the doctor reports, so the launcher
must still run when the venv is gone or broken. The doctor
itself checks the venv and says what to do next.
"""

import os
import subprocess
import sys


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    rc = subprocess.call(
        [sys.executable, "-m", "stella.doctor"], cwd=here
    )
    print()
    if rc == 0:
        print("Repair finished. Press Enter to close this window.")
    else:
        print("The check found problems (see above). "
              "Press Enter to close this window.")
    try:
        input()
    except EOFError:
        # No terminal attached (scripted run): do not hang, and do
        # not die with a traceback either.
        pass
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
