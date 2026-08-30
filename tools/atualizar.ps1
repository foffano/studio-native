<#
.SYNOPSIS
    Atualiza o Studio Native e reinicia o servico.

.DESCRIPTION
    Substitui o "Verificar atualizacoes" que existia quando o app era um .exe
    do Electron. Como servico, atualizar e outra coisa: puxar o codigo,
    reconstruir o front e reiniciar a tarefa agendada.

    Roda no PC que hospeda o app. Nao ha o que atualizar no celular -- ele so
    abre o endereco.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\atualizar.ps1
#>
param(
    # Nao mexe no git; so reconstroi o front e reinicia. Serve para quando voce
    # mesmo mudou o codigo.
    [switch]$SemGit
)

$ErrorActionPreference = 'Stop'
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

$tarefa = 'StudioNative'
$porta = 5050

function Passo($texto) { Write-Host "==> $texto" -ForegroundColor Cyan }

# --- 1. Codigo -------------------------------------------------------------
if (-not $SemGit) {
    Passo 'Puxando o codigo'
    # Alteracoes locais nao commitadas seriam sobrescritas por um pull sujo, e
    # o erro apareceria so la na frente, como um build estranho.
    $sujo = git status --porcelain
    if ($sujo) {
        Write-Host 'Ha alteracoes nao commitadas:' -ForegroundColor Yellow
        Write-Host $sujo
        throw 'Commite ou descarte antes de atualizar (ou use -SemGit).'
    }
    git pull --ff-only
}

# --- 2. Dependencias -------------------------------------------------------
Passo 'Conferindo dependencias do Python'
python -m pip install -q -r requirements.txt

Passo 'Conferindo dependencias do front'
Push-Location desktop
npm install --silent
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'npm install falhou.' }

# --- 3. Front --------------------------------------------------------------
Passo 'Construindo o front'
npm run build
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'O build do front falhou -- o servico NAO foi reiniciado.' }
Pop-Location

# --- 4. Servico ------------------------------------------------------------
# So aqui. Se o build falhou, o servico antigo continua de pe servindo a versao
# que funcionava, em vez de ficar fora do ar por causa de um erro de sintaxe.
Passo 'Reiniciando o servico'
Stop-ScheduledTask -TaskName $tarefa -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $tarefa

# --- 5. Confere ------------------------------------------------------------
Passo 'Esperando responder'
$ok = $false
foreach ($tentativa in 1..20) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:$porta/api/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch { }
}

if ($ok) {
    $v = (git rev-parse --short HEAD)
    Write-Host ''
    Write-Host "Atualizado e no ar (commit $v)." -ForegroundColor Green
    Write-Host '  local:   http://127.0.0.1:5050'
    Write-Host '  celular: https://native.toffa.com.br'
} else {
    Write-Host ''
    Write-Host "O servico nao respondeu em $porta depois de 20s." -ForegroundColor Red
    Write-Host 'Veja o que aconteceu com:'
    Write-Host '  Get-ScheduledTask StudioNative | Get-ScheduledTaskInfo'
    exit 1
}
