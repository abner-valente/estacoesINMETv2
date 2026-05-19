# =============================================================================
# inmet_service.ps1
# Roda como serviço Windows (via NSSM) e executa a sincronização INMET
# todos os dias ao meio-dia, cobrindo hoje e os 3 dias anteriores.
# =============================================================================

$PythonExe  = "C:\abner_tmp\scripts\estacoesINMETv2\venv\Scripts\python.exe"
$ScriptPath = "C:\abner_tmp\scripts\estacoesINMETv2\main.py"
$LogDir     = "C:\abner_tmp\scripts\estacoesINMETv2\logs"
$DiasAtras  = 3
$Formato    = "xlsx"          # json | csv | xlsx
$HoraExec   = 12              # hora do dia para executar (formato 24h)

# Garante que a pasta de logs existe
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-ServiceLog {
    param([string]$Message, [string]$Level = "INFO")
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$ts [$Level] $Message"
    Write-Host $line
    Add-Content -Path "$LogDir\service.log" -Value $line -Encoding UTF8
}

function Get-NextNoon {
    $now    = Get-Date
    $noon   = $now.Date.AddHours($HoraExec)
    # Se já passou do meio-dia hoje, agenda para amanhã
    if ($now -ge $noon) { $noon = $noon.AddDays(1) }
    return $noon
}

Write-ServiceLog "Serviço INMET iniciado."

while ($true) {
    $nextRun     = Get-NextNoon
    $waitSeconds = [int]($nextRun - (Get-Date)).TotalSeconds

    Write-ServiceLog "Próxima execução agendada para $($nextRun.ToString('yyyy-MM-dd HH:mm:ss')) (aguardando ${waitSeconds}s)."
    Start-Sleep -Seconds $waitSeconds

    # Calcula o período: hoje e os N dias anteriores
    $dataFim = (Get-Date).ToString("yyyy-MM-dd")
    $dataIni = (Get-Date).AddDays(-$DiasAtras).ToString("yyyy-MM-dd")

    Write-ServiceLog "Iniciando sincronização | período=$dataIni → $dataFim  formato=$Formato"

    try {
        & $PythonExe $ScriptPath `
            --modo lista `
            --data-ini $dataIni `
            --data-fim $dataFim `
            --formato  $Formato

        if ($LASTEXITCODE -eq 0) {
            Write-ServiceLog "Sincronização concluída com sucesso."
        } else {
            Write-ServiceLog "Sincronização encerrou com código de saída $LASTEXITCODE." "WARN"
        }
    } catch {
        Write-ServiceLog "Erro inesperado ao executar o script Python: $_" "ERROR"
    }
}
