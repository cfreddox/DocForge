# Publishing to GitHub

1. Create a repository (for example `DocForge`), then upload **the contents of the provided GitHub source ZIP**, not its containing parent directory. The README and `INSTALL-WINDOWS.cmd` must appear at repo root.
2. Configure Repository → Settings → Actions and Issues. Replace the `OWNER/REPOSITORY` placeholder in `.github/ISSUE_TEMPLATE/config.yml`.
3. Review third-party license obligations in `THIRD_PARTY_NOTICES.md` before publishing any bundled EXE. The upstream source being MIT is not sufficient for bundled dependencies.
4. Run the Linux tests and the Windows workflow, examine outputs. Windows EXE is built only on Windows and is not included in the source ZIP.
5. Tag as `v1.11.0`, create a GitHub Release and attach `DocForge-Windows-1.11.4.zip`, `DocForge-Linux-1.11.4.zip` and `SHA256SUMS.txt`.
6. List known limitations: internet required for initial installation; no guaranteed pixel-perfect Office rendering; Qt/Wayland Drag & Drop needs device testing.
7. For users of the ZIP-based Windows installer, instruct updating via fresh ZIP + `INSTALL-WINDOWS.cmd`. Do not claim this as an automatic background updater.
