<#
.SYNOPSIS
    Instala o Studio Native como tarefa agendada, rodando em segundo plano.

.DESCRIPTION
    Cria uma tarefa no Agendador do Windows que mantem o backend de pe sem
    janela nenhuma. O tunel `native.toffa.com.br` aponta para a porta 5050, e o
    site so responde enquanto esta tarefa estiver rodando.

    A tarefa roda **como o seu usuario do Windows**, e isso nao e detalhe:
    os tokens do TikTok sao cifrados com DPAPI, amarrados a sua conta. Rodando
    como SYSTEM, a decifragem falharia e o app pediria para reconectar a conta a
    cada renovacao de sessao, sem explicar o motivo.

.PARAMETER Gatilho
    AoLogar    (padrao) -- comeca quando voce entra no Windows. Nao pede senha.
    AoIniciar  -- comeca junto com o Windows, antes de voce desbloquear. O
                  Windows exige guardar a senha da sua conta para isso, e vai
                  pedir numa caixa propria. Precisa de PowerShell como
                  Administrador.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\instalar-servico.ps1
    powershell -ExecutionPolicy Bypass -File tools\instalar-servico.ps1 -Gatilho AoIniciar
#>
param(
    [ValidateSet('AoLogar', 'AoIniciar')]
    [string]$Gatilho = 'AoLogar'
)

$ErrorActionPreference = 'Stop'
$nomeTarefa = 'StudioNative'
$raiz = Split-Path -Parent $PSScriptRoot

# pythonw em vez de python: nao abre janela de console. Rodar do repositorio, e
# nao do executavel empacotado, e proposital -- o `dist/` e apagado a cada
# rebuild, e uma tarefa apontando para la quebraria no meio de um build.
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    throw "pythonw.exe nao encontrado no PATH. Instale o Python ou ajuste o script."
}

$appPy = Join-Path $raiz 'app.py'
if (-not (Test-Path $appPy)) { throw "Nao achei $appPy" }

Write-Host ""
Write-Host "Studio Native - instalacao do servico" -ForegroundColor Cyan
Write-Host "  repositorio : $raiz"
Write-Host "  interpreter : $pythonw"
Write-Host "  gatilho     : $Gatilho"
Write-Host ""

# --- Remove a tarefa anterior, se houver ------------------------------------
if (Get-ScheduledTask -TaskName $nomeTarefa -ErrorAction SilentlyContinue) {
    Write-Host "Removendo a tarefa anterior..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $nomeTarefa -Confirm:$false
}

# --- Peca a peca -------------------------------------------------------------
$acao = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$appPy`"" -WorkingDirectory $raiz

if ($Gatilho -eq 'AoIniciar') {
    $trigger = New-ScheduledTaskTrigger -AtStartup
} else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
}

# Segundo gatilho: um agendamento proprio que repete a cada 5 minutos.
#
# Duas coisas foram tentadas antes e NAO funcionam, ambas verificadas matando o
# processo e esperando:
#
# 1. `-RestartCount` do Agendador. Ele so age quando o Windows considera que a
#    tarefa *falhou*; processo morto a forca conta como tarefa encerrada.
# 2. Colar `.Repetition` no gatilho de logon. O `NextRunTime` fica vazio -- a
#    repeticao nao chega a ser agendada.
#
# Um gatilho `-Once` com repeticao e um agendamento de verdade e produz
# NextRunTime. Combinado com `MultipleInstances IgnoreNew`, cada disparo tenta
# subir: se ja estiver de pe, o Windows descarta a nova instancia; se tiver
# morrido, sobe de novo.
#
# Sem `-RepetitionDuration`: omitir significa "indefinidamente". Passar
# `[TimeSpan]::MaxValue`, receita que circula por ai, gera
# `P99999999DT23H59M59S`, que o Agendador recusa como fora do intervalo.
$vigia = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)

$config = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

# ExecutionTimeLimit zero = sem limite. O padrao do Windows mata a tarefa depois
# de 3 dias, e um servico que morre sozinho num sabado e pior que um que nunca
# subiu: ninguem percebe.

$tarefa = New-ScheduledTask -Action $acao -Trigger @($trigger, $vigia) -Settings $config `
    -Description "Studio Native - backend em segundo plano (porta 5050)"

# --- Registro ----------------------------------------------------------------
if ($Gatilho -eq 'AoIniciar') {
    Write-Host "O gatilho 'ao iniciar o sistema' exige a senha da sua conta do" -ForegroundColor Yellow
    Write-Host "Windows, guardada pelo Agendador. Ela sera pedida agora." -ForegroundColor Yellow
    Write-Host ""
    # -User + -Password faz a tarefa rodar mesmo sem ninguem logado, mantendo o
    # perfil do usuario carregado -- que e o que o DPAPI precisa.
    $cred = Get-Credential -UserName "$env:USERDOMAIN\$env:USERNAME" `
        -Message "Senha do Windows, para o servico subir antes de voce desbloquear"
    Register-ScheduledTask -TaskName $nomeTarefa -InputObject $tarefa `
        -User $cred.UserName `
        -Password $cred.GetNetworkCredential().Password | Out-Null
} else {
    Register-ScheduledTask -TaskName $nomeTarefa -InputObject $tarefa `
        -User "$env:USERDOMAIN\$env:USERNAME" | Out-Null
}

Write-Host "Tarefa registrada." -ForegroundColor Green

# --- Sobe agora e confere ----------------------------------------------------
Write-Host "Iniciando..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName $nomeTarefa
Start-Sleep -Seconds 8

$ok = $false
try {
    $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5050/api/health' -TimeoutSec 10 -UseBasicParsing
    $ok = ($r.StatusCode -eq 200)
} catch { $ok = $false }

Write-Host ""
if ($ok) {
    Write-Host "  Backend respondendo em http://127.0.0.1:5050" -ForegroundColor Green
    Write-Host "  Publico:              https://native.toffa.com.br" -ForegroundColor Green
} else {
    Write-Host "  O backend nao respondeu. Verifique com:" -ForegroundColor Red
    Write-Host "    Get-ScheduledTask StudioNative | Get-ScheduledTaskInfo"
    Write-Host "  Causa comum: ja existe algo na porta 5050 (o backend recusa subir nesse caso)."
}
Write-Host ""
Write-Host "Comandos uteis:" -ForegroundColor Cyan
Write-Host "  Start-ScheduledTask StudioNative     # subir"
Write-Host "  Stop-ScheduledTask  StudioNative     # parar"
Write-Host "  Unregister-ScheduledTask StudioNative -Confirm:`$false   # remover"
