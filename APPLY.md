# DocForge CI Hotfix 1.11.5

Fix for the GitHub Actions failure (9 failed, 150 passed, 1 skipped).
This is a code/CI patch; the application version stays 1.11.0.

## Apply on Ubuntu

1. Extract this archive.
2. Copy its `.github/`, `docforge/`, and `tests/` contents into the corresponding directories of your local DocForge repository. Preserve directory structure and overwrite matching files. Do not copy APPLY.md to the project unless you want to keep it.
3. Run:

```bash
python -m pytest -q
# Ensure your local dependencies are installed beforehand.
git add .github/workflows/tests.yml docforge tests
 git commit -m "fix: stabilize CI dependencies and CLI output"
git push origin main
```

## Changes

- Install system libEGL/OpenGL/Qt support on ubuntu-latest CI.
- Migrate application imports from deprecated `fitz` to `pymupdf as fitz`; CLI stdout stays machine-readable.
- Use safe standard-library local resource fetcher instead of unused WeasyPrint API dependency.
- Remove stale checks demanding deleted publication files.

## Validation

- Targeted tests: 55 passed.
- CLI conversion: zero exit status, PDF created, stdout contains only one path.
- Full test run reached 100% progress but did not terminate cleanly in this sandbox; not reported as passed.
- Qt tests need running on GitHub's Linux runner with the new system packages.
