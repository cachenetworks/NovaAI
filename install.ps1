#Requires -Version 5.1
<#
.SYNOPSIS
    NovaAI one-line installer for Windows.

.DESCRIPTION
    Run this with:
        powershell -c "irm https://raw.githubusercontent.com/cachenetworks/NovaAI/main/install.ps1 | iex"

    Or if you already downloaded it:
        .\install.ps1

    What it does:
        1. Checks for (and optionally installs) Python 3.11+
        2. Checks for (and optionally installs) Ollama
        3. Clones or downloads NovaAI
        4. Creates a virtual environment and installs dependencies
        5. Asks about NVIDIA GPU support
        6. Optionally creates a desktop shortcut
        7. Launches NovaAI
#>

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ── Config ───────────────────────────────────────────────────────────────────

$REPO_URL     = "https://github.com/cachenetworks/NovaAI"
$REPO_BRANCH  = "main"
$INSTALL_DIR  = "$env:USERPROFILE\NovaAI"
$PYTHON_MIN   = [version]"3.11.0"
$PYTHON_WINGET_ID = "Python.Python.3.11"
$OLLAMA_WINGET_ID = "Ollama.Ollama"

# ── Colors & helpers ─────────────────────────────────────────────────────────

function Write-Step  { param([string]$n, [string]$msg) Write-Host "  [$n] " -ForegroundColor Magenta -NoNewline; Write-Host $msg }
function Write-Ok    { param([string]$msg) Write-Host "    [OK] " -ForegroundColor Green -NoNewline; Write-Host $msg }
function Write-Warn  { param([string]$msg) Write-Host "    [!!] " -ForegroundColor Yellow -NoNewline; Write-Host $msg }
function Write-Fail  { param([string]$msg) Write-Host "    [X]  " -ForegroundColor Red -NoNewline; Write-Host $msg }
function Write-Info  { param([string]$msg) Write-Host "         $msg" -ForegroundColor DarkGray }

function Ask-YesNo {
    param([string]$Question, [bool]$Default = $true)
    $hint = if ($Default) { "[Y/n]" } else { "[y/N]" }
    while ($true) {
        Write-Host ""
        Write-Host "  ? " -ForegroundColor Cyan -NoNewline
        Write-Host "$Question $hint " -NoNewline
        $answer = Read-Host
        if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
        switch ($answer.Trim().ToLower()) {
            "y"   { return $true  }
            "yes" { return $true  }
            "n"   { return $false }
            "no"  { return $false }
            default { Write-Host "    Please enter y or n." -ForegroundColor Yellow }
        }
    }
}

function Ask-Choice {
    param([string]$Question, [string[]]$Options, [int]$Default = 0)
    Write-Host ""
    Write-Host "  ? " -ForegroundColor Cyan -NoNewline
    Write-Host $Question
    for ($i = 0; $i -lt $Options.Length; $i++) {
        $marker = if ($i -eq $Default) { " > " } else { "   " }
        $color  = if ($i -eq $Default) { "White" } else { "DarkGray" }
        Write-Host "   $marker[$($i+1)] " -ForegroundColor Magenta -NoNewline
        Write-Host $Options[$i] -ForegroundColor $color
    }
    Write-Host "    Enter choice (1-$($Options.Length)) [default: $($Default+1)]: " -NoNewline
    $answer = Read-Host
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    $idx = [int]$answer - 1
    if ($idx -ge 0 -and $idx -lt $Options.Length) { return $idx }
    return $Default
}

function Has-Command { param([string]$cmd) return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Has-Winget { return Has-Command "winget" }

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path    = "$machinePath;$userPath"
}

# ── Banner ───────────────────────────────────────────────────────────────────

function Show-Banner {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════════╗" -ForegroundColor Magenta
    Write-Host "  ║                                                      ║" -ForegroundColor Magenta
    Write-Host "  ║   " -ForegroundColor Magenta -NoNewline
    Write-Host "  _   _                    _    ___  " -ForegroundColor White -NoNewline
    Write-Host "       ║" -ForegroundColor Magenta
    Write-Host "  ║   " -ForegroundColor Magenta -NoNewline
    Write-Host " | \ | |  ___  __   ____ _| |  /   | " -ForegroundColor White -NoNewline
    Write-Host "       ║" -ForegroundColor Magenta
    Write-Host "  ║   " -ForegroundColor Magenta -NoNewline
    Write-Host " |  \| | / _ \ \ \ / / _` | | / /| | " -ForegroundColor White -NoNewline
    Write-Host "       ║" -ForegroundColor Magenta
    Write-Host "  ║   " -ForegroundColor Magenta -NoNewline
    Write-Host " | |\  || (_) | \ V / (_| | |/ /_| | " -ForegroundColor White -NoNewline
    Write-Host "       ║" -ForegroundColor Magenta
    Write-Host "  ║   " -ForegroundColor Magenta -NoNewline
    Write-Host " |_| \_| \___/   \_/ \__,_|_|\___,_| " -ForegroundColor White -NoNewline
    Write-Host "       ║" -ForegroundColor Magenta
    Write-Host "  ║                                                      ║" -ForegroundColor Magenta
    Write-Host "  ║   " -ForegroundColor Magenta -NoNewline
    Write-Host "  Your AI companion, built to vibe with you  " -ForegroundColor DarkGray -NoNewline
    Write-Host "       ║" -ForegroundColor Magenta
    Write-Host "  ║                                                      ║" -ForegroundColor Magenta
    Write-Host "  ╚══════════════════════════════════════════════════════╝" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "    This installer will set up everything you need." -ForegroundColor DarkGray
    Write-Host "    Grab a coffee — this might take a few minutes." -ForegroundColor DarkGray
    Write-Host ""
}

# ── Step: Python ─────────────────────────────────────────────────────────────

function Ensure-Python {
    Write-Step "1/6" "Checking for Python 3.11+..."

    # Check if python is available and meets version requirement
    $pythonCmd = $null
    foreach ($cmd in @("python", "python3", "py")) {
        if (Has-Command $cmd) {
            try {
                $ver = & $cmd --version 2>&1 | Select-String -Pattern "(\d+\.\d+\.\d+)" | ForEach-Object { $_.Matches[0].Value }
                if ($ver -and ([version]$ver -ge $PYTHON_MIN)) {
                    $pythonCmd = $cmd
                    Write-Ok "Found $cmd $ver"
                    return $pythonCmd
                }
            } catch { }
        }
    }

    # Try py launcher with version flag
    if (Has-Command "py") {
        try {
            $ver = & py -3.11 --version 2>&1 | Select-String -Pattern "(\d+\.\d+\.\d+)" | ForEach-Object { $_.Matches[0].Value }
            if ($ver -and ([version]$ver -ge $PYTHON_MIN)) {
                Write-Ok "Found py -3.11 ($ver)"
                return "py"
            }
        } catch { }
    }

    Write-Warn "Python 3.11+ not found."

    if (-not (Has-Winget)) {
        Write-Fail "winget is not available to install Python automatically."
        Write-Fail "Please install Python 3.11+ from https://python.org and run this again."
        throw "Python 3.11+ is required."
    }

    if (Ask-YesNo "Install Python 3.11 via winget?") {
        Write-Info "Installing Python 3.11 (this may take a moment)..."
        winget install -e --id $PYTHON_WINGET_ID --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity --silent
        if ($LASTEXITCODE -ne 0) { throw "Failed to install Python via winget." }
        Refresh-Path
        Write-Ok "Python installed."
        return "python"
    } else {
        throw "Python 3.11+ is required. Install it and run this again."
    }
}

# ── Step: Ollama ─────────────────────────────────────────────────────────────

function Ensure-Ollama {
    Write-Step "2/6" "Checking for Ollama..."

    # Check common locations
    $ollamaExe = $null
    $localPath = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (Test-Path $localPath) {
        $ollamaExe = $localPath
    } elseif (Has-Command "ollama") {
        $ollamaExe = (Get-Command "ollama").Source
    }

    if ($ollamaExe) {
        Write-Ok "Found Ollama: $ollamaExe"
        return $ollamaExe
    }

    Write-Warn "Ollama not found."

    if (-not (Has-Winget)) {
        Write-Warn "winget not available. Install Ollama manually from https://ollama.com/download"
        return $null
    }

    if (Ask-YesNo "Install Ollama via winget? (needed for local LLM)") {
        Write-Info "Installing Ollama..."
        winget install -e --id $OLLAMA_WINGET_ID --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity --silent
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Ollama install failed. You can install it later from https://ollama.com/download"
            return $null
        }
        Refresh-Path
        $localPath = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
        if (Test-Path $localPath) { $ollamaExe = $localPath }
        elseif (Has-Command "ollama") { $ollamaExe = (Get-Command "ollama").Source }
        if ($ollamaExe) { Write-Ok "Ollama installed: $ollamaExe" }
        return $ollamaExe
    } else {
        Write-Info "Skipping Ollama. You can install it later."
        return $null
    }
}

# ── Step: Clone / Download ───────────────────────────────────────────────────

function Get-NovaAI {
    Write-Step "3/6" "Downloading NovaAI..."

    if (Test-Path "$INSTALL_DIR\setup.py") {
        Write-Ok "NovaAI already exists at $INSTALL_DIR"
        if (-not (Ask-YesNo "Re-download / update it?" $false)) {
            return
        }
    }

    if (Has-Command "git") {
        if (Test-Path "$INSTALL_DIR\.git") {
            Write-Info "Pulling latest changes..."
            Push-Location $INSTALL_DIR
            git pull origin $REPO_BRANCH --ff-only 2>&1 | Out-Null
            Pop-Location
            Write-Ok "Updated via git pull."
        } else {
            Write-Info "Cloning from GitHub..."
            git clone --branch $REPO_BRANCH --single-branch $REPO_URL $INSTALL_DIR 2>&1 | Out-Null
            Write-Ok "Cloned to $INSTALL_DIR"
        }
    } else {
        # Download as zip
        Write-Info "git not found — downloading as ZIP..."
        $zipUrl  = "$REPO_URL/archive/refs/heads/$REPO_BRANCH.zip"
        $zipPath = "$env:TEMP\novaai-download.zip"
        $extractPath = "$env:TEMP\novaai-extract"

        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
        if (Test-Path $extractPath) { Remove-Item $extractPath -Recurse -Force }
        Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force

        # The zip extracts to a folder like NovaAI-main/
        $innerDir = Get-ChildItem $extractPath | Select-Object -First 1
        if (-not (Test-Path $INSTALL_DIR)) { New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null }
        Copy-Item -Path "$($innerDir.FullName)\*" -Destination $INSTALL_DIR -Recurse -Force

        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        Remove-Item $extractPath -Recurse -Force -ErrorAction SilentlyContinue
        Write-Ok "Downloaded and extracted to $INSTALL_DIR"
    }
}

# ── Step: Setup ──────────────────────────────────────────────────────────────

function Run-Setup {
    param([string]$PythonCmd)

    Write-Step "4/6" "Running NovaAI setup..."
    Write-Info "This installs dependencies, downloads models, and prepares everything."
    Write-Host ""

    Push-Location $INSTALL_DIR
    try {
        if ($PythonCmd -eq "py") {
            & py -3.11 setup.py --setup
        } else {
            & $PythonCmd setup.py --setup
        }
        if ($LASTEXITCODE -ne 0) { throw "Setup script failed." }
        Write-Ok "Setup complete."
    } finally {
        Pop-Location
    }
}

# ── Step: GPU ────────────────────────────────────────────────────────────────

function Ask-GPU {
    Write-Step "5/6" "GPU acceleration..."

    $choice = Ask-Choice "Do you have an NVIDIA GPU for faster voice synthesis?" @(
        "Yes — install CUDA-accelerated PyTorch (recommended for NVIDIA GPUs)",
        "No  — stick with CPU-only (works fine, just slower voice)",
        "Skip — I'll decide later"
    ) 2  # default to Skip

    if ($choice -eq 0) {
        Write-Info "Installing CUDA-enabled PyTorch... (this downloads ~2 GB)"
        $venvPython = "$INSTALL_DIR\.venv\Scripts\python.exe"
        & $venvPython -m pip install --upgrade --index-url https://download.pytorch.org/whl/cu128 torch torchaudio torchcodec -q
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "CUDA PyTorch installed. Voice synthesis will be much faster!"
        } else {
            Write-Warn "CUDA install had issues. CPU mode will still work fine."
        }
    } elseif ($choice -eq 1) {
        Write-Ok "Using CPU mode. You can add GPU support later."
        Write-Info "To add GPU later, run:"
        Write-Info "  $INSTALL_DIR\.venv\Scripts\python.exe -m pip install --upgrade --index-url https://download.pytorch.org/whl/cu128 torch torchaudio torchcodec"
    } else {
        Write-Ok "Skipped. Default CPU mode works out of the box."
    }
}

# ── Step: Shortcut ───────────────────────────────────────────────────────────

function Ask-Shortcut {
    Write-Step "6/6" "Desktop shortcut..."

    if (Ask-YesNo "Create a desktop shortcut for NovaAI?") {
        try {
            $desktopPath = [Environment]::GetFolderPath("Desktop")
            $shortcutPath = "$desktopPath\NovaAI.lnk"
            $shell = New-Object -ComObject WScript.Shell
            $shortcut = $shell.CreateShortcut($shortcutPath)
            $shortcut.TargetPath = "$INSTALL_DIR\.venv\Scripts\pythonw.exe"
            $shortcut.Arguments = "`"$INSTALL_DIR\app.py`" --gui"
            $shortcut.WorkingDirectory = $INSTALL_DIR
            $shortcut.Description = "NovaAI - AI Companion Studio"

            # Use the Python icon if available
            $pythonIcon = "$INSTALL_DIR\.venv\Scripts\python.exe"
            if (Test-Path $pythonIcon) {
                $shortcut.IconLocation = "$pythonIcon,0"
            }

            $shortcut.Save()
            Write-Ok "Shortcut created on your desktop."
        } catch {
            Write-Warn "Couldn't create shortcut: $_"
        }
    } else {
        Write-Ok "No shortcut created."
    }
}

# ── Finish ───────────────────────────────────────────────────────────────────

function Show-Finish {
    Write-Host ""
    Write-Host "  ╔══════════════════════════════════════════════════════╗" -ForegroundColor Green
    Write-Host "  ║                                                      ║" -ForegroundColor Green
    Write-Host "  ║       " -ForegroundColor Green -NoNewline
    Write-Host "NovaAI is ready to go!" -ForegroundColor White -NoNewline
    Write-Host "                      ║" -ForegroundColor Green
    Write-Host "  ║                                                      ║" -ForegroundColor Green
    Write-Host "  ╚══════════════════════════════════════════════════════╝" -ForegroundColor Green
    Write-Host ""
    Write-Host "    Installed to: " -NoNewline -ForegroundColor DarkGray
    Write-Host $INSTALL_DIR -ForegroundColor White
    Write-Host ""
    Write-Host "    To launch NovaAI anytime:" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "      cd $INSTALL_DIR" -ForegroundColor Cyan
    Write-Host "      python setup.py" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "    Or use the desktop shortcut if you created one." -ForegroundColor DarkGray
    Write-Host ""
}

# ── Main ─────────────────────────────────────────────────────────────────────

function Main {
    Show-Banner

    $pythonCmd = Ensure-Python
    $ollamaExe = Ensure-Ollama
    Get-NovaAI
    Run-Setup -PythonCmd $pythonCmd
    Ask-GPU
    Ask-Shortcut

    Show-Finish

    if (Ask-YesNo "Launch NovaAI now?") {
        Write-Host ""
        Write-Info "Starting NovaAI..."
        Push-Location $INSTALL_DIR
        $venvPython = "$INSTALL_DIR\.venv\Scripts\python.exe"
        & $venvPython app.py --gui
        Pop-Location
    }
}

# ── Run ──────────────────────────────────────────────────────────────────────

try {
    Main
} catch {
    Write-Host ""
    Write-Fail "Installation failed: $_"
    Write-Host ""
    Write-Host "    If you need help, open an issue at:" -ForegroundColor DarkGray
    Write-Host "    $REPO_URL/issues" -ForegroundColor Cyan
    Write-Host ""
    exit 1
}
