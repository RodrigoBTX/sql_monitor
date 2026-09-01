<#
    install_service.ps1

    Regista o SQL Monitor como serviço do Windows, usando o NSSM — em vez
    de teres de correr manualmente os comandos "nssm install/set/start"
    (ver README.md, secção "Correr como serviço do Windows").

    Pré-requisitos:
      - Já compilaste o executável (.\build.bat) e existe dist\SQLMonitor.exe.
      - Tens o nssm.exe disponível — ou na mesma pasta deste script, ou
        algures no PATH (download em https://nssm.cc/download).
      - Corre este script num PowerShell como Administrador (o registo de
        serviços do Windows exige privilégios elevados).

    Uso, a partir da pasta do projeto:
        .\install_service.ps1

    Para outro nome de serviço, porta, ou instância (ex: vários clientes
    na mesma máquina, cada um com o seu próprio serviço):
        .\install_service.ps1 -ServiceName "SQLMonitorClienteX" -Port 5001

    Se já existir um serviço com o mesmo nome, este script pára-o e
    remove-o primeiro, e volta a instalar do zero. Isto é só para a
    primeira instalação (ou para uma reinstalação completa) — para
    atualizares para uma versão nova do executável no dia a dia NÃO
    precisas de voltar a correr isto: basta parar o serviço, substituir o
    ficheiro .exe e voltar a arrancar (ver README.md).
#>

param(
    [string]$ServiceName = "SQLMonitor",
    [string]$ExePath = "$PSScriptRoot\dist\SQLMonitor.exe",
    [string]$MonitorHost = "127.0.0.1",
    [int]$Port = 5000
)

$ErrorActionPreference = "Stop"

function Find-Nssm {
    $local = Join-Path $PSScriptRoot "nssm.exe"
    if (Test-Path $local) { return $local }
    $onPath = Get-Command nssm.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    Write-Host "Nao encontrei o nssm.exe (nem na pasta do projeto, nem no PATH)." -ForegroundColor Red
    Write-Host "Descarrega-o em https://nssm.cc/download e coloca o nssm.exe nesta pasta, ou no PATH, e volta a correr este script." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $ExePath)) {
    Write-Host "Nao encontrei $ExePath" -ForegroundColor Red
    Write-Host "Corre primeiro .\build.bat para gerar o executavel, ou indica o caminho certo com -ExePath." -ForegroundColor Red
    exit 1
}

$nssm = Find-Nssm
$exeFullPath = (Resolve-Path $ExePath).Path
$appDir = Split-Path $exeFullPath -Parent

& $nssm status $ServiceName *> $null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Ja existe um servico chamado '$ServiceName' -- a parar e remover para reinstalar..." -ForegroundColor Yellow
    & $nssm stop $ServiceName confirm | Out-Null
    & $nssm remove $ServiceName confirm | Out-Null
}

Write-Host "A registar o servico '$ServiceName'..."
& $nssm install $ServiceName $exeFullPath
& $nssm set $ServiceName AppDirectory $appDir
& $nssm set $ServiceName AppEnvironmentExtra "SQL_MONITOR_HOST=$MonitorHost`r`nSQL_MONITOR_PORT=$Port"
& $nssm set $ServiceName Start SERVICE_AUTO_START
& $nssm set $ServiceName DisplayName "SQL Monitor"
& $nssm set $ServiceName Description "Monitorizacao de instancias SQL Server -- ver README do projeto."

Write-Host "A iniciar o servico..."
& $nssm start $ServiceName

Write-Host ""
Write-Host "Pronto. Servico '$ServiceName' instalado e a correr." -ForegroundColor Green
Write-Host "Acede em http://$($MonitorHost):$Port"
Write-Host ""
Write-Host "Para atualizar depois de compilares uma versao nova:"
Write-Host "  nssm stop $ServiceName"
Write-Host "  (substitui o ficheiro $exeFullPath pelo novo .exe)"
Write-Host "  nssm start $ServiceName"
Write-Host ""
Write-Host "Para remover o servico por completo:"
Write-Host "  nssm remove $ServiceName confirm"
