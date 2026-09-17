<#
.SYNOPSIS
    Empacota os dados do Studio Native para levar a uma VPS Linux.

.DESCRIPTION
    Desliga a tarefa agendada, para o app nao escrever no banco no meio da
    copia, e gera um .tar.gz com %APPDATA%\StudioNative sem as pastas
    temporarias. Do outro lado, tools/importar-dados.sh poe tudo no lugar.

    A tarefa fica DESLIGADA de proposito. Com o app de pe nos dois lugares, os
    dois renovariam sessoes do TikTok e responderiam por conta propria -- e o
    tunel so pode apontar para um deles.

    Para voltar a usar no Windows:
        Enable-ScheduledTask StudioNative; Start-ScheduledTask StudioNative

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\exportar-para-vps.ps1
#>
param(
    [string]$Destino = (Join-Path ([Environment]::GetFolderPath('Desktop')) 'studio-dados.tar.gz')
)

$ErrorActionPreference = 'Stop'
$tarefa = 'StudioNative'
$pasta = Join-Path $env:APPDATA 'StudioNative'

if (-not (Test-Path $pasta)) { throw "Nao achei $pasta" }
if (-not (Get-Command tar.exe -ErrorAction SilentlyContinue)) {
    throw 'tar.exe nao encontrado. Ele vem com o Windows 10 (1803) ou mais novo.'
}

# --- 1. Desliga a tarefa ------------------------------------------------------
# So parar nao basta: o gatilho que repete a cada 5 minutos subiria o app de
# novo no meio da copia.
if (Get-ScheduledTask -TaskName $tarefa -ErrorAction SilentlyContinue) {
    Write-Host 'Desligando a tarefa agendada...' -ForegroundColor Cyan
    Disable-ScheduledTask -TaskName $tarefa | Out-Null
    Stop-ScheduledTask -TaskName $tarefa -ErrorAction SilentlyContinue
}

# --- 2. Ninguem mais servindo na 5050 ----------------------------------------
# Uma instancia aberta a mao (python app.py) continuaria gravando no banco.
Start-Sleep -Seconds 3
$escutando = Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction SilentlyContinue
if ($escutando) {
    $processo = Get-Process -Id $escutando[0].OwningProcess -ErrorAction SilentlyContinue
    throw "Ainda ha algo servindo na porta 5050 ($($processo.ProcessName), PID $($processo.Id)). Feche e rode de novo."
}

# --- 3. Empacota --------------------------------------------------------------
# O studio.db-wal vai junto: o app foi parado a forca, e as ultimas gravacoes
# podem estar so nele.
Write-Host "Empacotando $pasta ..." -ForegroundColor Cyan
tar.exe -czf $Destino -C $env:APPDATA `
    --exclude 'StudioNative/uploads' `
    --exclude 'StudioNative/library_staging' `
    StudioNative
if ($LASTEXITCODE -ne 0) { throw 'O tar falhou.' }

$tamanho = [math]::Round((Get-Item $Destino).Length / 1MB, 1)
Write-Host ''
Write-Host "Pronto: $Destino ($tamanho MB)" -ForegroundColor Green
Write-Host ''
Write-Host 'Agora mande para a VPS e importe:' -ForegroundColor Cyan
Write-Host "  scp `"$Destino`" usuario@sua-vps:/tmp/studio-dados.tar.gz"
Write-Host '  ssh -t usuario@sua-vps sudo /opt/studio-native/tools/importar-dados.sh /tmp/studio-dados.tar.gz'
Write-Host ''
Write-Host 'A tarefa do Windows ficou desligada. Para voltar a usar aqui:' -ForegroundColor Yellow
Write-Host '  Enable-ScheduledTask StudioNative; Start-ScheduledTask StudioNative'
