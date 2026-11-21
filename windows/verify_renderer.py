"""Check the native Office renderer without fragile shell quoting.

Invoked as a file, not with `python -c`: PowerShell 5.1 can alter quoted
command-line strings before Python receives them.
"""
from __future__ import annotations

from office2pdf import ConvertOptions, convert_path

if not callable(convert_path):
    raise RuntimeError("office2pdf.convert_path is not callable")

options = ConvertOptions(include_warnings=True)
if options is None:
    raise RuntimeError("office2pdf.ConvertOptions did not initialize")

print("office2pdf API available")
