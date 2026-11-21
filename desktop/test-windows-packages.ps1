$ErrorActionPreference = 'Stop'
if (-not $env:CI) { throw 'Use a disposable Windows CI runner' }
$testRoot = $env:BAIZE_PACKAGE_TEST_TEMP
$output = $env:BAIZE_PACKAGE_OUTPUT
if (-not $testRoot -or -not (Test-Path -LiteralPath $testRoot -PathType Container)) { throw 'Missing package test directory' }

# Reproduce per-user TEMP folders which inherit a package SID but no package
# group access. The portable launcher must prepare its own program directory.
$portableTemp = Join-Path $testRoot 'portable-temp'
New-Item -ItemType Directory -Path $portableTemp | Out-Null
$acl = Get-Acl -LiteralPath $portableTemp
$acl.SetAccessRuleProtection($true, $true)
foreach ($rule in @($acl.Access)) {
  $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
  if ($sid -in @('S-1-15-2-1', 'S-1-15-2-2')) { $acl.RemoveAccessRuleSpecific($rule) }
}
$packageSid = [System.Security.Principal.SecurityIdentifier]::new('S-1-15-2-123456789-234567890-345678901-456789012-567890123-678901234-789012345')
$acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new($packageSid, 'ReadAndExecute', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
Set-Acl -LiteralPath $portableTemp -AclObject $acl
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
try {
  $env:TEMP = $portableTemp
  $env:TMP = $portableTemp
  $portable = @(Get-ChildItem -LiteralPath $output -Filter '*-portable.exe' -File)
  if ($portable.Count -ne 1) { throw 'Expected one portable EXE' }
  $env:BAIZE_SMOKE_EXECUTABLE = $portable[0].FullName
  node (Join-Path $PSScriptRoot 'smoke.cjs')
  if ($LASTEXITCODE -ne 0) { throw 'Final portable EXE did not render its interface' }
} finally {
  $env:TEMP = $previousTemp
  $env:TMP = $previousTmp
}

$setup = @(Get-ChildItem -LiteralPath $output -Filter '*-setup.exe' -File)
if ($setup.Count -ne 1) { throw 'Expected one setup EXE' }
$installDirectory = Join-Path $testRoot 'installed app'
$installer = Start-Process -FilePath $setup[0].FullName -ArgumentList '/S', ('/D=' + $installDirectory) -WindowStyle Hidden -PassThru
if (-not $installer.WaitForExit(180000)) { $installer.Kill(); throw 'Setup timed out' }
if ($installer.ExitCode -ne 0) { throw "Setup failed: $($installer.ExitCode)" }
$installedExe = Join-Path $installDirectory 'Baize.exe'
if (-not (Test-Path -LiteralPath $installedExe)) { throw 'Setup did not install Baize.exe' }
$env:BAIZE_SMOKE_EXECUTABLE = $installedExe
node (Join-Path $PSScriptRoot 'smoke.cjs')
if ($LASTEXITCODE -ne 0) { throw 'Installed application did not render its interface' }
$uninstaller = Join-Path $installDirectory 'Uninstall Baize.exe'
Start-Process -FilePath $uninstaller -ArgumentList '/S' -WindowStyle Hidden -Wait
if (Test-Path -LiteralPath $installedExe) { throw 'Uninstall left the application executable behind' }
