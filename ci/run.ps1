python ./skip_ci.py --base-branch-env=SYSTEM_PULLREQUEST_TARGETBRANCH --is-pull-env=SYSTEM_PULLREQUEST_PULLREQUESTID --base-branch-origin
if ($LastExitCode -ne 0) {
  exit 0
}

# remove Chocolately, MinGW, Strawberry Perl from path, so we don't find gcc/gfortran and try to use it
# remove PostgreSQL from path so we don't pickup a broken zlib from it
$env:Path = ($env:Path.Split(';') | Where-Object { $_ -notmatch 'mingw|Strawberry|Chocolatey|PostgreSQL' }) -join ';'

# Rust puts its shared stdlib in a secret place, but it is needed to run tests.
$env:Path += ";$HOME/.rustup/toolchains/stable-x86_64-pc-windows-msvc/bin"

# Set the CI env var for the meson test framework
$env:CI = '1'

# download and install prerequisites
function DownloadFile([String] $Source, [String] $Destination) {
  $retries = 10
  echo "Downloading $Source"
  for ($i = 1; $i -le $retries; $i++) {
      try {
          (New-Object net.webclient).DownloadFile($Source, $Destination)
          break # succeeded
      } catch [net.WebException] {
          if ($i -eq $retries) {
              throw # fail on last retry
          }
          $backoff = (10 * $i) # backoff 10s, 20s, 30s...
          echo ('{0}: {1}' -f $Source, $_.Exception.Message)
          echo ('Retrying in {0}s...' -f $backoff)
          Start-Sleep -m ($backoff * 1000)
        }
    }
}


if (($env:backend -eq 'ninja') -and ($env:arch -ne 'arm64')) { $dmd = $true } else { $dmd = $false }

DownloadFile -Source https://github.com/mesonbuild/cidata/releases/download/ci3/ci_data.zip -Destination $env:AGENT_WORKFOLDER\ci_data.zip
echo "Extracting ci_data.zip"
Expand-Archive $env:AGENT_WORKFOLDER\ci_data.zip -DestinationPath $env:AGENT_WORKFOLDER\ci_data
& "$env:AGENT_WORKFOLDER\ci_data\install.ps1" -Arch $env:arch -Compiler $env:compiler -Boost $true -DMD $dmd


echo "=== PATH BEGIN ==="
echo ($env:Path).Replace(';',"`n")
echo "=== PATH END ==="
echo ""

$progs = @("python","ninja","pkg-config","cl","rc","link")
foreach ($prog in $progs) {
  echo ""
  echo "Locating ${prog}:"
  where.exe $prog
}

echo ""
echo "Ninja / MSBuld version:"
if ($env:backend -eq 'ninja') {
  ninja --version
} else {
  MSBuild /version
}

echo ""
echo "Python version:"
python --version

# Needed for running unit tests in parallel.
echo ""
python -m pip --disable-pip-version-check install --upgrade pefile pytest-xdist jsonschema coverage gcovr 

echo ""
echo "=== Start running tests ==="
# Starting from VS2019 Powershell(?) will fail the test run
# if it prints anything to stderr. Python's test runner
# does that by default so we need to forward it.
cmd /c "python 2>&1 ./tools/run_with_cov.py  run_tests.py --backend $env:backend $env:extraargs"

$result = $LastExitCode

echo ""
echo ""
echo "=== Gathering coverage report ==="
echo ""

python3 -m coverage combine
python3 -m coverage xml
python3 -m coverage report

# Currently codecov.py does not handle Azure, use this fork of a fork to get it
# working without requireing a token
git clone https://github.com/mensinda/codecov-python
python3 -m pip install --ignore-installed ./codecov-python
python3 -m codecov -f .coverage/coverage.xml -n "VS$env:compiler $env:arch $env:backend" -c $env:SOURCE_VERSION

exit $result
