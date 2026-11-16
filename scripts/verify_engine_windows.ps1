[CmdletBinding()]
param(
    [string]$BaseUrl = "",
    [string]$Token = "",
    [string]$EndpointPath = "",
    [string]$EngineRoot = "",
    [string]$GameRoot = "",
    [string]$DraftId = "",
    [int]$MatchCount = 256,
    [string]$WorkerList = "1,8,256",
    [switch]$AllowOversubscription,
    [string]$EvidenceDir = "dist/engine-qa",
    [int]$JobTimeoutSeconds = 7200,
    [int]$PollSeconds = 3
)

$ErrorActionPreference = "Stop"
$script:BaseUrl = $BaseUrl
$script:Token = $Token

function Write-Step {
    param([string]$Message)
    Write-Host "== $Message"
}

function Resolve-Endpoint {
    param([string]$Path, [string]$Url, [string]$Bearer)
    if ($Url -and $Bearer) { return }
    $candidates = @()
    if ($Path) { $candidates += $Path }
    if (-not $Path) {
        $dataRoot = Join-Path $env:LOCALAPPDATA "com.severuszh.fm27lab"
        $candidates += (Join-Path $dataRoot "agent/endpoint.json")
        $candidates += (Join-Path $env:LOCALAPPDATA "fm27lab/agent/endpoint.json")
    }
    foreach ($candidate in $candidates) {
        if (-not (Test-Path $candidate)) { continue }
        $payload = Get-Content -Raw -Path $candidate | ConvertFrom-Json
        if (-not $script:BaseUrl) { $script:BaseUrl = [string]$payload.url }
        if (-not $script:Token) { $script:Token = [string]$payload.token }
        return
    }
    throw "未提供 -BaseUrl 与 -Token，且找不到 sidecar 发现文件 endpoint.json；请显式传入两者或指定 -EndpointPath"
}

function Invoke-Api {
    param([string]$Method, [string]$Path, $Body = $null)
    $uri = "$($script:BaseUrl)$Path"
    $parameters = @{
        Method     = $Method
        Uri        = $uri
        Headers    = @{ Authorization = "Bearer $($script:Token)" }
        TimeoutSec = 120
    }
    if ($null -ne $Body) {
        $parameters.ContentType = "application/json; charset=utf-8"
        $parameters.Body = ($Body | ConvertTo-Json -Depth 24 -Compress)
    }
    try {
        return Invoke-RestMethod @parameters
    } catch {
        $response = $_.Exception.Response
        $code = 0
        if ($null -ne $response) { $code = [int]$response.StatusCode }
        $detail = $_.ErrorDetails.Message
        if ([string]::IsNullOrWhiteSpace($detail)) { $detail = $_.Exception.Message }
        throw "HTTP $code $Method $Path 失败：$detail"
    }
}

function Get-FmJob {
    param([string]$JobId)
    return Invoke-Api -Method Get -Path "/api/jobs/$JobId"
}

function Start-NextJobAsync {
    $request = @{
        uri     = "$($script:BaseUrl)/api/experiments/start"
        token   = $script:Token
        timeout = $JobTimeoutSeconds + 120
    }
    return Start-Job -ArgumentList $request -ScriptBlock {
        param($payload)
        $headers = @{ Authorization = "Bearer $($payload.token)" }
        try {
            $body = Invoke-RestMethod -Method Post -Uri $payload.uri -Headers $headers -TimeoutSec $payload.timeout
            return [ordered]@{ ok = $true; status = 200; body = $body; message = "" }
        } catch {
            $status = 0
            $response = $_.Exception.Response
            if ($null -ne $response) { $status = [int]$response.StatusCode }
            return [ordered]@{ ok = $false; status = $status; body = $null; message = $_.Exception.Message }
        }
    }
}

function Complete-NextJobAsync {
    param($Request)
    $outcome = Receive-Job -Job $Request -Wait
    Remove-Job -Job $Request -Force
    if ($null -eq $outcome) { return }
    if (-not $outcome.ok) {
        throw ("引擎启动失败：HTTP {0} {1}" -f $outcome.status, $outcome.message)
    }
}

function Wait-FmJob {
    param([string]$JobId)
    $deadline = (Get-Date).AddSeconds($JobTimeoutSeconds)
    $lastStatus = ""
    $request = Start-NextJobAsync
    try {
        while ((Get-Date) -lt $deadline) {
            $job = Get-FmJob -JobId $JobId
            if ($job.status -ne $lastStatus) {
                Write-Host ("任务 {0} 状态 {1}，已完成 {2}/{3}" -f $JobId, $job.status, $job.completed, $job.total)
                $lastStatus = $job.status
            }
            if (@("completed", "error", "cancelled", "interrupted") -contains $job.status) {
                return $job
            }
            if ($null -ne $request -and $request.State -eq "Completed") {
                Complete-NextJobAsync -Request $request
                $request = $null
            }
            Start-Sleep -Seconds $PollSeconds
        }
        throw "任务 $JobId 在 $JobTimeoutSeconds 秒内未进入终态"
    } finally {
        if ($null -ne $request) {
            if ($request.State -eq "Completed") {
                Complete-NextJobAsync -Request $request
            } else {
                Stop-Job -Job $request -ErrorAction SilentlyContinue
                Remove-Job -Job $request -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

function Get-AllRuns {
    param([string]$JobId)
    $items = @()
    $offset = 0
    while ($true) {
        $page = Invoke-Api -Method Get -Path "/api/jobs/$JobId/runs?limit=200&offset=$offset"
        if ($null -eq $page) { break }
        $pageItems = @($page.items)
        if ($pageItems.Count -eq 0) { break }
        $items += $pageItems
        $offset += $pageItems.Count
        if ($null -eq $page.next_offset) { break }
    }
    return $items
}

function ConvertTo-Canonical {
    param($Value)
    if ($null -eq $Value) { return "null" }
    if ($Value -is [string]) { return (ConvertTo-Json -InputObject $Value -Compress) }
    if ($Value -is [bool]) { if ($Value) { return "true" } else { return "false" } }
    if ($Value -is [int] -or $Value -is [long] -or $Value -is [double] -or $Value -is [decimal]) {
        return $Value.ToString([System.Globalization.CultureInfo]::InvariantCulture)
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $keys = @($Value.Keys | ForEach-Object { [string]$_ } | Sort-Object)
        $parts = @()
        foreach ($name in $keys) {
            $parts += (ConvertTo-Json -InputObject $name -Compress) + ":" + (ConvertTo-Canonical -Value $Value[$name])
        }
        return "{" + ($parts -join ",") + "}"
    }
    $properties = @($Value.PSObject.Properties | Where-Object { $_.MemberType -eq "NoteProperty" })
    if ($properties.Count -gt 0) {
        $parts = @()
        foreach ($name in ($properties | ForEach-Object { $_.Name } | Sort-Object)) {
            $parts += (ConvertTo-Json -InputObject $name -Compress) + ":" + (ConvertTo-Canonical -Value $Value.$name)
        }
        return "{" + ($parts -join ",") + "}"
    }
    if ($Value -is [System.Collections.IEnumerable]) {
        $parts = @()
        foreach ($item in $Value) { $parts += (ConvertTo-Canonical -Value $item) }
        return "[" + ($parts -join ",") + "]"
    }
    return (ConvertTo-Json -InputObject $Value -Compress)
}

function Get-RunSignature {
    param($Run)
    $payload = [ordered]@{
        score    = $Run.score
        verified = $Run.verified
        stats    = $Run.stats
    }
    return (ConvertTo-Canonical -Value $payload)
}

function Invoke-Experiment {
    param([int]$Workers, [int]$MatchCount, [string]$Draft, $Resources, [bool]$Oversubscribe)
    $body = @{
        name                    = "引擎验收 workers=$Workers"
        seeds                   = @(1..$MatchCount)
        draft_id                = $Draft
        workers                 = $Workers
        cpu_count               = [int]$Resources.cpu_count
        available_memory_bytes  = [int64]$Resources.available_memory_bytes
        free_disk_bytes         = [int64]$Resources.free_disk_bytes
        allow_oversubscription  = $Oversubscribe
    }
    return Invoke-Api -Method Post -Path "/api/experiments" -Body $body
}

function Resolve-Draft {
    param([string]$Requested)
    if ($Requested) { return $Requested }
    $page = Invoke-Api -Method Get -Path "/api/drafts?limit=1"
    $items = @()
    if ($null -ne $page) { $items = @($page.items) }
    if ($items.Count -gt 0) {
        return [string]$items[0].id
    }
    Write-Host "没有既有草案，使用引擎资源配置生成模板草案"
    $template = Invoke-Api -Method Get -Path "/api/tactics/template"
    $created = Invoke-Api -Method Post -Path "/api/drafts" -Body @{ name = "引擎验收草案"; scenario = $template.scenario }
    return [string]$created.id
}

function Add-Check {
    param([System.Collections.ArrayList]$Checks, [string]$Name, [bool]$Passed, [string]$Detail)
    $null = $Checks.Add([ordered]@{ name = $Name; passed = $Passed; detail = $Detail })
}

Resolve-Endpoint -Path $EndpointPath -Url $BaseUrl -Bearer $Token
if (-not $script:BaseUrl) { throw "缺少 sidecar 地址" }
if (-not $script:Token) { throw "缺少访问令牌" }
if ($MatchCount -lt 1 -or $MatchCount -gt 10000) { throw "-MatchCount 必须在 1 到 10000 之间" }
$workers = @()
foreach ($part in $WorkerList.Split(",")) {
    $text = $part.Trim()
    if (-not $text) { continue }
    $value = [int]$text
    if ($value -lt 1 -or $value -gt 256) { throw "并行数必须在 1 到 256 之间：$value" }
    $workers += $value
}
if ($workers.Count -eq 0) { throw "-WorkerList 不能为空" }

$startedAt = (Get-Date).ToUniversalTime().ToString("o")
$checks = New-Object System.Collections.ArrayList
$configs = @()
$mismatches = @()
$baselineSignatures = $null
$baselineWorkers = $workers[0]

Write-Step "检查 sidecar 健康状态"
$health = Invoke-Api -Method Get -Path "/api/health"
Add-Check -Checks $checks -Name "sidecar_health" -Passed ($health.status -eq "ok") -Detail ([string]$health.version)
if ($health.status -ne "ok") { throw "sidecar 健康检查未通过" }

if ($EngineRoot -or $GameRoot) {
    Write-Step "配置引擎与游戏目录"
    $selectBody = @{}
    if ($EngineRoot) { $selectBody.engine_root = $EngineRoot }
    if ($GameRoot) { $selectBody.game_root = $GameRoot }
    $null = Invoke-Api -Method Post -Path "/api/engine/select" -Body $selectBody
}

$engineStatus = Invoke-Api -Method Get -Path "/api/engine"
Add-Check -Checks $checks -Name "engine_available" -Passed ([bool]$engineStatus.engine.available) -Detail (($engineStatus.engine.missing | ForEach-Object { $_ }) -join "; ")
Add-Check -Checks $checks -Name "game_available" -Passed ([bool]$engineStatus.game.available) -Detail (($engineStatus.game.missing | ForEach-Object { $_ }) -join "; ")
if (-not $engineStatus.engine.available -or -not $engineStatus.game.available) {
    throw "引擎或游戏资源不完整，无法进行真实引擎验收"
}

Write-Step "运行引擎兼容诊断"
$diagnosis = Invoke-Api -Method Post -Path "/api/engine/diagnose"
Add-Check -Checks $checks -Name "engine_diagnose" -Passed ([bool]$diagnosis.compatible) -Detail ([string]$diagnosis.reason)
if (-not $diagnosis.compatible) { throw "引擎兼容诊断未通过：$($diagnosis.reason)" }

$draft = Resolve-Draft -Requested $DraftId
Write-Step "使用草案 $draft"
Add-Check -Checks $checks -Name "draft_ready" -Passed ([bool]$draft) -Detail $draft

$resources = Invoke-Api -Method Get -Path "/api/system/resources"
Write-Host ("宿主资源：CPU {0}，可用内存 {1} 字节，空闲磁盘 {2} 字节" -f $resources.cpu_count, $resources.available_memory_bytes, $resources.free_disk_bytes)

foreach ($workerCount in $workers) {
    Write-Step "提交 $MatchCount 场真实引擎批次，并行 $workerCount"
    $oversubscribe = [bool]$AllowOversubscription
    $overrideNote = ""
    try {
        $job = Invoke-Experiment -Workers $workerCount -MatchCount $MatchCount -Draft $draft -Resources $resources -Oversubscribe $oversubscribe
    } catch {
        if (-not $oversubscribe -and $_.Exception.Message -match "insufficient_(memory|disk)") {
            Write-Warning "资源预检拒绝 $workerCount 路，使用覆盖开关重试"
            $oversubscribe = $true
            $overrideNote = "resource_preflight_overridden"
            $job = Invoke-Experiment -Workers $workerCount -MatchCount $MatchCount -Draft $draft -Resources $resources -Oversubscribe $oversubscribe
        } else {
            throw
        }
    }
    $jobId = [string]$job.id
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $finished = Wait-FmJob -JobId $jobId
    $watch.Stop()
    $wallSeconds = [math]::Round($watch.Elapsed.TotalSeconds, 3)
    if ($finished.status -ne "completed") {
        $summaryText = ""
        if ($null -ne $finished.summary) { $summaryText = ConvertTo-Canonical -Value $finished.summary }
        throw "批次 $jobId 终态为 $($finished.status)：$summaryText"
    }
    $runSeconds = $null
    if ($finished.started_at -and $finished.finished_at) {
        $runSeconds = [math]::Round((([datetime]::Parse($finished.finished_at) - [datetime]::Parse($finished.started_at)).TotalSeconds), 3)
    }
    $throughput = $null
    if ($null -ne $runSeconds -and $runSeconds -gt 0) {
        $throughput = [math]::Round($MatchCount / $runSeconds, 3)
    }
    Write-Host ("批次完成：墙钟 {0} 秒，引擎计时 {1} 秒，吞吐 {2} 场每秒" -f $wallSeconds, $runSeconds, $throughput)

    $runs = Get-AllRuns -JobId $jobId
    $signatures = [ordered]@{}
    foreach ($run in $runs) {
        $signatures[[string]$run.seed] = Get-RunSignature -Run $run
    }
    $configDirectory = Join-Path $EvidenceDir ("runs-workers-$workerCount")
    New-Item -ItemType Directory -Force -Path $configDirectory | Out-Null
    $signatures | ConvertTo-Json -Depth 6 | Set-Content -Path (Join-Path $configDirectory "signatures.json") -Encoding utf8
    $runs | ConvertTo-Json -Depth 12 | Set-Content -Path (Join-Path $configDirectory "runs.json") -Encoding utf8

    $configRecord = [ordered]@{
        workers           = $workerCount
        job_id            = $jobId
        matches           = [int]$finished.total
        completed         = [int]$finished.completed
        wall_seconds      = $wallSeconds
        engine_seconds    = $runSeconds
        throughput        = $throughput
        allow_oversubscription = $oversubscribe
        override_note     = $overrideNote
    }
    if ($finished.total -ne $MatchCount -or $finished.completed -ne $MatchCount) {
        Add-Check -Checks $checks -Name "batch_complete_$workerCount" -Passed $false -Detail "total=$($finished.total) completed=$($finished.completed)"
        throw "批次 $jobId 场次不一致：期望 $MatchCount，实际 total=$($finished.total) completed=$($finished.completed)"
    }
    Add-Check -Checks $checks -Name "batch_complete_$workerCount" -Passed $true -Detail "$MatchCount 场"

    if ($null -eq $baselineSignatures) {
        $baselineSignatures = $signatures
        $baselineWorkers = $workerCount
    } else {
        foreach ($seed in $baselineSignatures.Keys) {
            if (-not $signatures.Contains($seed)) {
                $mismatches += [ordered]@{ seed = $seed; workers = $workerCount; issue = "missing_run" }
                continue
            }
            if ($signatures[$seed] -ne $baselineSignatures[$seed]) {
                $mismatches += [ordered]@{ seed = $seed; workers = $workerCount; issue = "signature_mismatch"; baseline = $baselineSignatures[$seed]; actual = $signatures[$seed] }
            }
        }
    }
    $configs += $configRecord
}

$identityPassed = ($mismatches.Count -eq 0)
Add-Check -Checks $checks -Name "result_identity" -Passed $identityPassed -Detail ("基准并行 $baselineWorkers，对比 $($configs.Count) 组，差异 $($mismatches.Count) 条")

$finishedAt = (Get-Date).ToUniversalTime().ToString("o")
$passed = -not ($checks | Where-Object { -not $_.passed })
$evidence = [ordered]@{
    started_at        = $startedAt
    finished_at       = $finishedAt
    passed            = [bool]$passed
    matches_per_batch = $MatchCount
    baseline_workers  = $baselineWorkers
    host              = [ordered]@{
        machine = $env:COMPUTERNAME
        os      = [System.Environment]::OSVersion.VersionString
    }
    engine            = $engineStatus
    diagnosis         = $diagnosis
    draft_id          = $draft
    resources         = $resources
    configs           = $configs
    identity_mismatches = $mismatches
    checks            = $checks
}
New-Item -ItemType Directory -Force -Path $EvidenceDir | Out-Null
$evidencePath = Join-Path $EvidenceDir "evidence.json"
$evidence | ConvertTo-Json -Depth 16 | Set-Content -Path $evidencePath -Encoding utf8
Write-Host "证据文件：$evidencePath"

if ($passed) {
    Write-Host "真实引擎并发与结果身份验收通过"
    exit 0
}
Write-Host "真实引擎验收未通过"
exit 1
