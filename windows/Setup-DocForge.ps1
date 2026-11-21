# DocForge graphical per-user setup for Windows PowerShell 5.1+.
# UTF-8 with BOM is required for localized UI strings in Windows PowerShell 5.1.
param([switch]$NoLaunch)
$ErrorActionPreference = 'Stop'
$PSScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Target = Join-Path $env:LOCALAPPDATA 'DocForge'
$Logs = Join-Path $Target 'logs'
New-Item -ItemType Directory -Force -Path $Logs | Out-Null
$script:stdout = Join-Path $Logs 'installer-stdout.log'
$script:stderr = Join-Path $Logs 'installer-stderr.log'
$script:worker = $null
$script:ready = $false
try {
    Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase
} catch {
    Write-Host 'Graphical installer is unavailable; open install.ps1 in PowerShell.'
    exit 90
}
[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" Title="DocForge Setup"
 Width="800" Height="555" WindowStartupLocation="CenterScreen" ResizeMode="NoResize"
 WindowStyle="None" AllowsTransparency="True" Background="Transparent" ShowInTaskbar="True">
 <Border CornerRadius="24" BorderThickness="1" BorderBrush="#566b8f" Background="#101d33">
  <Grid>
   <Grid.RowDefinitions><RowDefinition Height="172"/><RowDefinition Height="*"/><RowDefinition Height="60"/></Grid.RowDefinitions>
   <Grid Grid.Row="0">
    <Border CornerRadius="23,23,0,0" Background="#162a48"/>
    <Image Name="Banner" Stretch="UniformToFill" ClipToBounds="True" Opacity="0.91"/>
    <Border Background="#3f0c1524" CornerRadius="23,23,0,0"/>
    <Button Name="ExitButton" Content="×" Width="40" Height="38" HorizontalAlignment="Right" VerticalAlignment="Top" Margin="0,15,18,0"
            Background="#31425a" Foreground="White" BorderBrush="#516a88" FontSize="21" Cursor="Hand"/>
   </Grid>
   <StackPanel Grid.Row="1" Margin="34,18,34,10">
    <TextBlock Text="Установка DocForge" FontSize="27" FontWeight="Bold" Foreground="#f3f7ff"/>
    <TextBlock Text="Конвертер документов и PDF-редактор без LibreOffice" FontSize="13" Foreground="#a8c3e6" Margin="0,4,0,15"/>
    <Border BorderThickness="1" BorderBrush="#3f557b" Background="#1d304d" CornerRadius="10" Padding="13,9">
      <TextBlock Name="Status" Text="Готов к установке. Python и библиотеки загрузятся автоматически." TextWrapping="Wrap" Foreground="#e8f2ff" FontSize="13"/>
    </Border>
    <ProgressBar Name="Progress" Height="9" Minimum="0" Maximum="100" Value="0" Margin="0,15,0,12" Background="#283b57" Foreground="#65caff"/>
    <TextBlock Text="Подробности установки" Foreground="#b9d3ef" FontSize="12" Margin="0,0,0,6"/>
    <Border BorderBrush="#30466a" Background="#0b1629" BorderThickness="1" CornerRadius="10" Padding="10">
     <ScrollViewer Height="112" VerticalScrollBarVisibility="Auto">
      <TextBlock Name="LogOutput" Text="Компоненты будут установлены в профиль пользователя. Системный PATH не изменяется." Foreground="#98afce" FontSize="11" TextWrapping="Wrap" FontFamily="Consolas"/>
     </ScrollViewer>
    </Border>
   </StackPanel>
   <Grid Grid.Row="2" Margin="32,4,32,17">
    <Grid.ColumnDefinitions><ColumnDefinition Width="*"/><ColumnDefinition Width="Auto"/><ColumnDefinition Width="12"/><ColumnDefinition Width="Auto"/></Grid.ColumnDefinitions>
    <Button Grid.Column="0" Name="ShowLogs" Content="Открыть журнал" Height="38" HorizontalAlignment="Left" Width="145" Foreground="#cedeff" Background="#263a58" BorderBrush="#56769c" Cursor="Hand"/>
    <Button Grid.Column="1" Name="InstallButton" Content="Установить" Width="145" Height="40" Foreground="White" FontWeight="Bold" Background="#376cdf" BorderBrush="#6db8ff" Cursor="Hand"/>
    <Button Grid.Column="3" Name="OpenButton" Content="Открыть DocForge" Width="155" Height="40" Foreground="White" Background="#1e795d" BorderBrush="#4ad2a3" Cursor="Hand" IsEnabled="False"/>
   </Grid>
  </Grid>
 </Border>
</Window>
'@
try {
  $reader = New-Object System.Xml.XmlNodeReader($xaml)
  $window = [Windows.Markup.XamlReader]::Load($reader)
} catch {
  Write-Host ('Failed to load setup UI: ' + $_.Exception.Message)
  exit 90
}
$banner = $window.FindName('Banner')
$bannerPath = Join-Path $Project 'assets\installer-banner.png'
if (Test-Path -LiteralPath $bannerPath) {
  $bmp = New-Object System.Windows.Media.Imaging.BitmapImage
  $bmp.BeginInit()
  $bmp.UriSource = New-Object System.Uri($bannerPath)
  $bmp.CacheOption = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
  $bmp.EndInit()
  $banner.Source = $bmp
}
$status = $window.FindName('Status')
$bar = $window.FindName('Progress')
$logText = $window.FindName('LogOutput')
$installButton = $window.FindName('InstallButton')
$existingApp = Join-Path $Target 'docforge\__init__.py'
if (Test-Path -LiteralPath $existingApp -PathType Leaf) {
  $window.FindName('Status').Text = 'Найдена установленная версия DocForge. Настройки и Python сохранятся.'
  $installButton.Content = 'Обновить'
}

$openButton = $window.FindName('OpenButton')
$exitButton = $window.FindName('ExitButton')
$showLogs = $window.FindName('ShowLogs')
$window.Add_MouseLeftButtonDown({
  param($sender, $e)
  if ($e.LeftButton -eq [System.Windows.Input.MouseButtonState]::Pressed) {
    try { $window.DragMove() } catch {}
  }
})
$exitButton.Add_Click({
  if ($script:worker -and -not $script:worker.HasExited) {
    $choice = [System.Windows.MessageBox]::Show('Прервать установку? Её можно запустить снова.', 'DocForge', 'YesNo', 'Question')
    if ($choice -ne 'Yes') { return }
    try { $script:worker.Kill() } catch {}
  }
  $window.Close()
})
$showLogs.Add_Click({
  $path = $script:stdout
  if (-not (Test-Path -LiteralPath $path)) { $path = $Logs }
  Start-Process -FilePath explorer.exe -ArgumentList ('"' + $path + '"')
})
$openButton.Add_Click({
  $exe = Join-Path $Target 'venv313\Scripts\pythonw.exe'
  $launcher = Join-Path $Target 'launcher.py'
  if ((Test-Path -LiteralPath $exe) -and (Test-Path -LiteralPath $launcher)) {
    Start-Process -FilePath $exe -ArgumentList ('"' + $launcher + '" gui') -WorkingDirectory $Target
    $window.Close()
  }
})
# The native tool may print a harmless stderr warning after a successful
# smoke test.  GUI success is based on validated artifacts and the completed
# installer log, not on the last visible line from merged stdout/stderr.
function Test-DocForgeInstalled {
  $python = Join-Path $Target 'venv313\Scripts\python.exe'
  $launcher = Join-Path $Target 'launcher.py'
  $module = Join-Path $Target 'docforge\cli.py'
  if (-not ((Test-Path -LiteralPath $python -PathType Leaf) -and
            (Test-Path -LiteralPath $launcher -PathType Leaf) -and
            (Test-Path -LiteralPath $module -PathType Leaf))) { return $false }
  if (-not (Test-Path -LiteralPath $script:stdout)) { return $false }
  try {
    $body = Get-Content -LiteralPath $script:stdout -Raw -ErrorAction Stop
  } catch { return $false }
  # Match the completed smoke test independent of the app version.
  # A fixed 1.10.0 string caused false failures for 1.11.0 and later.
  # Both the actual test and final shortcut creation must have completed.
  return ($body -match '(?m)^OK: DocForge [0-9]+\.[0-9]+\.[0-9]+;.*GUI imports' -and
          $body -match '\[DocForge\] SUCCESS\.' -and
          $body -match '\[DocForge\] Installed location:' -and
          $body -notmatch '\[DocForge ERROR\]')
}

function Test-DocForgeLogFailure {
  foreach ($file in @($script:stdout, $script:stderr)) {
    if (Test-Path -LiteralPath $file) {
      try {
        if ((Get-Content -LiteralPath $file -Raw) -match '\[DocForge ERROR\]') {
          return $true
        }
      } catch {}
    }
  }
  return $false
}

$timer = New-Object System.Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(500)
$timer.Add_Tick({
  $pieces = @()
  foreach ($file in @($script:stdout,$script:stderr)) {
    if (Test-Path -LiteralPath $file) {
      try { $pieces += @(Get-Content -LiteralPath $file -Tail 8 -ErrorAction SilentlyContinue) } catch {}
    }
  }
  if ($pieces.Count -gt 0) {
    $logText.Text = ($pieces -join [Environment]::NewLine)
    $last = $pieces | Where-Object { $_ -match '^\[DocForge\]' } | Select-Object -Last 1
    if ($last) { $status.Text = $last }
  }
  if ($script:worker -and $script:worker.HasExited) {
    $timer.Stop()
    # Flush redirected streams before inspecting the completion markers.
    try { $script:worker.WaitForExit() } catch {}
    $bar.IsIndeterminate = $false
    $validated = Test-DocForgeInstalled
    $hasError = Test-DocForgeLogFailure
    if ($validated -and -not $hasError) {
      $script:ready = $true
      $bar.Value = 100
      if ($script:worker.ExitCode -ne 0) {
        $status.Text = 'Проверка документов и установка завершены. Дополнительное предупреждение записано в журнал.'
      } else {
        $status.Text = 'DocForge установлен. Ярлык создан в меню Пуск и на рабочем столе.'
      }
      $installButton.Content = 'Готово'
      $installButton.IsEnabled = $true
      $openButton.IsEnabled = $true
    } else {
      $bar.Value = 0
      $status.Text = 'Не удалось подтвердить завершение установки. Откройте журнал: ошибки не скрываются.'
      $installButton.Content = 'Повторить'
      $installButton.IsEnabled = $true
    }
  }
})
$installButton.Add_Click({
  if ($script:ready) { $window.Close(); return }
  $installButton.IsEnabled = $false
  $status.Text = 'Проверка компонентов и безопасная установка/обновление...'
  $logText.Text = 'Скачивание и установка библиотек может занять некоторое время.'
  $bar.IsIndeterminate = $true
  $run = Join-Path $PSScriptRoot 'install.ps1'
  try {
    # Use a child process so the WPF window remains responsive throughout setup.
    $argument = '-NoProfile -ExecutionPolicy Bypass -File "' + $run + '" -NoLaunch'
    $script:worker = Start-Process -FilePath 'powershell.exe' -ArgumentList $argument -PassThru -WindowStyle Hidden `
      -RedirectStandardOutput $script:stdout -RedirectStandardError $script:stderr
    $timer.Start()
  } catch {
    $bar.IsIndeterminate = $false
    $installButton.IsEnabled = $true
    $status.Text = 'Не удалось начать установку: ' + $_.Exception.Message
  }
})
[void]$window.ShowDialog()
if ($script:ready) { exit 0 }
exit 1
