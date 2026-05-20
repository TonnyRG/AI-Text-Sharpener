# Launch the AI Text Sharpener review editor against the default project.
# Usage: double-click in Explorer, or `.\start-editor.ps1` from PowerShell.
# Pass extra args through to the editor: `.\start-editor.ps1 --port 8888`.
#
# If Windows blocks the script with "running scripts is disabled on this system",
# run once (in an admin PowerShell) :
#   Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

$ErrorActionPreference = "Stop"

$env:FLAGS_use_mkldnn = "0"
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = "True"
$env:PYTHONIOENCODING = "utf-8"

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "Virtualenv not found at $venvPython. Create it with: python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -e `".[dev]`""
    exit 1
}

$project = Join-Path $PSScriptRoot "examples\before_after\review_project.json"
$editorArgs = @("-m", "ai_text_sharpener.editor")
if (Test-Path $project) {
    $editorArgs += @("--project", $project)
} else {
    Write-Host "Default project not found at $project ; starting editor without --project." -ForegroundColor Yellow
}
$editorArgs += $args

& $venvPython @editorArgs
