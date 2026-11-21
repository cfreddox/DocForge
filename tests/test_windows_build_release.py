"""Regression checks for the GitHub Actions Windows build wrapper."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_build_wrapper_uses_named_argument_array():
    source = (ROOT / 'windows' / 'build-release.ps1').read_text(encoding='utf-8')
    assert 'function Invoke-Checked' in source
    assert '[string[]]$ArgumentList' in source
    assert '& $Executable @ArgumentList' in source
    assert 'function Check([string]$exe, [string[]]$args)' not in source
    assert 'Check $Python @(' not in source
    assert 'Invoke-Checked -Executable $Python -ArgumentList @(' in source
    assert 'Invoke-Checked -Executable $Compiler -ArgumentList @(' in source


def test_windows_workflow_runs_arg_forwarding_self_test():
    workflow = (ROOT / '.github' / 'workflows' / 'build-windows.yml').read_text(encoding='utf-8')
    assert r'.\windows\build-release.ps1 -SelfTest' in workflow
    assert workflow.index('build-release.ps1 -SelfTest') < workflow.index('choco install innosetup')


def test_build_script_fails_on_nonzero_native_exit_code():
    source = (ROOT / 'windows' / 'build-release.ps1').read_text(encoding='utf-8')
    assert '$exitCode = $LASTEXITCODE' in source
    assert 'if ($exitCode -ne 0)' in source
    assert 'PyInstaller exited successfully but' in source
