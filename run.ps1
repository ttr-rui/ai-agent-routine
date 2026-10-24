# TaskMate launcher: use the pre-built Python environment, no system Python needed.
# Usage:
#   .\run.ps1          -> offline demo CLI (no API key required)
#   .\run.ps1 web      -> Streamlit web UI
#   .\run.ps1 live     -> real LLM mode (requires .env with LLM_API_KEY)
#   .\run.ps1 test     -> run all 5 verification suites
param(
    [string]$Mode = "demo"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Py = "C:\Users\ruijie\.workbuddy\binaries\python\envs\default\Scripts\python.exe"

if (-not (Test-Path $Py)) {
    Write-Host "[ERROR] Python env not found: $Py" -ForegroundColor Red
    exit 1
}

$env:PYTHONIOENCODING = "utf-8"
Set-Location $Root

switch ($Mode.ToLower()) {
    "demo" {
        $env:USE_MOCK_LLM = "1"
        Write-Host "[TaskMate] offline demo mode (rule-based mock brain, no API key)" -ForegroundColor Cyan
        & $Py main.py
    }
    "live" {
        $env:USE_MOCK_LLM = "0"
        Write-Host "[TaskMate] live mode (real LLM, needs .env)" -ForegroundColor Cyan
        & $Py main.py
    }
    "web" {
        $env:USE_MOCK_LLM = "1"
        Write-Host "[TaskMate] web UI in offline demo mode" -ForegroundColor Cyan
        & $Py -m streamlit run ui/app.py
    }
    "test" {
        foreach ($t in @("tests\selftest.py", "tests\test_static_checks.py",
                         "tests\test_mcp_integration.py", "tests\test_agent_loop_mock.py",
                         "tests\test_task_views.py", "tests\test_e2e.py", "tests\test_ui_smoke.py")) {
            Write-Host "`n===== $t =====" -ForegroundColor Cyan
            & $Py $t
            if ($LASTEXITCODE -ne 0) {
                Write-Host "[FAIL] $t" -ForegroundColor Red
                exit 1
            }
        }
        Write-Host "`n[ALL PASS] 82 assertions, 7 suites" -ForegroundColor Green
    }
    default {
        Write-Host "Unknown mode '$Mode'. Use: demo | live | web | test" -ForegroundColor Yellow
        exit 1
    }
}
