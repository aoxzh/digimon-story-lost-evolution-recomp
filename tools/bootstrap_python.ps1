# Fetch a private CPython into kit\python when the machine has none.
# Unprivileged: everything stays inside this folder. Pinned and SHA-256 checked.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$url = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.14.10+20261026-x86_64-pc-windows-msvc-install_only.tar.gz'
$sha = '98bbe6a0d798bcbad142e96e5930a330e4dc407638e898b515c51eb73a27580d'
$kit = Join-Path $root 'kit'
$tmp = Join-Path $kit 'downloads'
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$archive = Join-Path $tmp 'cpython-3.14.10-x86_64-pc-windows-msvc.tar.gz'
Write-Host '[kit] downloading Python 3.14.10 (about 49 MiB) ...'
& curl.exe -L --fail --retry 3 --progress-bar -o $archive $url
if ($LASTEXITCODE -ne 0) { throw 'curl failed' }
$actual = (Get-FileHash -Algorithm SHA256 $archive).Hash.ToLower()
if ($actual -ne $sha) {
    Remove-Item -Force $archive
    throw "python archive sha256 mismatch: expected $sha, got $actual"
}
$extract = Join-Path $tmp 'python-extract'
Remove-Item -Recurse -Force $extract -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $extract | Out-Null
& tar.exe -xzf $archive -C $extract
if ($LASTEXITCODE -ne 0) { throw 'tar failed' }
$inner = Get-ChildItem $extract -Directory | Select-Object -First 1
if (-not $inner) { throw 'unexpected python archive layout' }
Remove-Item -Recurse -Force (Join-Path $kit 'python') -ErrorAction SilentlyContinue
Move-Item $inner.FullName (Join-Path $kit 'python')
Remove-Item -Recurse -Force $extract -ErrorAction SilentlyContinue
& (Join-Path $kit 'python\python.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'the fetched python does not run' }
