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
        2. Asks which LLM provider you want (Ollama, OpenAI, OpenRouter, LM Studio, custom)
        3. Installs Ollama if needed, or configures API keys for cloud providers
        4. Clones or downloads NovaAI
        5. Creates a virtual environment and installs dependencies
        6. Asks about NVIDIA GPU support
        7. Optionally creates a desktop shortcut
        8. Launches NovaAI
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

function Ask-Input {
    param([string]$Prompt, [string]$Default = "")
    Write-Host ""
    Write-Host "  ? " -ForegroundColor Cyan -NoNewline
    if ($Default) {
        Write-Host "$Prompt [default: $Default]: " -NoNewline
    } else {
        Write-Host "${Prompt}: " -NoNewline
    }
    $answer = Read-Host
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim()
}

function Has-Command { param([string]$cmd) return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Invoke-Native {
    # Run an external command via cmd /c with stderr merged into stdout INSIDE
    # cmd, so PowerShell's error stream never sees it. Completely immune to
    # $ErrorActionPreference = "Stop". Returns the exit code.
    param([string]$CommandLine)
    $output = cmd /c "$CommandLine 2>&1"
    if ($output) { $output | ForEach-Object { Write-Host $_ } }
    return $LASTEXITCODE
}

function Has-Winget { return Has-Command "winget" }

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath    = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path    = "$machinePath;$userPath"
}

function Set-EnvValue {
    param([string]$FilePath, [string]$Key, [string]$Value)
    if (-not (Test-Path $FilePath)) { return }
    $lines = Get-Content $FilePath -Encoding UTF8
    $found = $false
    $newLines = @()
    foreach ($line in $lines) {
        if ($line -match "^$Key=") {
            $newLines += "$Key=$Value"
            $found = $true
        } else {
            $newLines += $line
        }
    }
    if (-not $found) { $newLines += "$Key=$Value" }
    $newLines | Set-Content $FilePath -Encoding UTF8
}

# ── Banner ───────────────────────────────────────────────────────────────────

function Show-Banner {
    Write-Host ""
    Write-Host "                 o   o   o" -ForegroundColor DarkMagenta
    Write-Host "                 |   |   |" -ForegroundColor DarkMagenta
    Write-Host "             o--+-----------+--o" -ForegroundColor DarkMagenta
    Write-Host "             " -NoNewline; Write-Host "o--" -ForegroundColor DarkMagenta -NoNewline; Write-Host "|" -ForegroundColor Magenta -NoNewline; Write-Host "  N o v a  " -ForegroundColor White -NoNewline; Write-Host "|" -ForegroundColor Magenta -NoNewline; Write-Host "--o" -ForegroundColor DarkMagenta
    Write-Host "             " -NoNewline; Write-Host "o--" -ForegroundColor DarkMagenta -NoNewline; Write-Host "|" -ForegroundColor Magenta -NoNewline; Write-Host "    A I    " -ForegroundColor Cyan -NoNewline; Write-Host "|" -ForegroundColor Magenta -NoNewline; Write-Host "--o" -ForegroundColor DarkMagenta
    Write-Host "             " -NoNewline; Write-Host "o--" -ForegroundColor DarkMagenta -NoNewline; Write-Host "|" -ForegroundColor Magenta -NoNewline; Write-Host "  " -NoNewline; Write-Host "[" -ForegroundColor DarkGray -NoNewline; Write-Host " *** " -ForegroundColor Magenta -NoNewline; Write-Host "]" -ForegroundColor DarkGray -NoNewline; Write-Host "  " -NoNewline; Write-Host "|" -ForegroundColor Magenta -NoNewline; Write-Host "--o" -ForegroundColor DarkMagenta
    Write-Host "             o--+-----------+--o" -ForegroundColor DarkMagenta
    Write-Host "                 |   |   |" -ForegroundColor DarkMagenta
    Write-Host "                 o   o   o" -ForegroundColor DarkMagenta
    Write-Host ""
    Write-Host "        Your AI companion, built to vibe with you" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "        This installer will set up everything you need." -ForegroundColor DarkGray
    Write-Host "        Grab a coffee -- this might take a few minutes." -ForegroundColor DarkGray
    Write-Host ""
}

# ── Step 1: Python ───────────────────────────────────────────────────────────

function Ensure-Python {
    Write-Step "1/7" "Checking for Python 3.11+..."

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

# ── Step 2: LLM Provider ────────────────────────────────────────────────────

function Choose-LLMProvider {
    Write-Step "2/7" "Choose your LLM provider..."
    Write-Host ""
    Write-Host "         NovaAI works with local and cloud LLMs." -ForegroundColor DarkGray
    Write-Host "         Pick what works for you — you can always change it later in " -ForegroundColor DarkGray -NoNewline
    Write-Host ".env" -ForegroundColor White
    Write-Host ""

    $choice = Ask-Choice "Which LLM provider do you want to use?" @(
        "Ollama        — free, runs locally, no API key needed (recommended)",
        "OpenAI        — GPT-4o, GPT-4, etc. (requires API key)",
        "OpenRouter    — tons of models, one API key (requires API key)",
        "LM Studio     — local OpenAI-compatible server (no API key)",
        "Custom        — any OpenAI-compatible endpoint"
    ) 0

    $result = @{
        Provider = "ollama"
        ApiUrl   = ""
        ApiKey   = ""
        Model    = "dolphin3"
        NeedOllama = $true
    }

    switch ($choice) {
        0 {
            # Ollama
            $result.Provider = "ollama"
            $result.NeedOllama = $true
            $result.Model = Ask-Input "Which Ollama model?" "dolphin3"
            Write-Info "Popular models: dolphin3, llama3.1, mistral, gemma2, phi3"
            Write-Ok "Using Ollama with model: $($result.Model)"
        }
        1 {
            # OpenAI
            $result.Provider = "openai"
            $result.NeedOllama = $false
            $result.ApiUrl = "https://api.openai.com/v1/chat/completions"
            $result.ApiKey = Ask-Input "Enter your OpenAI API key"
            if (-not $result.ApiKey) {
                Write-Warn "No API key entered. You can add it later in .env (LLM_API_KEY=)"
            }
            $result.Model = Ask-Input "Which OpenAI model?" "gpt-4o-mini"
            Write-Info "Popular models: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo"
            Write-Ok "Using OpenAI with model: $($result.Model)"
        }
        2 {
            # OpenRouter
            $result.Provider = "openai"
            $result.NeedOllama = $false
            $result.ApiUrl = "https://openrouter.ai/api/v1/chat/completions"
            $result.ApiKey = Ask-Input "Enter your OpenRouter API key"
            if (-not $result.ApiKey) {
                Write-Warn "No API key entered. You can add it later in .env (LLM_API_KEY=)"
                Write-Info "Get a key at: https://openrouter.ai/keys"
            }
            $result.Model = Ask-Input "Which model?" "meta-llama/llama-3.1-8b-instruct:free"
            Write-Info "Browse models at: https://openrouter.ai/models"
            Write-Info "Free models: meta-llama/llama-3.1-8b-instruct:free, google/gemma-2-9b-it:free"
            Write-Ok "Using OpenRouter with model: $($result.Model)"
        }
        3 {
            # LM Studio
            $result.Provider = "openai"
            $result.NeedOllama = $false
            $result.ApiUrl = "http://localhost:1234/v1/chat/completions"
            $result.Model = Ask-Input "Which model is loaded in LM Studio?" "local-model"
            Write-Info "Make sure LM Studio's local server is running before you start NovaAI."
            Write-Ok "Using LM Studio at localhost:1234"
        }
        4 {
            # Custom
            $result.Provider = "openai"
            $result.NeedOllama = $false
            $result.ApiUrl = Ask-Input "Enter the API endpoint URL (e.g. https://my-server.com/v1/chat/completions)"
            $result.ApiKey = Ask-Input "Enter the API key (leave blank if none)"
            $result.Model = Ask-Input "Which model?" "default"
            Write-Ok "Using custom endpoint: $($result.ApiUrl)"
        }
    }

    return $result
}

# ── Step 3: Ollama (only if needed) ─────────────────────────────────────────

function Ensure-Ollama {
    param([bool]$Needed = $true)

    if (-not $Needed) {
        Write-Step "3/7" "Skipping Ollama (not needed for your provider)."
        return $null
    }

    Write-Step "3/7" "Checking for Ollama..."

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

    if (Ask-YesNo "Install Ollama via winget?") {
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

# ── Step 4: Clone / Download ────────────────────────────────────────────────

function Get-NovaAI {
    Write-Step "4/7" "Downloading NovaAI..."

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
            $gitExit = Invoke-Native "git pull origin $REPO_BRANCH --ff-only"
            Pop-Location
            if ($gitExit -ne 0) {
                Write-Warn "git pull failed (exit $gitExit). Trying fresh clone instead..."
                Remove-Item $INSTALL_DIR -Recurse -Force
                $gitExit = Invoke-Native "git clone --branch $REPO_BRANCH --single-branch $REPO_URL `"$INSTALL_DIR`""
                if ($gitExit -ne 0) { throw "git clone failed (exit $gitExit)." }
                Write-Ok "Fresh clone to $INSTALL_DIR"
            } else {
                Write-Ok "Updated via git pull."
            }
        } else {
            Write-Info "Cloning from GitHub..."
            $gitExit = Invoke-Native "git clone --branch $REPO_BRANCH --single-branch $REPO_URL `"$INSTALL_DIR`""
            if ($gitExit -ne 0) { throw "git clone failed (exit $gitExit)." }
            Write-Ok "Cloned to $INSTALL_DIR"
        }
    } else {
        Write-Info "git not found — downloading as ZIP..."
        $zipUrl  = "$REPO_URL/archive/refs/heads/$REPO_BRANCH.zip"
        $zipPath = "$env:TEMP\novaai-download.zip"
        $extractPath = "$env:TEMP\novaai-extract"

        Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath -UseBasicParsing
        if (Test-Path $extractPath) { Remove-Item $extractPath -Recurse -Force }
        Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force

        $innerDir = Get-ChildItem $extractPath | Select-Object -First 1
        if (-not (Test-Path $INSTALL_DIR)) { New-Item -ItemType Directory -Path $INSTALL_DIR -Force | Out-Null }
        Copy-Item -Path "$($innerDir.FullName)\*" -Destination $INSTALL_DIR -Recurse -Force

        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
        Remove-Item $extractPath -Recurse -Force -ErrorAction SilentlyContinue
        Write-Ok "Downloaded and extracted to $INSTALL_DIR"
    }
}

# ── Step 5: Setup + configure .env ──────────────────────────────────────────

function Run-Setup {
    param([string]$PythonCmd, [hashtable]$LLMConfig)

    Write-Step "5/7" "Running NovaAI setup..."
    Write-Info "This installs dependencies, downloads models, and prepares everything."
    Write-Host ""

    Push-Location $INSTALL_DIR
    try {
        if ($PythonCmd -eq "py") {
            $setupExit = Invoke-Native "py -3.11 setup.py --setup"
        } else {
            $setupExit = Invoke-Native "$PythonCmd setup.py --setup"
        }
        if ($setupExit -ne 0) { throw "Setup script failed." }
        Write-Ok "Setup complete."
    } finally {
        Pop-Location
    }

    # Configure .env with the chosen LLM provider
    $envFile = "$INSTALL_DIR\.env"
    if (Test-Path $envFile) {
        Write-Info "Configuring LLM provider in .env..."
        Set-EnvValue $envFile "LLM_PROVIDER" $LLMConfig.Provider
        Set-EnvValue $envFile "LLM_MODEL"    $LLMConfig.Model

        if ($LLMConfig.Provider -eq "ollama") {
            Set-EnvValue $envFile "OLLAMA_MODEL" $LLMConfig.Model
            Set-EnvValue $envFile "LLM_API_URL"  ""
            Set-EnvValue $envFile "LLM_API_KEY"  ""
        } else {
            Set-EnvValue $envFile "LLM_API_URL"   $LLMConfig.ApiUrl
            Set-EnvValue $envFile "LLM_API_KEY"   $LLMConfig.ApiKey
            Set-EnvValue $envFile "OPENAI_MODEL"  $LLMConfig.Model
            Set-EnvValue $envFile "OPENAI_API_URL" $LLMConfig.ApiUrl
            Set-EnvValue $envFile "OPENAI_API_KEY" $LLMConfig.ApiKey
        }
        Write-Ok "LLM provider configured."
    }
}

# ── Step 6: GPU ──────────────────────────────────────────────────────────────

function Ask-GPU {
    Write-Step "6/7" "GPU acceleration..."

    $choice = Ask-Choice "Do you have an NVIDIA GPU for faster voice synthesis?" @(
        "Yes — install CUDA-accelerated PyTorch",
        "No  — stick with CPU-only (works fine, just slower voice)",
        "Skip — I'll decide later"
    ) 0  # default to Yes

    if ($choice -eq 0) {
        Write-Host ""
        Write-Info "Pick the CUDA version that matches your GPU and driver."
        Write-Info "Not sure? Choose CUDA 12.8 — it works with most modern GPUs."
        Write-Info "Older GPUs (GTX 900/1000 series) or old drivers may need 11.8."
        Write-Host ""

        $cudaChoice = Ask-Choice "Which CUDA version?" @(
            "CUDA 12.8  — latest, RTX 20/30/40/50 series (driver 570+)",
            "CUDA 12.6  — stable, RTX 20/30/40 series (driver 560+)",
            "CUDA 12.4  — safe bet for most GPUs (driver 550+)",
            "CUDA 12.1  — older driver compat (driver 530+)",
            "CUDA 11.8  — legacy, GTX 900/1000 or very old drivers (driver 520+)"
        ) 0

        $cudaUrl = switch ($cudaChoice) {
            0 { "https://download.pytorch.org/whl/cu128" }
            1 { "https://download.pytorch.org/whl/cu126" }
            2 { "https://download.pytorch.org/whl/cu124" }
            3 { "https://download.pytorch.org/whl/cu121" }
            4 { "https://download.pytorch.org/whl/cu118" }
        }
        $cudaLabel = @("12.8", "12.6", "12.4", "12.1", "11.8")[$cudaChoice]

        Write-Info "Installing CUDA $cudaLabel PyTorch... (this downloads ~2 GB)"
        $venvPython = "$INSTALL_DIR\.venv\Scripts\python.exe"
        $pipExit = Invoke-Native "`"$venvPython`" -m pip install --upgrade --index-url $cudaUrl torch torchaudio -q"
        if ($pipExit -eq 0) {
            Write-Ok "CUDA $cudaLabel PyTorch installed. Voice synthesis will be much faster!"
        } else {
            Write-Warn "CUDA install had issues. CPU mode will still work fine."
        }
    } elseif ($choice -eq 1) {
        Write-Ok "Using CPU mode. You can add GPU support later."
        Write-Info "To add GPU later, run:"
        Write-Info "  $INSTALL_DIR\.venv\Scripts\python.exe -m pip install --upgrade --index-url https://download.pytorch.org/whl/cu128 torch torchaudio"
    } else {
        Write-Ok "Skipped. Default CPU mode works out of the box."
    }
}

# ── Step 7: Shortcut ────────────────────────────────────────────────────────

function Ask-Shortcut {
    Write-Step "7/7" "Desktop shortcut..."

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
    param([hashtable]$LLMConfig)

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
    Write-Host "    LLM:          " -NoNewline -ForegroundColor DarkGray
    $providerLabel = switch ($LLMConfig.Provider) {
        "ollama" { "Ollama ($($LLMConfig.Model))" }
        default  {
            if ($LLMConfig.ApiUrl -match "openrouter") { "OpenRouter ($($LLMConfig.Model))" }
            elseif ($LLMConfig.ApiUrl -match "openai\.com") { "OpenAI ($($LLMConfig.Model))" }
            elseif ($LLMConfig.ApiUrl -match "localhost:1234") { "LM Studio ($($LLMConfig.Model))" }
            else { "Custom ($($LLMConfig.Model))" }
        }
    }
    Write-Host $providerLabel -ForegroundColor White
    Write-Host ""
    Write-Host "    To launch NovaAI anytime:" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "      cd $INSTALL_DIR" -ForegroundColor Cyan
    Write-Host "      python setup.py" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "    Or use the desktop shortcut if you created one." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "    Change LLM provider anytime by editing " -ForegroundColor DarkGray -NoNewline
    Write-Host ".env" -ForegroundColor White -NoNewline
    Write-Host " in the install folder." -ForegroundColor DarkGray
    Write-Host ""
}

# ── Ollama helpers (start + pull model) ──────────────────────────────────────

function Start-OllamaAndPull {
    param([string]$OllamaExe, [string]$Model)

    if (-not $OllamaExe) { return }

    # Check if already running
    $running = $false
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 -UseBasicParsing
        $running = $true
    } catch { }

    if (-not $running) {
        Write-Info "Starting Ollama..."
        $appPath = "$env:LOCALAPPDATA\Programs\Ollama\ollama app.exe"
        if (Test-Path $appPath) {
            Start-Process $appPath -WindowStyle Hidden
        } else {
            Start-Process $OllamaExe -ArgumentList "serve" -WindowStyle Hidden
        }

        Write-Info "Waiting for Ollama to come online..."
        $online = $false
        for ($i = 0; $i -lt 60; $i++) {
            Start-Sleep -Seconds 1
            try {
                $null = Invoke-WebRequest -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 3 -UseBasicParsing
                $online = $true
                break
            } catch { }
        }
        if (-not $online) {
            Write-Warn "Ollama didn't start in time. You can start it manually later."
            return
        }
        Write-Ok "Ollama is online."
    } else {
        Write-Ok "Ollama is already running."
    }

    # Pull model
    Write-Info "Checking model '$Model'..."
    $showExit = Invoke-Native "`"$OllamaExe`" show $Model"
    if ($showExit -ne 0) {
        Write-Info "Pulling model '$Model'... (this may take a while)"
        $pullExit = Invoke-Native "`"$OllamaExe`" pull $Model"
        if ($pullExit -ne 0) {
            Write-Warn "Could not pull model '$Model'. You can pull it later: ollama pull $Model"
        } else {
            Write-Ok "Model '$Model' is ready."
        }
    } else {
        Write-Ok "Model '$Model' is already available."
    }
}

# ── Main ─────────────────────────────────────────────────────────────────────

function Main {
    Show-Banner

    # Step 1: Python
    $pythonCmd = Ensure-Python

    # Step 2: Choose LLM provider
    $llmConfig = Choose-LLMProvider

    # Step 3: Ollama (only if chosen)
    $ollamaExe = Ensure-Ollama -Needed $llmConfig.NeedOllama

    # Step 4: Download NovaAI
    Get-NovaAI

    # Step 5: Run setup + configure .env
    Run-Setup -PythonCmd $pythonCmd -LLMConfig $llmConfig

    # Start Ollama and pull model if needed
    if ($llmConfig.NeedOllama -and $ollamaExe) {
        Start-OllamaAndPull -OllamaExe $ollamaExe -Model $llmConfig.Model
    }

    # Step 6: GPU
    Ask-GPU

    # Step 7: Shortcut
    Ask-Shortcut

    Show-Finish -LLMConfig $llmConfig

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
