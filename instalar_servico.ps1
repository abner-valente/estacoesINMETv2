# =============================================================================
# instalar_servico.ps1
# Execute UMA VEZ como Administrador para registrar o serviço Windows via NSSM.
# Pré-requisito: baixar nssm.exe de https://nssm.cc/download e colocar em:
#   C:\tools\nssm\nssm.exe   (ou ajuste $NssmExe abaixo)
# =============================================================================

$NssmExe     = "C:\tools\nssm\nssm.exe"
$ServiceName = "InmetSyncService"
$PwshExe     = (Get-Command pwsh.exe -ErrorAction SilentlyContinue)?.Source
if (-not $PwshExe) { $PwshExe = "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" }
$ServiceScript = "C:\abner_tmp\scripts\estacoesINMETv2\inmet_service.ps1"
$LogDir        = "C:\abner_tmp\scripts\estacoesINMETv2\logs"

# Validações
if (-not (Test-Path $NssmExe)) {
    Write-Error "NSSM não encontrado em '$NssmExe'. Baixe em https://nssm.cc/download e ajuste a variavel NssmExe."
    exit 1
}
if (-not (Test-Path $ServiceScript)) {
    Write-Error "Script de serviço não encontrado: $ServiceScript"
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "Instalando serviço '$ServiceName'..."

# Remove instalação anterior se existir
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Serviço já existe — removendo versão anterior..."
    & $NssmExe stop   $ServiceName confirm
    & $NssmExe remove $ServiceName confirm
}

# Instala o serviço
& $NssmExe install $ServiceName $PwshExe "-NonInteractive -ExecutionPolicy Bypass -File `"$ServiceScript`""

# Configura propriedades do serviço
& $NssmExe set $ServiceName DisplayName  "Sincronizador INMET"
& $NssmExe set $ServiceName Description  "Sincroniza dados meteorologicos da API INMET para o banco PostgreSQL diariamente."
& $NssmExe set $ServiceName Start        SERVICE_AUTO_START

# Redireciona stdout e stderr para arquivo de log do NSSM
& $NssmExe set $ServiceName AppStdout "$LogDir\service_stdout.log"
& $NssmExe set $ServiceName AppStderr "$LogDir\service_stderr.log"
& $NssmExe set $ServiceName AppRotateFiles     1
& $NssmExe set $ServiceName AppRotateSeconds   86400
& $NssmExe set $ServiceName AppRotateBytes     5242880   # 5 MB

# Reinício automático em caso de falha
& $NssmExe set $ServiceName AppExit Default Restart
& $NssmExe set $ServiceName AppRestartDelay 10000        # 10 segundos

# Inicia o serviço
Write-Host "Iniciando serviço..."
& $NssmExe start $ServiceName

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host ""
    Write-Host "Servico '$ServiceName' instalado e em execucao com sucesso." -ForegroundColor Green
    Write-Host "  - Gerenciar : services.msc  ou  nssm edit $ServiceName"
    Write-Host "  - Parar     : nssm stop  $ServiceName"
    Write-Host "  - Remover   : nssm remove $ServiceName confirm"
    Write-Host "  - Logs      : $LogDir\"
} else {
    Write-Warning "Servico instalado mas pode nao ter iniciado. Verifique com: Get-Service $ServiceName"
}
