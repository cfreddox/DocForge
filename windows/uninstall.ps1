# Per-user removal for the bootstrap installation. Documents in other folders are preserved.
$ErrorActionPreference = 'Stop'
$Target=Join-Path $env:LOCALAPPDATA 'DocForge'
$desktop=[Environment]::GetFolderPath('Desktop')
$menu=Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
foreach ($name in @('DocForge.lnk','DocForge Zone.lnk','DocForge Tray.lnk')) {
  foreach ($folder in @($desktop,$menu)) {
    if ($folder) { Remove-Item -LiteralPath (Join-Path $folder $name) -Force -ErrorAction SilentlyContinue }
  }
}
foreach ($ext in @('.md','.txt','.docx','.pdf')) {
  foreach ($fmt in @('pdf','md','docx','txt')) {
    Remove-Item -LiteralPath ('HKCU:\Software\Classes\SystemFileAssociations\'+$ext+'\shell\DocForgeTo'+$fmt) -Force -Recurse -ErrorAction SilentlyContinue
  }
}
Remove-Item -LiteralPath 'HKCU:\Software\Classes\SystemFileAssociations\.pdf\shell\DocForgeEdit' -Force -Recurse -ErrorAction SilentlyContinue
if (Test-Path -LiteralPath $Target) { Remove-Item -LiteralPath $Target -Force -Recurse }
Write-Host 'DocForge removed. Files that were converted outside the application folder remain.'
