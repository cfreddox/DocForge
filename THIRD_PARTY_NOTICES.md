# Third-party dependencies and publication compliance

This file records component *families* used by DocForge 1.11.0. It is **not** a substitute for bundling each required license notice, verifying the actual wheel distribution licenses, or legal advice.

| Component | Indicative license / note | Upstream |
|---|---|---|
| PyMuPDF / MuPDF | **AGPLv3 or commercial**. Redistribution and linkage of the application may trigger AGPL obligations. Obtain proper commercial rights if distributing proprietary binaries. | https://pymupdf.io/licensing |
| PySide6 / Qt for Python | **LGPLv3/GPL/commercial**, depending on the chosen Qt modules and distribution. Review LGPL dynamic-linking/replacement requirements and licensing notices. | https://doc.qt.io/qtforpython-6/licenses.html |
| Pandoc | **GPL-2.0-or-later**. If distributing a binary, provide required notices and source access as the license requires. | https://github.com/jgm/pandoc |
| office2pdf-python | Check shipped package metadata and repository license for exact release. | https://pypi.org/project/office2pdf-python/ |
| Pillow, pypdf, python-docx, python-pptx, openpyxl, tkinterdnd2, pystray | Check installed package distribution metadata and include all notices. | https://pypi.org/ |
| Tesseract OCR (optional, Linux) | Apache-2.0; verify language-model licenses separately. | https://github.com/tesseract-ocr/tesseract |
| Python runtime (Windows installer) | Python Software Foundation License; include notices when bundled. | https://www.python.org/psf/license/ |

**Publication gate:** Do not distribute a standalone bundled EXE until the software's applicable licenses have been reviewed. A top-level MIT license for DocForge's own source code does not waive third-party requirements.
