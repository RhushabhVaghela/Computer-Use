# bridge.ps1
# Master script for OpenFang & Open-Interpreter Bridge
# Combines: Installation, Uninstallation, and Execution.

param (
    [Parameter(Mandatory=$true, Position=0)]
    [ValidateSet('install', 'uninstall', 'run', 'hand')]
    [string]$Command,

    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$ArgsRemaining
)

$ErrorActionPreference = "Stop"

# Central Paths & Settings
$scriptDir = $PSScriptRoot
$bridgeDir = Split-Path $scriptDir -Parent
$envName = "open-interpreter"
$pythonVersion = "3.11"
$projectDir = "d:\Agents-and-other-repos\open-interpreter"
$openfangRepoPath = "D:\Agents-and-other-repos\openfang"
$desktopPath = [System.IO.Path]::Combine([System.Environment]::GetFolderPath('Desktop'))
$icoUrl = "https://raw.githubusercontent.com/OpenInterpreter/open-interpreter/main/docs/assets/favicon.ico"
$icoPath = "$env:TEMP\open-interpreter.ico"
$openfangIcoPath = "$env:TEMP\openfang-logo.ico"
$handsPath = "$bridgeDir\openfang-hands"

switch ($Command) {
    'install' {
        Write-Host "=========================================================="
        Write-Host " OpenFang & Open-Interpreter Unified Installer (Stable) "
        Write-Host "=========================================================="
        Write-Host ""
        
        # 1. Install OpenFang
        Write-Host "[1/5] Checking OpenFang Installation..."
        $openfangExecutable = (Get-Command openfang -ErrorAction SilentlyContinue).Source
        if (-Not $openfangExecutable) {
            Write-Host "OpenFang is not installed. Installing OpenFang now via official script..."
            try {
                Invoke-RestMethod https://openfang.sh/install.ps1 | Invoke-Expression
            } catch {
                Write-Host "Warning: OpenFang installation script encountered an issue. Please install it manually if it fails."
            }
        } else {
            Write-Host "OpenFang is already installed at: $openfangExecutable"
        }

        # 2. Check for Conda
        Write-Host "`n[2/5] Checking Conda Environment '$envName'..."
        try {
            $condaBase = (conda info --base).Trim()
        } catch {
            Write-Error "Could not find Conda in your PATH. Please install Miniconda or Anaconda first."
            exit 1
        }
        $condaScriptsDir = "$condaBase\Scripts"

        $envExists = conda env list | Select-String -Pattern "^$envName\s"
        if (-Not $envExists) {
            Write-Host "Creating new conda environment '$envName' with Python $pythonVersion..."
            conda create -n $envName python=$pythonVersion -y
        } else {
            Write-Host "Environment '$envName' already exists. Skipping creation."
        }

        # 3. Install Packages
        Write-Host "`n[3/5] Installing Open-Interpreter from source..."
        if (Test-Path $projectDir) {
            Push-Location $projectDir
            try {
                Write-Host "Applying stability patch for Open-Interpreter..."
                $oiPatchPath = Join-Path $scriptDir "open_interpreter_init.patch"
                if (Test-Path $oiPatchPath) {
                    git apply $oiPatchPath
                }

                Write-Host "Installing Open-Interpreter, MCP, and OS-control dependencies..."
                conda run -n $envName pip install . mcp "starlette<0.38.0,>=0.37.2" "open-interpreter[os]" fastapi uvicorn python-multipart pyautogui pynput opencv-python Pillow
                
                Write-Host "Reverting Open-Interpreter repo to maintain a clean git state..."
                git reset --hard HEAD
            } catch {
                Write-Host "Warning: Failed to patch or install open-interpreter correctly."
                git reset --hard HEAD
            }
            Pop-Location
            Write-Host "Source directory not found. Installing latest stable version with OS support from PyPI..."
            conda run -n $envName pip install open-interpreter mcp "starlette<0.38.0,>=0.37.2" "open-interpreter[os]" fastapi uvicorn python-multipart pyautogui pynput opencv-python Pillow
        }

        # 4. Create Shortcuts (replaces create_shortcuts.ps1 and gen_icon.ps1 logic)
        Write-Host "`n[5/5] Creating Desktop Shortcuts..."

        $localIcoPath = "$projectDir\docs\assets\favicon.ico"
        if (Test-Path $localIcoPath) {
            $icoPath = $localIcoPath
            Write-Host "Using proper local Open-Interpreter icon."
        } else {
            Write-Host "Local icon not found, attempting to generate one..."
            try {
                [System.Reflection.Assembly]::LoadWithPartialName("System.Drawing") | Out-Null
                $bmp = New-Object System.Drawing.Bitmap(32, 32)
                $graph = [System.Drawing.Graphics]::FromImage($bmp)
                $brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::Blue)
                $graph.FillEllipse($brush, 0, 0, 32, 32)
                $icon = [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
                $fs = New-Object System.IO.FileStream($icoPath, [System.IO.FileMode]::Create)
                $icon.Save($fs)
                $fs.Close()
            } catch {
                $icoPath = ""
            }
        }

        $shell = New-Object -ComObject WScript.Shell

        # --- Shortcut 1: Open-Interpreter connected to OpenFang ---
        $fangShortcutPath = "$desktopPath\Open Interpreter (OpenFang Brain).lnk"
        $fangTargetPath = "powershell.exe"
        $fangArguments = "-ExecutionPolicy Bypass -NoExit -File `"$scriptDir\bridge.ps1`" run"
        
        $fangShortcut = $shell.CreateShortcut($fangShortcutPath)
        $fangShortcut.TargetPath = $fangTargetPath
        $fangShortcut.Arguments = $fangArguments
        $fangShortcut.WorkingDirectory = $bridgeDir
        $fangShortcut.WindowStyle = 1
        if ($icoPath -ne "") { $fangShortcut.IconLocation = $icoPath }
        $fangShortcut.Save()


        # --- Build OpenFang Desktop ---
        $openfangExePath = "$openfangRepoPath\target\release\openfang-desktop.exe"
        if (Test-Path $openfangRepoPath) {
            Write-Host "`nOpenFang repository found. Ensuring custom patch is applied and built..."
            Push-Location $openfangRepoPath
            
            $patchPath = "$scriptDir\openfang_isolation_utf8.patch"
            $patchApplied = $false
            
            try {
                # Check if patch is already applied
                $checkPatch = git apply --check --reverse "$patchPath" 2>$null
                if ($LASTEXITCODE -eq 0) {
                    Write-Host "Custom patch is already applied. Skipping application step."
                    $patchApplied = $true
                } else {
                    Write-Host "Applying custom hands isolation patch..."
                    git apply "$patchPath"
                    $patchApplied = $true
                }

                Write-Host "Building OpenFang desktop with custom features..."
                # Incremental build - only rebuilds what changed in the patch
                cargo build --release -p openfang-desktop
                
                if ($patchApplied) {
                    Write-Host "Temporarily reversing patch to maintain clean git state (incremental cache preserved)..."
                    git apply --reverse "$patchPath"
                }
            } catch {
                Write-Host "Warning: Build or patch operation encountered an error."
                Write-Host "Executing fallback build..."
                cargo build --release -p openfang-desktop
            }
            Pop-Location
        }
        
        # --- Shortcut 3: OpenFang Native ---
        $ofShortcutPath = "$desktopPath\OpenFang.lnk"
        Write-Host "`nConfiguring User Hands (Isolation Strategy)..."
        if (Test-Path $handsPath) {
            Write-Host "Setting OPENFANG_HANDS_PATH to $handsPath..."
            [System.Environment]::SetEnvironmentVariable("OPENFANG_HANDS_PATH", $handsPath, "User")
            $env:OPENFANG_HANDS_PATH = $handsPath
        }

        $ofShortcut = $shell.CreateShortcut($ofShortcutPath)
        if (Test-Path $openfangExePath) {
            $ofShortcut.TargetPath = "powershell.exe"
            $ofShortcut.Arguments = "-WindowStyle Hidden -Command `"`$env:OPENFANG_HANDS_PATH='$handsPath'; if (-Not (Test-Path `~/.openfang/config.toml`)) { Start-Process cmd -ArgumentList '/c echo Initializing OpenFang OS for the first time. Please follow the setup... && openfang init' -Wait }; Start-Process '$openfangExePath'`""
            $ofShortcut.WorkingDirectory = "$openfangRepoPath\target\release"
            $ofShortcut.IconLocation = $openfangExePath
        } else {
            $ofShortcut.TargetPath = "$env:SystemRoot\System32\cmd.exe"
            $ofShortcut.Arguments = "/K set OPENFANG_HANDS_PATH=$handsPath && echo Starting OpenFang Daemon... && openfang start"
            $ofShortcut.WorkingDirectory = $env:USERPROFILE
            
            try {
                Invoke-WebRequest -Uri "https://openfang.sh/favicon.ico" -OutFile $openfangIcoPath -UseBasicParsing
                $ofShortcut.IconLocation = $openfangIcoPath
            } catch {
                if ($openfangExecutable) { $ofShortcut.IconLocation = $openfangExecutable }
            }
        }

        $ofShortcut.WindowStyle = 7
        $ofShortcut.Save()

        # --- Inject MCP Configuration into OpenFang ---
        Write-Host "`n[5/6] Registering Open-Interpreter as an MCP tool in OpenFang..."
        $ofConfigDir = "$env:USERPROFILE\.openfang"
        $ofConfigFile = "$ofConfigDir\config.toml"
        $mcpScriptPath = "$bridgeDir\src\mcp_server.py"
        
        if (-Not (Test-Path $ofConfigDir)) {
            New-Item -ItemType Directory -Force -Path $ofConfigDir | Out-Null
        }

        try {
            $condaBase = (conda info --base).Trim()
            $oiPythonExe = "$condaBase\envs\$envName\python.exe"
            
            # Format paths for TOML (escape backslashes)
            $escapedPython = $oiPythonExe -replace '\\', '\\'
            $escapedScript = $mcpScriptPath -replace '\\', '\\'
            
            $mcpConfigBlock = @"

# --- Auto-injected by OpenFang-Interpreter-Bridge ---
[[mcp_servers]]
name = "open_interpreter"
timeout_secs = 600

[mcp_servers.transport]
type = "stdio"
command = "$escapedPython"
args = ["$escapedScript"]
# ----------------------------------------------------
"@

            if (Test-Path $ofConfigFile) {
                $currentConfig = Get-Content $ofConfigFile -Raw
                if ($currentConfig -notmatch 'name\s*=\s*"open_interpreter"') {
                    Write-Host "Appending MCP configuration to $ofConfigFile..."
                    Add-Content -Path $ofConfigFile -Value $mcpConfigBlock
                } else {
                    Write-Host "Open-Interpreter MCP is already registered in OpenFang."
                }
            } else {
                Write-Host "Creating new OpenFang config with MCP configuration..."
                Set-Content -Path $ofConfigFile -Value $mcpConfigBlock
            }
        } catch {
             Write-Host "Warning: Could not automatically register MCP server due to conda path errors. Please register manually."
        }

        # 6. Final Verification
        Write-Host "`n[6/6] Verifying installation..."
        try {
            conda run -n $envName interpreter --version | Out-Host
            Write-Host "Open-Interpreter verified successfully in environment '$envName'."
        } catch {
            Write-Host "Warning: Could not verify Open-Interpreter. Please check your conda environment manually."
        }

        Write-Host "`n=========================================================="
        Write-Host " Installation Complete! "
        Write-Host " Look on your Desktop for the new Shortcuts."
        Write-Host "=========================================================="
    }
    
    'uninstall' {
        Write-Host "=========================================================="
        Write-Host " OpenFang & Open-Interpreter Unified Uninstaller "
        Write-Host "=========================================================="
        Write-Host ""
        Write-Host "This script will permanently delete:"
        Write-Host "  - The '$envName' Conda environment"
        Write-Host "  - OpenFang's generated target build folder"
        Write-Host "  - OpenFang Desktop Executable"
        Write-Host "  - OpenFang configuration folder (~/.openfang)"
        Write-Host "  - Desktop Shortcuts"
        Write-Host ""

        $confirm = Read-Host "Are you sure you want to proceed? (Y/N)"
        if ($confirm -notmatch '^[Yy]$') {
            Write-Host "Uninstallation aborted."
            exit 0
        }

        Write-Host "`nStarting uninstallation...`n"

        # 1. Remove Conda Environment
        Write-Host "[1/5] Removing Conda Environment '$envName'..."
        $condaExecutable = (Get-Command conda -ErrorAction SilentlyContinue).Source
        if ($condaExecutable) {
            try {
                $envExists = conda env list | Select-String -Pattern "^$envName\s"
                if ($envExists) {
                    conda deactivate
                    conda deactivate
                    Write-Host "Deleting environment '$envName'..."
                    conda env remove -n $envName -y
                    Write-Host "cleaning conda environment..."
                    conda clean --all -y
                    Write-Host "Cleaning pip environment..."
                    pip cache purge
                    Write-Host "Environment '$envName' successfully removed."
                } else {
                    Write-Host "Environment '$envName' does not exist. Skipping."
                }
            } catch {
                Write-Host "Warning: Failed to remove conda environment. You may need to remove it manually."
            }
        } else {
            Write-Host "Conda not found. Skipping environment deletion."
        }

        # 2. Remove OpenFang Build Target Folder
        Write-Host "`n[2/5] Cleaning OpenFang Build Target Folder..."
        $openfangTargetDir = "$openfangRepoPath\target"
        if (Test-Path $openfangTargetDir) {
            Write-Host "Deleting cargo target folder: $openfangTargetDir"
            Remove-Item -Path $openfangTargetDir -Recurse -Force -ErrorAction SilentlyContinue
            Write-Host "Target folder removed."
        } else {
            Write-Host "OpenFang target folder not found. Skipping."
        }
        
        $localOiPath = "$env:LOCALAPPDATA\open-interpreter"
        if (Test-Path $localOiPath) {
             Write-Host "Deleting Open-Interperter from Local directory"
             Remove-Item -Path $localOiPath -Recurse -Force -ErrorAction SilentlyContinue
        }

        # 3. Remove OpenFang CLI Executable
        Write-Host "`n[3/5] Removing OpenFang CLI Executable..."
        $openfangExe = (Get-Command openfang -ErrorAction SilentlyContinue).Source
        if ($openfangExe) {
            Write-Host "Removing $openfangExe..."
            Remove-Item -Path $openfangExe -Force -ErrorAction SilentlyContinue
            Write-Host "Executable removed."
        } else {
            Write-Host "OpenFang CLI executable not found globally. Skipping."
        }

        # 4. Remove Configuration Directory
        Write-Host "`n[4/5] Removing OpenFang Configuration (~/.openfang)..."
        $openfangConfigDir = "$env:USERPROFILE\.openfang"
        if (Test-Path $openfangConfigDir) {
            # Write-Host "Deleting configuration directory: $openfangConfigDir"
            # Remove-Item -Path $openfangConfigDir -Recurse -Force -ErrorAction SilentlyContinue
            # Write-Host "Configuration directory removed."
        } else {
            Write-Host "Configuration directory not found. Skipping."
        }

        # 5. Remove Desktop Shortcuts
        Write-Host "`n[5/5] Removing Desktop Shortcuts..."
        $shortcuts = @(
            "$desktopPath\Open Interpreter.lnk",
            "$desktopPath\Open Interpreter (OpenFang Brain).lnk",
            "$desktopPath\OpenFang.lnk"
        )

        foreach ($shortcut in $shortcuts) {
            if (Test-Path $shortcut) {
                Write-Host "Deleting shortcut: $shortcut"
                Remove-Item -Path $shortcut -Force -ErrorAction SilentlyContinue
            }
        }
        Write-Host "Shortcuts removed."

        Write-Host "`n=========================================================="
        Write-Host " Uninstallation Complete! "
        Write-Host " (Note: Source code repositories are left unmodified.) "
        Write-Host "=========================================================="
    }
    
    'run' {
        # Replaces run_interpreter.ps1
        
        $env:OPENAI_API_BASE = "http://localhost:4200/v1"
        $env:OPENAI_API_KEY = "openfang-local" 

        Write-Host "Starting Open-Interpreter connected to OpenFang's API (http://localhost:4200/v1)"
        
        try {
            $condaBase = (conda info --base).Trim()
            $activateBat = "$condaBase\Scripts\activate.bat"
            # Launch interactively via cmd.exe to inherit the conda environment correctly
            Write-Host "Executing: interpreter --api_base http://localhost:1234/v1 --model openai/qwen3.5-35b-a3b --os -y"
            cmd.exe /c "`"$activateBat`" $envName && interpreter --api_base http://localhost:1234/v1 --model openai/qwen3.5-35b-a3b --os -y"
        } catch {
            Write-Host "Warning: Could not natively find conda base or $envName environment. Falling back to simple system interpreter call..."
            interpreter --api_base http://localhost:1234/v1 --model openai/qwen3.5-35b-a3b --os -y
        }
    }

    'hand' {
        if ($ArgsRemaining.Count -lt 1) {
            Write-Error "Usage: bridge.ps1 hand [register|unregister] [--all] [paths/names...]"
            exit 1
        }

        $action = $ArgsRemaining[0]
        $targets = @()
        if ($ArgsRemaining.Count -gt 1) {
            $targets = $ArgsRemaining[1..($ArgsRemaining.Count - 1)]
        }

        if (-not (Test-Path $handsPath)) {
            New-Item -ItemType Directory -Force -Path $handsPath | Out-Null
        }

        if ($action -eq 'register') {
            if ($targets.Count -eq 0) {
                Write-Error "Please provide one or more directory paths to register. Example: bridge.ps1 hand register ./my-hand ./another-hand"
                exit 1
            }

            foreach ($target in $targets) {
                if (Test-Path $target) {
                    $item = Get-Item $target
                    if ($item.PSIsContainer) {
                        $destination = Join-Path $handsPath $item.Name
                        if (Test-Path $destination) {
                            Write-Host "Hand '$($item.Name)' already exists. Overwriting..."
                            Remove-Item -Recurse -Force $destination
                        }
                        Copy-Item -Recurse -Path $target -Destination $destination
                        Write-Host "Successfully registered hand: $($item.Name)"
                    } else {
                        Write-Host "Warning: '$target' is not a directory. Hands must be folders."
                    }
                } else {
                    Write-Host "Warning: Path '$target' not found."
                }
            }
        } elseif ($action -eq 'unregister') {
            if ($targets.Count -eq 0) {
                Write-Error "Please provide hand names or --all to unregister. Example: bridge.ps1 hand unregister researcher-1"
                exit 1
            }

            if ($targets -contains '--all') {
                Write-Host "Unregistering ALL hands from $handsPath..."
                Remove-Item -Path "$handsPath\*" -Recurse -Force -ErrorAction SilentlyContinue
                Write-Host "All hands unregistered successfully."
            } else {
                foreach ($target in $targets) {
                    # Avoid accidentally triggering --all behavior via strange names
                    if ($target -eq '--all') { continue }
                    
                    $targetPath = Join-Path $handsPath $target
                    if (Test-Path $targetPath) {
                        Remove-Item -Recurse -Force $targetPath
                        Write-Host "Successfully unregistered hand: $target"
                    } else {
                        Write-Host "Warning: Hand '$target' not found in registry."
                    }
                }
            }
        } else {
            Write-Error "Invalid action: $action. Use 'register' or 'unregister'."
        }
    }
}
