# Release checklist — 1.11.0

- [x] README explains clean install and update on both platforms.
- [x] Root-level `INSTALL-WINDOWS.cmd` and `INSTALL-LINUX.sh` routes.
- [x] Existing installation detection and code-backup/rollback path.
- [x] Nautilus permanent zone launch; no GNOME top-bar plugin.
- [x] Config, user documents and environments excluded from repo.
- [x] GitHub Issue/PR templates, CI, .gitignore, security and contributing docs.
- [ ] Validate Windows setup end-to-end on **clean Windows 10/11 x64**.
- [ ] Validate Windows upgrades from installed 1.10.x and rollback after forced failure.
- [ ] Verify Nautilus Drag & Drop on real GNOME Wayland.
- [ ] Build/sign and test a native EXE, if publishing one.
- [ ] Legal review of PyMuPDF (AGPL/commercial), PySide6/Qt and Pandoc obligations; bundle required third-party licenses.
- [ ] Upload release assets, SHA256SUMS and test reports to GitHub Releases.

**Do not claim production readiness for untested Windows/Wayland combinations.**
