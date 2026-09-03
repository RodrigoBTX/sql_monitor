# SQL Monitor

Aplicação web (Flask + Bootstrap) para monitorizar o estado de instâncias
SQL Server: jobs do SQL Agent, sessões ativas, queries em execução/bloqueadas,
backups, espaço em disco, saúde de índices, deadlocks, Query Store, e
"custom checks" às tuas próprias tabelas/processos de negócio. Suporta
vários perfis (várias instâncias/clientes) na mesma instalação, cada um
totalmente separado dos outros.

## Pré-requisitos

1. Python 3.10+
2. **ODBC Driver for SQL Server** instalado na máquina (necessário para o `pyodbc`):
   - Windows: instala o "ODBC Driver 17 (ou 18) for SQL Server" da Microsoft.
   - Confirma o nome exato do driver instalado em "ODBC Data Sources" (64-bit),
     porque tens de o indicar nas Definições da app (por omissão está
     `ODBC Driver 17 for SQL Server`).

## Instalação (modo de desenvolvimento)

```bash
cd sql_monitor
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac
pip install -r requirements.txt
```

## Correr a aplicação

```bash
python run.py
```

Abre http://127.0.0.1:5000 no browser. Este `run.py` usa o servidor de
desenvolvimento do Flask — cómodo para testar, mas não pensado para ficar
a correr sem supervisão durante muito tempo. Para deixar a app a correr
"a sério" (por exemplo no teu PC o dia todo, ou num servidor de um
cliente), usa antes o `serve.py` (ver secção seguinte) ou compila-a e
regista-a como serviço do Windows (ver mais abaixo).

```bash
python serve.py
```

`serve.py` faz exatamente o mesmo que `run.py`, mas usa o `waitress`
(um servidor WSGI mais robusto) em vez do servidor de desenvolvimento.
Aceita duas variáveis de ambiente opcionais, `SQL_MONITOR_HOST` (por
omissão `127.0.0.1`, só a própria máquina — usa `0.0.0.0` se precisares
de aceder a partir de outro PC na rede) e `SQL_MONITOR_PORT` (por
omissão `5000`).

## Primeira utilização

- Vais criar uma conta de administrador (login/password).
- De seguida és encaminhado automaticamente para a configuração da ligação
  à instância SQL Server (também acessível depois em "Definições").
- Usa de preferência um **login SQL só de leitura** com permissão
  `VIEW SERVER STATE` (necessária para consultar sessões/queries em execução)
  e `SELECT` nas tabelas do `msdb` (jobs) e nas tuas tabelas de negócio.

## Vários perfis (várias instâncias/clientes)

Nas Definições há uma secção "Perfis". Por omissão só existe um, chamado
"Principal" — não precisas de fazer nada para continuares a usar a app
como até aqui. Se quiseres monitorizar mais do que uma instância SQL
Server (por exemplo, vários clientes) a partir da mesma instalação:

- **"+ Novo perfil"** nas Definições cria um perfil novo e independente,
  com a sua própria ligação SQL, os seus próprios custom checks e o seu
  próprio histórico de tendências — nada é partilhado entre perfis.
- Assim que tiveres 2 ou mais perfis, aparece um **dropdown na barra de
  navegação** com o nome do perfil atual: usa-o para trocar de instância
  a qualquer momento (por exemplo, entre uma ligação por VPN a um
  cliente e a tua própria instância).
- A app lembra-se sempre do último perfil que estavas a ver, mesmo depois
  de reiniciares.
- Só **um** perfil acumula histórico de tendências em segundo plano — o
  que estiver marcado com a estrela ("Tornar principal" nas Definições).
  Isto é propositado: manter isto leve e não sobrecarregar disco/SQL só
  por teres vários perfis configurados. Os outros perfis continuam a
  funcionar normalmente (dashboard, alertas, custom checks), só não
  acumulam histórico no separador "Tendências".

## Histórico de tendências — limpeza automática

Os snapshots gravados em segundo plano para a página "Tendências" são
mantidos durante **30 dias**; mais antigos que isso são apagados
automaticamente a cada nova captura. É o mesmo período da maior janela
que a própria página mostra ("Últimos 30 dias"), por isso nunca perdes
histórico que ainda consigas ver ali — só evita que a base de dados
cresça para sempre.

## Backup da base de dados local

Nas Definições há uma secção "Backup da base de dados local", com a data
do último backup feito e um botão **"Fazer backup agora"**. É sempre
manual — nada é feito automaticamente. Ao clicar, a app gera uma cópia
consistente de `instance/app.db` (perfis, ligações, custom checks e
histórico) e entrega-a ao browser como download; se tiveres a opção
"perguntar onde guardar cada ficheiro" ativa nas definições do teu
browser, ele pergunta-te a pasta — caso contrário, guarda na pasta de
Transferências por omissão.

## Notificações por email

Nas Definições há duas partes para isto:

1. **Servidor de email (SMTP)** — configuração única, partilhada por
   todos os perfis (normalmente só faz sentido teres uma conta/servidor a
   enviar). Preenche o servidor, porta, utilizador/password e o email de
   origem, e usa o botão "Enviar teste" para confirmares que está tudo
   certo antes de depender disto.
2. **Notificações por email**, dentro da configuração de cada perfil —
   ativa o interruptor e indica o email de destino desse perfil. Cada
   perfil tem o seu próprio interruptor e o seu próprio email (podem ser
   diferentes clientes/pessoas).

Só chega um email quando algo **passa** a estar mau (ex: um job começa a
falhar) — enquanto continuar por resolver, não repete o aviso. Quando
ficar resolvido e voltar a acontecer, avisa de novo. Isto corre em
segundo plano a cada 10 minutos, só para os perfis que tiverem
notificações ativas — os restantes nunca são tocados por este processo.

## Integridade dos dados (corrupção e estatísticas)

A página **Saúde da instância → Integridade** junta os dois sinais mais
diretos de que uma base de dados tem (ou pode vir a ter) um problema de
integridade:

- **Páginas suspeitas** (`msdb.dbo.suspect_pages`) — o próprio SQL Server
  regista aqui qualquer página que tenha falhado a verificação de
  checksum numa leitura/escrita normal. Se aparecer alguma marcada como
  "Por resolver", é corrupção real já detetada — o mais cedo possível,
  corre um `DBCC CHECKDB` à base de dados em causa para perceber a
  extensão do problema.
- **Último CHECKDB conhecido, por base de dados** — a app lê a data do
  último CHECKDB "limpo" que o motor tem registada (via
  `DBCC DBINFO`) e sinaliza a vermelho se estiver mais atrasado do que o
  limiar definido nas Definições ("CHECKDB atrasado acima de", 7 dias por
  omissão) ou se nunca tiver corrido.

**Importante:** a app nunca executa um `DBCC CHECKDB` — é uma operação
pesada (pode demorar muito tempo e consumir bastantes recursos numa base
grande) que deve continuar agendada à parte, normalmente como um SQL
Agent job semanal. Esta página só te avisa se esse job parou de correr,
nunca existiu, ou se já há corrupção detetada — não substitui o job em
si.

A mesma página **Índices** (agora "Índices e estatísticas") também passou
a mostrar as estatísticas mais desatualizadas da base de dados
selecionada — quando muitas linhas mudaram desde a última atualização, o
otimizador de queries pode escolher planos de execução maus com base
nesses números antigos. Isto não substitui a manutenção normal
(`UPDATE STATISTICS` ou a atualização automática do próprio SQL Server),
serve para saberes rapidamente onde essa manutenção está atrasada.

## Custom Checks — só leitura

Os **Custom Checks** só aceitam queries de leitura (`SELECT`, com CTEs via
`WITH`) — a app recusa gravar ou correr uma query que contenha
`INSERT`/`UPDATE`/`DELETE`/`DROP` ou outras instruções que alterem dados,
como proteção extra contra escreveres sem querer no sítio errado. Ainda
assim, o login SQL só de leitura acima continua a ser a proteção
principal.

## Exportar para CSV

Nas tabelas principais (Jobs, Sessões, Queries, Backups, Índices,
Estatísticas, Deadlocks, Capacidade, Integridade) há um botão para
exportar os dados visíveis para `.csv`, para abrires no Excel ou
partilhares.

## Esqueci-me da password de acesso à app

Não há recuperação por email (é uma app local). Usa o comando de
manutenção incluído para repor a password diretamente na base de dados
local:

```bash
cd sql_monitor
.venv\Scripts\activate        # Windows
flask --app run.py reset-password <o_teu_utilizador>
```

Vai pedir a nova password (duas vezes, para confirmar) sem a mostrar no
ecrã. Se o utilizador indicado não existir, é criado.

## Onde ficam guardados os dados

- `instance/app.db` — base de dados SQLite local: utilizadores, perfis,
  ligações SQL (password encriptada), custom checks, histórico de
  tendências e a configuração do servidor de email (a password também
  encriptada).
- `instance/secret.key` — chave de encriptação gerada automaticamente no
  primeiro arranque. **Não apagar nem partilhar este ficheiro.**
- `instance/secret_key` — chave usada para assinar o cookie de sessão
  (login) e os tokens de segurança dos formulários, também gerada
  automaticamente no primeiro arranque. **Não apagar nem partilhar.** Se
  for apagada, é gerada uma nova e todas as sessões com sessão iniciada
  nesse momento são invalidadas (é preciso voltar a fazer login).
- `instance/last_backup.txt` — só a data/hora do último backup manual
  feito (ver secção "Backup da base de dados local"), para aparecer nas
  Definições. Não tem informação sensível.
- `instance/logs/sqlmonitor.log` — ficheiro de log da aplicação (ver
  secção "Logs da aplicação" abaixo).

A pasta `instance/` fica sempre ao lado do `run.py`/`serve.py` (ou, numa
instalação compilada, ao lado do `.exe`) — nunca é preciso ires à procura
dela noutro sítio.

## Logs da aplicação

Como a app corre muitas vezes sem ninguém a ver (como serviço do
Windows, sem janela nenhuma aberta), fica um registo em disco do que se
passa em segundo plano: arranques, envio de notificações (com sucesso ou
falha) e falhas inesperadas nas verificações periódicas.

- Ficheiro: `instance/logs/sqlmonitor.log` (texto simples, abre em
  qualquer editor).
- Fica um ficheiro novo por dia (rotação à meia-noite), e só ficam
  guardados os **últimos 30 dias** — o mais antigo é apagado sozinho a
  cada rotação, tal como o histórico de tendências, para não acumular
  para sempre.
- Não é um log detalhado de cada pedido/página aberta (isso encheria o
  ficheiro sem necessidade) — só regista o que é relevante para
  perceberes se algo correu mal.

## Compilar para .exe

Para levares a app a um servidor/PC de cliente sem teres de lá instalar
Python, dá para compilar tudo num único `SQLMonitor.exe` com o
PyInstaller. Isto compila-se **uma vez, na tua máquina**; o `.exe`
resultante é o que copias para o cliente.

```bash
cd sql_monitor
.venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-build.txt
.\build.bat
```

(No PowerShell é preciso o `.\` à frente do nome do script — sem isso dá
erro "not recognized", porque por segurança o PowerShell não corre
comandos da pasta atual sem indicares explicitamente o caminho.
`build.bat` chama o `pyinstaller` com as opções corretas — inclui os
templates HTML, o ícone e os módulos do APScheduler que o PyInstaller
não deteta sozinho.) No fim, o executável fica em `dist\SQLMonitor.exe`.

**No PC/servidor do cliente:**

1. Copia só o `SQLMonitor.exe` (uma única pasta à tua escolha, ex:
   `C:\SQLMonitor\`).
2. Garante que o **ODBC Driver for SQL Server** está instalado nessa
   máquina (ver Pré-requisitos) — isto não vai dentro do `.exe`.
3. Corre `SQLMonitor.exe` (duplo clique, ou a partir da linha de
   comandos). Cria automaticamente uma pasta `instance\` ao lado do
   `.exe` na primeira vez que arranca, com a base de dados própria
   **daquela instalação** — totalmente separada de qualquer outra
   instalação do SQL Monitor que tenhas noutra máquina ou no teu PC.
4. Abre `http://127.0.0.1:5000` no browser dessa máquina (ou de outra
   máquina na mesma rede, se tiveres definido `SQL_MONITOR_HOST=0.0.0.0`
   antes de correr o `.exe`).

Cada instalação (cada `.exe` + a pasta `instance\` ao lado) é
completamente independente das outras — é essa a forma mais simples de
teres "uma instalação por cliente" sem misturar dados: um `.exe` por
servidor, cada um com o seu próprio ficheiro de base de dados.

## Correr como serviço do Windows

Para a app arrancar sozinha com o Windows e continuar a correr em
segundo plano (sem uma janela aberta nem alguém ter de fazer login),
regista o `.exe` compilado como serviço, usando o **NSSM** (Non-Sucking
Service Manager — gratuito, muito usado para isto).

### Forma rápida: `install_service.ps1`

1. Descarrega o NSSM em https://nssm.cc/download e coloca o `nssm.exe`
   (versão de 64-bit, pasta `win64\`) na pasta do projeto, ou no PATH.
2. Abre um PowerShell **como Administrador**, na pasta do projeto, e
   corre:
   ```
   .\install_service.ps1
   ```
   Isto regista e arranca o serviço "SQLMonitor" já com o `SQLMonitor.exe`
   compilado (`dist\SQLMonitor.exe`), sem precisares de preencher nenhuma
   janela à mão.
3. Se precisares de outro nome de serviço, porta, ou endereço (ex: várias
   instalações na mesma máquina, uma por cliente):
   ```
   .\install_service.ps1 -ServiceName "SQLMonitorClienteX" -Port 5001
   ```

O próprio script explica no fim como atualizar depois de uma versão nova
e como remover o serviço, se precisares.

### Forma manual (o que o script faz por trás)

1. Abre uma linha de comandos **como Administrador** e corre:
   ```
   nssm install SQLMonitor
   ```
2. Na janela que abre:
   - **Path**: aponta para o `SQLMonitor.exe` compilado
     (ex: `C:\SQLMonitor\SQLMonitor.exe`).
   - **Startup directory**: a pasta onde está o `.exe`
     (ex: `C:\SQLMonitor\`) — importante, é ali que a pasta `instance\`
     vai ser criada.
   - (Opcional) No separador **Environment**, podes definir
     `SQL_MONITOR_HOST=0.0.0.0` se quiseres aceder a partir doutras
     máquinas da rede.
   - Clica "Install service".
3. O serviço "SQLMonitor" já aparece em `services.msc`, com arranque
   automático. Para o iniciar já sem reiniciar o Windows:
   ```
   nssm start SQLMonitor
   ```

Para parar, remover ou reconfigurar mais tarde (com o script ou à mão):

```
nssm stop SQLMonitor
nssm restart SQLMonitor
nssm remove SQLMonitor confirm
nssm edit SQLMonitor
```

Como serviço, a app não mostra nenhuma janela — para veres se está a
funcionar, abre o browser em `http://127.0.0.1:5000`, consulta o estado
do serviço em `services.msc`, ou olha para `instance/logs/sqlmonitor.log`
(ver secção "Logs da aplicação").

## Número de versão

A app mostra um número de "build" discreto no rodapé de todas as páginas
(ex: "SQL Monitor · build 7") — útil quando dás suporte remoto a uma
instalação de cliente e precisas de saber rapidamente que versão está lá
instalada, sem ires ver o código.

Esse número vive no ficheiro `VERSION`, na raiz do projeto, e **incrementa
sozinho a cada commit** através de um hook do Git incluído no repositório
(`.githooks/pre-commit`). Só precisas de ativar isto **uma vez**, em cada
PC onde tenhas o repositório clonado:

```bash
cd sql_monitor
git config core.hooksPath .githooks
```

A partir daí, sempre que fizeres `git commit`, o número em `VERSION`
sobe automaticamente e essa alteração entra nesse mesmo commit — não
precisas de fazer mais nada. Se fizeres vários commits antes de um único
`git push`, o número sobe uma vez por commit (não por push).

## O que é a proteção CSRF

Todos os formulários da app (login, definições, custom checks) incluem
um token de segurança (CSRF) que confirma que o pedido veio mesmo do
formulário que viste no browser, e não de outro sítio a tentar enviar
pedidos em teu nome enquanto tens sessão iniciada. Se um formulário
ficar aberto muito tempo (sessão a expirar) e deres submit, pode aparecer
um aviso a pedir para tentares outra vez — não é um erro, é a proteção a
funcionar.

## Estrutura

```
app/
  __init__.py         # app factory, extensões, migração automática de schema
  models.py            # User, Profile, SqlConnection, CustomCheck, MetricSnapshot
  profiles.py           # gestão de perfis (criar/trocar/tornar principal/remover)
  crypto_utils.py        # encriptação da password guardada
  sql_client.py           # ligação pyodbc + queries às DMVs
  sql_guard.py             # validação "só SELECT/CTE" dos custom checks
  cli.py                    # comando flask reset-password
  auth.py                    # login / criação do 1º utilizador
  settings.py                 # configuração da ligação SQL + gestão de perfis
  dashboard.py                 # landing page com métricas gerais
  monitoring.py                 # jobs, sessões, queries, backups, capacidade,
                                 # índices, deadlocks, Query Store
  custom_checks.py               # checks personalizados às tabelas de negócio
  trends.py                       # histórico/gráficos de tendências
  snapshot.py                      # captura periódica de snapshots (só do
                                    # perfil principal) + limpeza automática +
                                    # arranca a verificação de notificações
  notifications.py                  # envio de email + lógica "passou a mau"
  backup.py                         # backup manual de instance/app.db
  version.py                         # lê o número de build do ficheiro VERSION
  logging_setup.py                    # configuração do log em instance/logs/
  templates/                          # Bootstrap 5
.githooks/
  pre-commit          # incrementa o VERSION a cada commit (ver README)
assets/
  sqlmonitor.ico       # ícone usado na compilação para .exe
VERSION                 # número de build atual (não editar à mão)
run.py             # arranque em modo de desenvolvimento
serve.py            # arranque em modo de produção (waitress) — é este que
                     # se compila com o PyInstaller
build.bat            # script que compila o serve.py num SQLMonitor.exe
install_service.ps1   # script que regista/arranca o serviço do Windows (NSSM)
requirements.txt      # dependências da app
requirements-build.txt # dependências só para compilar (PyInstaller)
```

---

Rodrigo BTX — 1 de setembro de 2026
