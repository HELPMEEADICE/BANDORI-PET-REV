[CmdletBinding()]
param(
    [string]$InstallDir = "",
    [int]$BandoriPort = 38473,
    [string]$BandoriToken = "",
    [int]$WaitLoginMinutes = 10,
    [switch]$SkipDownload,
    [switch]$NoLaunch
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Resolve-RepoRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Get-BandoriEndpoint {
    $endpoint = "http://127.0.0.1:$BandoriPort/chat-events"
    if ($BandoriToken.Trim()) {
        $endpoint += "?token=$([System.Uri]::EscapeDataString($BandoriToken.Trim()))"
    }
    return $endpoint
}

function Test-BandoriPort {
    $health = "http://127.0.0.1:$BandoriPort/health"
    try {
        Invoke-RestMethod -Method Get -Uri $health -TimeoutSec 2 | Out-Null
        Write-Ok "BandoriPet 聊天接入口已响应：$health"
    } catch {
        Write-Warn "暂时没有连上 BandoriPet：$health"
        Write-Warn "如果桌宠还没启动，稍后启动桌宠并在设置里启用聊天接入即可。"
    }
}

function Get-LatestNapCatAsset {
    Write-Step "查询 NapCat 最新 Windows 包"
    $release = Invoke-RestMethod `
        -Uri "https://api.github.com/repos/NapNeko/NapCatQQ/releases/latest" `
        -Headers @{ "User-Agent" = "BandoriPet-NapCat-Setup" }
    $asset = $release.assets | Where-Object { $_.name -eq "NapCat.Shell.Windows.Node.zip" } | Select-Object -First 1
    if (-not $asset) {
        $asset = $release.assets | Where-Object { $_.name -eq "NapCat.Shell.Windows.OneKey.zip" } | Select-Object -First 1
    }
    if (-not $asset) {
        throw "没有在最新 Release 里找到 NapCat Windows 包。请手动下载 NapCat.Shell.Windows.Node.zip。"
    }
    Write-Ok "找到 $($release.tag_name)：$($asset.name)"
    return $asset
}

function Find-NapCatLauncher([string]$Root) {
    if (-not (Test-Path $Root)) {
        return $null
    }
    $preferred = @("napcat.bat", "napcat.quick.bat", "NapCatWinBootMain.exe", "NapCat.Shell.exe")
    foreach ($name in $preferred) {
        $hit = Get-ChildItem -Path $Root -Recurse -File -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($hit) {
            return $hit
        }
    }
    return $null
}

function Install-NapCat([string]$TargetDir) {
    $launcher = Find-NapCatLauncher $TargetDir
    if ($launcher) {
        Write-Ok "检测到已有 NapCat：$($launcher.FullName)"
        return $launcher
    }
    if ($SkipDownload) {
        throw "指定了 -SkipDownload，但 $TargetDir 下没有找到 NapCat 启动器。"
    }

    $asset = Get-LatestNapCatAsset
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
    $zipPath = Join-Path $TargetDir $asset.name
    Write-Step "下载 NapCat：$($asset.browser_download_url)"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath
    Write-Step "解压 NapCat 到 $TargetDir"
    Expand-Archive -Path $zipPath -DestinationPath $TargetDir -Force

    $launcher = Find-NapCatLauncher $TargetDir
    if (-not $launcher) {
        throw "解压完成，但没有找到 NapCat 启动器。请检查 $TargetDir。"
    }
    Write-Ok "NapCat 已准备好：$($launcher.FullName)"
    return $launcher
}

function Ensure-JsonProperty($Object, [string]$Name, $DefaultValue) {
    if (-not ($Object.PSObject.Properties.Name -contains $Name)) {
        $Object | Add-Member -NotePropertyName $Name -NotePropertyValue $DefaultValue
    }
}

function New-OneBotConfigObject([string]$Endpoint) {
    return [pscustomobject]@{
        network = [pscustomobject]@{
            httpServers = @()
            httpClients = @([pscustomobject]@{
                name = "BandoriPet"
                enable = $true
                url = $Endpoint
                messagePostFormat = "array"
                reportSelfMessage = $false
                token = ""
                debug = $false
            })
            websocketServers = @()
            websocketClients = @()
        }
        musicSignUrl = ""
        enableLocalFile2Url = $false
        parseMultMsg = $false
    }
}

function Set-OneBotBandoriClient([string]$ConfigPath, [string]$Endpoint) {
    $client = [pscustomobject]@{
        name = "BandoriPet"
        enable = $true
        url = $Endpoint
        messagePostFormat = "array"
        reportSelfMessage = $false
        token = ""
        debug = $false
    }

    if (Test-Path $ConfigPath) {
        try {
            $data = Get-Content -Raw -Encoding UTF8 $ConfigPath | ConvertFrom-Json
        } catch {
            $backup = "$ConfigPath.bandori-backup-$(Get-Date -Format yyyyMMddHHmmss)"
            Copy-Item -LiteralPath $ConfigPath -Destination $backup -Force
            Write-Warn "原配置不是标准 JSON，已备份到 $backup，并重写 OneBot 配置。"
            $data = New-OneBotConfigObject $Endpoint
        }
    } else {
        $data = New-OneBotConfigObject $Endpoint
    }

    Ensure-JsonProperty $data "network" ([pscustomobject]@{})
    Ensure-JsonProperty $data.network "httpServers" @()
    Ensure-JsonProperty $data.network "httpClients" @()
    Ensure-JsonProperty $data.network "websocketServers" @()
    Ensure-JsonProperty $data.network "websocketClients" @()
    Ensure-JsonProperty $data "musicSignUrl" ""
    Ensure-JsonProperty $data "enableLocalFile2Url" $false
    Ensure-JsonProperty $data "parseMultMsg" $false

    $existing = @($data.network.httpClients) | Where-Object { $_ -and $_.name -ne "BandoriPet" }
    $data.network.httpClients = @($existing + $client)

    $dir = Split-Path -Parent $ConfigPath
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $data | ConvertTo-Json -Depth 20 | Set-Content -Path $ConfigPath -Encoding UTF8
    Write-Ok "已写入 OneBot HTTP 上报：$ConfigPath"
}

function Get-NapCatConfigDirs([string]$InstallRoot, [string]$LauncherDir) {
    $dirs = New-Object System.Collections.Generic.List[string]
    foreach ($candidate in @(
        (Join-Path $LauncherDir "config"),
        (Join-Path $InstallRoot "config")
    )) {
        if (-not $dirs.Contains($candidate)) {
            $dirs.Add($candidate)
        }
    }
    Get-ChildItem -Path $InstallRoot -Recurse -Directory -Filter "config" -ErrorAction SilentlyContinue |
        ForEach-Object {
            if (-not $dirs.Contains($_.FullName)) {
                $dirs.Add($_.FullName)
            }
        }
    return $dirs
}

function Sync-NapCatConfigs([string]$InstallRoot, [string]$LauncherDir, [string]$Endpoint) {
    $configDirs = Get-NapCatConfigDirs -InstallRoot $InstallRoot -LauncherDir $LauncherDir
    foreach ($dir in $configDirs) {
        Set-OneBotBandoriClient -ConfigPath (Join-Path $dir "onebot11.json") -Endpoint $Endpoint
    }

    $accountFiles = Get-ChildItem -Path $InstallRoot -Recurse -File -Filter "onebot11_*.json" -ErrorAction SilentlyContinue
    foreach ($file in $accountFiles) {
        Set-OneBotBandoriClient -ConfigPath $file.FullName -Endpoint $Endpoint
    }
    return @($accountFiles)
}

function Start-NapCat([System.IO.FileInfo]$Launcher) {
    if ($NoLaunch) {
        Write-Warn "已跳过启动 NapCat。"
        return
    }
    Write-Step "启动 NapCat"
    if ($Launcher.Extension -ieq ".bat" -or $Launcher.Extension -ieq ".cmd") {
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$($Launcher.FullName)`"" -WorkingDirectory $Launcher.DirectoryName
    } else {
        Start-Process -FilePath $Launcher.FullName -WorkingDirectory $Launcher.DirectoryName
    }
    Write-Ok "NapCat 已启动。如果弹出安全提示，请确认这是你刚下载的 NapCat。"
}

function Get-WebUiUrl([string]$InstallRoot) {
    $webui = Get-ChildItem -Path $InstallRoot -Recurse -File -Filter "webui.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($webui) {
        try {
            $data = Get-Content -Raw -Encoding UTF8 $webui.FullName | ConvertFrom-Json
            $port = 6099
            if ($data.PSObject.Properties.Name -contains "port" -and $data.port) {
                $port = [int]$data.port
            }
            $token = ""
            if ($data.PSObject.Properties.Name -contains "token" -and $data.token) {
                $token = [string]$data.token
            }
            if ($token.Trim()) {
                return "http://127.0.0.1:$port/webui?token=$([System.Uri]::EscapeDataString($token.Trim()))"
            }
            return "http://127.0.0.1:$port/webui"
        } catch {
            return "http://127.0.0.1:6099/webui"
        }
    }
    return $null
}

function Open-WebUiWhenReady([string]$InstallRoot) {
    if ($NoLaunch) {
        return
    }
    Write-Step "等待 NapCat WebUI"
    $url = $null
    for ($i = 0; $i -lt 30; $i++) {
        $url = Get-WebUiUrl $InstallRoot
        if ($url) {
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $url) {
        $url = "http://127.0.0.1:6099/webui"
        Write-Warn "暂未找到 webui.json，将打开默认 WebUI 地址。Token 可在 NapCat 控制台或 webui.json 里查看。"
    }
    Start-Process $url
    Write-Ok "已打开 NapCat WebUI：$url"
}

function Wait-And-PatchAccountConfig([string]$InstallRoot, [string]$LauncherDir, [string]$Endpoint) {
    if ($WaitLoginMinutes -le 0) {
        return
    }
    Write-Step "等待 QQ 扫码登录并生成账号配置"
    Write-Host "请在 NapCat WebUI 中进入 QQ 登录，点击 QRCode，用手机 QQ 扫码登录。"
    Write-Host "脚本会等待 $WaitLoginMinutes 分钟；检测到 onebot11_<QQ号>.json 后会自动写入 BandoriPet 上报配置。"

    $deadline = (Get-Date).AddMinutes($WaitLoginMinutes)
    $patched = @()
    while ((Get-Date) -lt $deadline) {
        $patched = Sync-NapCatConfigs -InstallRoot $InstallRoot -LauncherDir $LauncherDir -Endpoint $Endpoint
        if ($patched.Count -gt 0) {
            Write-Ok "检测到账号 OneBot 配置，已完成接入。"
            return
        }
        Start-Sleep -Seconds 5
    }
    Write-Warn "等待超时。默认 onebot11.json 已写入；如果登录后仍收不到消息，请重新运行本脚本。"
}

$repoRoot = Resolve-RepoRoot
if (-not $InstallDir.Trim()) {
    $InstallDir = Join-Path $repoRoot ".runtime\napcat"
}
$InstallDir = [System.IO.Path]::GetFullPath($InstallDir)
$endpoint = Get-BandoriEndpoint

Write-Host "BandoriPet NapCat QQ 接入脚本" -ForegroundColor Magenta
Write-Host "NapCat 安装目录：$InstallDir"
Write-Host "BandoriPet 接收地址：$endpoint"
Write-Host "说明：脚本不会读取或保存你的 QQ 密码；QQ 登录需要你在 NapCat WebUI 中扫码确认。"

Test-BandoriPort
$launcher = Install-NapCat $InstallDir
$launcherDir = $launcher.DirectoryName
Sync-NapCatConfigs -InstallRoot $InstallDir -LauncherDir $launcherDir -Endpoint $endpoint | Out-Null
Start-NapCat $launcher
Open-WebUiWhenReady $InstallDir
Wait-And-PatchAccountConfig -InstallRoot $InstallDir -LauncherDir $launcherDir -Endpoint $endpoint

Write-Step "完成"
Write-Host "后续确认项："
Write-Host "1. BandoriPet 设置 -> 聊天接入：启用本地聊天接入端口。"
Write-Host "2. NapCat WebUI：QQ 已登录，网络配置里 BandoriPet HTTP 客户端为启用状态。"
Write-Host "3. 在 QQ 群/私聊发一条消息，桌宠应显示未读摘要。"
