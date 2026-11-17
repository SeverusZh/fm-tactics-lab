"""Windows 真机验收脚本的后台启动收割与失败传播。"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "verify_engine_windows.ps1"
PWSH_CANDIDATES = (
    "pwsh",
    "/mnt/c/Program Files/PowerShell/7/pwsh.exe",
    r"C:\Program Files\PowerShell\7\pwsh.exe",
)

HARNESS = """$ErrorActionPreference = "Stop"
$ScriptPath = "__SCRIPT_PATH__"
$ast = [System.Management.Automation.Language.Parser]::ParseFile($ScriptPath, [ref]$null, [ref]$null)
$definitions = @{}
foreach ($node in $ast.FindAll({ param($item) $item -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
    $definitions[$node.Name] = $node.Extent.Text
}
__STUBS__
. ([scriptblock]::Create($definitions["Complete-NextJobAsync"]))
. ([scriptblock]::Create($definitions["Wait-FmJob"]))
__BODY__
"""


def pwsh_path() -> str | None:
    for candidate in PWSH_CANDIDATES:
        if candidate == "pwsh":
            found = shutil.which(candidate)
        else:
            found = candidate if Path(candidate).exists() else None
        if found:
            return found
    return None


def windows_pwsh(executable: str) -> bool:
    if sys.platform == "win32":
        return True
    return executable.lower().endswith(".exe")


def native_path(path: Path) -> str:
    if sys.platform == "win32":
        return str(path)
    converted = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True)
    if converted.returncode == 0 and converted.stdout.strip():
        return converted.stdout.strip()
    return str(path)


@pytest.fixture(scope="module")
def pwsh():
    executable = pwsh_path()
    if executable is None:
        pytest.skip("pwsh is required to exercise the Windows acceptance script")
    if not windows_pwsh(executable):
        pytest.skip("the acceptance script is exercised through Windows PowerShell")
    return executable


def run_harness(pwsh_executable: str, stubs: str, body: str) -> str:
    script = HARNESS.replace("__SCRIPT_PATH__", native_path(SCRIPT))
    script = script.replace("__STUBS__", stubs.strip())
    script = script.replace("__BODY__", body.strip())
    command = [pwsh_executable, "-NoProfile", "-NonInteractive"]
    if windows_pwsh(pwsh_executable):
        command += ["-ExecutionPolicy", "Bypass"]
    command += ["-Command", script]
    completed = subprocess.run(command, capture_output=True, timeout=180)
    stdout = completed.stdout.decode("utf-8", "replace")
    stderr = completed.stderr.decode("utf-8", "replace")
    assert completed.returncode == 0, stderr + stdout
    return stdout


def test_wait_fm_job_harvests_each_request_once():
    text = SCRIPT.read_text(encoding="utf-8")
    harvest_targets = re.findall(r"Complete-NextJobAsync -Request (\$\w+)", text)
    assert harvest_targets, "Wait-FmJob must harvest the background start request"
    assert all(target != "$request" for target in harvest_targets), (
        "harvesting $request before clearing it lets finally harvest the same job twice"
    )


def test_async_start_failure_keeps_the_original_error(pwsh):
    stubs = """
function Get-FmJob {
    param([string]$JobId)
    [pscustomobject]@{ status = "running"; completed = 0; total = 1 }
}
function Start-NextJobAsync {
    Start-Job -ScriptBlock { [ordered]@{ ok = $false; status = 503; message = "down" } }
}
$JobTimeoutSeconds = 30
$PollSeconds = 0
$script:BaseUrl = "http://127.0.0.1:1"
$script:Token = "token"
"""
    body = """
$message = ""
try {
    Wait-FmJob -JobId "deadbeef" | Out-Null
} catch {
    $message = $_.Exception.Message
}
Write-Output ("MESSAGE=" + $message)
Write-Output ("JOBS=" + @(Get-Job).Count)
"""
    output = run_harness(pwsh, stubs, body)
    assert "HTTP 503 down" in output, output
    assert "JOBS=0" in output, output


def test_timeout_stops_and_removes_the_background_request(pwsh):
    stubs = """
function Get-FmJob {
    param([string]$JobId)
    [pscustomobject]@{ status = "running"; completed = 0; total = 1 }
}
function Start-NextJobAsync {
    Start-Job -ScriptBlock { Start-Sleep -Seconds 60 }
}
$JobTimeoutSeconds = 1
$PollSeconds = 0
$script:BaseUrl = "http://127.0.0.1:1"
$script:Token = "token"
"""
    body = """
$message = ""
try {
    Wait-FmJob -JobId "deadbeef" | Out-Null
} catch {
    $message = $_.Exception.Message
}
Write-Output ("FAILED=" + [bool]$message)
Write-Output ("JOBS=" + @(Get-Job).Count)
"""
    output = run_harness(pwsh, stubs, body)
    assert "FAILED=True" in output, output
    assert "JOBS=0" in output, output


def test_completed_batch_returns_without_leaking_the_request(pwsh):
    stubs = """
function Get-FmJob {
    param([string]$JobId)
    [pscustomobject]@{ status = "completed"; completed = 4; total = 4 }
}
function Start-NextJobAsync {
    Start-Job -ScriptBlock { [ordered]@{ ok = $true; status = 200; message = "" } }
}
$JobTimeoutSeconds = 30
$PollSeconds = 0
$script:BaseUrl = "http://127.0.0.1:1"
$script:Token = "token"
"""
    body = """
$result = Wait-FmJob -JobId "deadbeef"
Write-Output ("STATUS=" + $result.status)
Write-Output ("JOBS=" + @(Get-Job).Count)
"""
    output = run_harness(pwsh, stubs, body)
    assert "STATUS=completed" in output, output
    assert "JOBS=0" in output, output


def test_terminal_batch_harvests_the_start_request_before_returning(pwsh):
    stubs = """
function Get-FmJob {
    param([string]$JobId)
    [pscustomobject]@{ status = "completed"; completed = 4; total = 4 }
}
function Start-NextJobAsync {
    Start-Job -ScriptBlock {
        Start-Sleep -Milliseconds 500
        [ordered]@{ ok = $false; status = 503; message = "delayed" }
    }
}
$JobTimeoutSeconds = 30
$PollSeconds = 0
$script:BaseUrl = "http://127.0.0.1:1"
$script:Token = "token"
"""
    body = """
$message = ""
try {
    Wait-FmJob -JobId "deadbeef" | Out-Null
} catch {
    $message = $_.Exception.Message
}
Write-Output ("MESSAGE=" + $message)
Write-Output ("JOBS=" + @(Get-Job).Count)
"""
    output = run_harness(pwsh, stubs, body)
    assert "HTTP 503 delayed" in output, output
    assert "JOBS=0" in output, output


def test_complete_without_output_returns_and_removes_the_job(pwsh):
    body = """
$job = Start-Job -ScriptBlock { }
Wait-Job -Job $job | Out-Null
$message = ""
try {
    Complete-NextJobAsync -Request $job
} catch {
    $message = $_.Exception.Message
}
Write-Output ("FAILED=" + [bool]$message)
Write-Output ("JOBS=" + @(Get-Job).Count)
"""
    output = run_harness(pwsh, "", body)
    assert "FAILED=False" in output, output
    assert "JOBS=0" in output, output


def test_terminal_batch_with_dead_start_request_is_bounded(pwsh):
    stubs = """
function Get-FmJob {
    param([string]$JobId)
    [pscustomobject]@{ status = "completed"; completed = 4; total = 4 }
}
function Start-NextJobAsync {
    Start-Job -ScriptBlock { Start-Sleep -Seconds 60 }
}
$JobTimeoutSeconds = 30
$PollSeconds = 0
$script:BaseUrl = "http://127.0.0.1:1"
$script:Token = "token"
"""
    body = """
$watch = [System.Diagnostics.Stopwatch]::StartNew()
$result = Wait-FmJob -JobId "deadbeef"
$watch.Stop()
Write-Output ("ELAPSED=" + [math]::Round($watch.Elapsed.TotalSeconds, 1))
Write-Output ("STATUS=" + $result.status)
Write-Output ("JOBS=" + @(Get-Job).Count)
"""
    output = run_harness(pwsh, stubs, body)
    elapsed = float(re.search(r"ELAPSED=([0-9.]+)", output).group(1))
    assert 4.0 <= elapsed <= 10.0, output
    assert "STATUS=completed" in output, output
    assert "JOBS=0" in output, output


def test_complete_removes_the_job_when_receive_job_throws(pwsh):
    body = """
$job = Start-Job -ScriptBlock {
    Write-Error "boom"
    [ordered]@{ ok = $true; status = 200; message = "" }
}
Wait-Job -Job $job | Out-Null
$message = ""
try {
    Complete-NextJobAsync -Request $job
} catch {
    $message = $_.Exception.Message
}
Write-Output ("FAILED=" + [bool]$message)
Write-Output ("JOBS=" + @(Get-Job).Count)
"""
    output = run_harness(pwsh, "", body)
    assert "FAILED=True" in output, output
    assert "JOBS=0" in output, output