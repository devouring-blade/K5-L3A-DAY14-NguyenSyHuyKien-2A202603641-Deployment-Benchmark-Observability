$ErrorActionPreference = 'Stop'
$labRoot = Join-Path $PSScriptRoot '../06-lab-complete'
$envPath = Join-Path $labRoot '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    $secretBytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($secretBytes)
    $rng.Dispose()
    $localSecret = [Convert]::ToBase64String($secretBytes)
    $template = Get-Content -Raw (Join-Path $labRoot '.env.example')
    $content = $template -replace '(?m)^AGENT_API_KEY=.*$', "AGENT_API_KEY=$localSecret"
    [System.IO.File]::WriteAllText($envPath, $content, [System.Text.UTF8Encoding]::new($false))
}
Push-Location $labRoot
try {
    docker compose -p k5-day14-final up -d --build
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose failed' }
    Write-Output 'Agent: http://localhost:8000; API key is in ignored 06-lab-complete/.env'
} finally {
    Pop-Location
}
