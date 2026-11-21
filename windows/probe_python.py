"""Check whether a Python interpreter can run the DocForge Windows UI.

No third-party packages are needed. In diagnostic mode emit a readable
reason for rejection. Ordinary mode keeps the protocol used by install.ps1.
"""
import json
import struct
import sys


def main() -> int:
    details = {
        "executable": sys.executable,
        "version": sys.version.split(" ")[0],
        "implementation": sys.implementation.name,
        "bits": struct.calcsize("P") * 8,
        "tkinter": False,
        "venv": False,
    }
    try:
        import tkinter  # noqa: F401
        details["tkinter"] = True
    except Exception as error:
        details["tkinter_error"] = str(error)
    try:
        import venv  # noqa: F401
        details["venv"] = True
    except Exception as error:
        details["venv_error"] = str(error)
    valid = (
        sys.implementation.name == "cpython"
        and sys.version_info[:2] == (3, 13)
        and details["bits"] == 64
        and details["tkinter"]
        and details["venv"]
    )
    if "--diagnose" in sys.argv:
        details["accepted"] = valid
        print(json.dumps(details, ensure_ascii=True))
    elif valid:
        print("DOCFORGE_PYTHON=" + sys.executable)
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
