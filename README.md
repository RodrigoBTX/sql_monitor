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

## Custom Checks — só leitura

Os **Custom Checks** só aceitam queries de leitura (`SELECT`, com CTEs via
`WITH`) — a app recusa gravar ou correr uma query que contenha
`INSERT`/`UPDATE`/`DELETE`/`DROP` ou outras instruções que alterem dados,
como proteção extra contra escreveres sem querer no sítio errado. Ainda
assim, o login SQL só de leitura acima continua a ser a proteção
principal.

## Exportar para CSV

Nas tabelas principais (Jobs, Sessões, Queries, Backups, Índices,
Deadlocks, Capacidade) há um botão para exportar os dados visíveis para
`.csv`, para abrires no Excel ou partilhares.

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
  ligações SQL (password encriptada), custom checks e histórico de
  tendências.
- `instance/secret.key` — chave de encriptação gerada automaticamente no
  primeiro arranque. **Não apagar nem partilhar este ficheiro.**
- `instance/secret_key` — chave usada para assinar o cookie de sessão
  (login) e os tokens de segurança dos formulários, também gerada
  automaticamente no primeiro arranque. **Não apagar nem partilhar.** Se
  for apagada, é gerada uma nova e todas as sessões com sessão iniciada
  nesse momento são invalidadas (é preciso voltar a fazer login).

A pasta `instance/` fica sempre ao lado do `run.py`/`serve.py` (ou, numa
instalação compilada, ao lado do `.exe`) — nunca é preciso ires à procura
dela noutro sítio.

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
build.bat
```

(`build.bat` chama o `pyinstaller` com as opções corretas — inclui os
templates HTML e os módulos do APScheduler que o PyInstaller não deteta
sozinho.) No fim, o executável fica em `dist\SQLMonitor.exe`.

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
Service Manager — gratuito, muito usado para isto):

1. Descarrega o NSSM em https://nssm.cc/download e extrai o `nssm.exe`
   (usa a versão de 64-bit, pasta `win64\`).
2. Abre uma linha de comandos **como Administrador** e corre:
   ```
   nssm install SQLMonitor
   ```
3. Na janela que abre:
   - **Path**: aponta para o `SQLMonitor.exe` compilado
     (ex: `C:\SQLMonitor\SQLMonitor.exe`).
   - **Startup directory**: a pasta onde está o `.exe`
     (ex: `C:\SQLMonitor\`) — importante, é ali que a pasta `instance\`
     vai ser criada.
   - (Opcional) No separador **Environment**, podes definir
     `SQL_MONITOR_HOST=0.0.0.0` se quiseres aceder a partir doutras
     máquinas da rede.
   - Clica "Install service".
4. O serviço "SQLMonitor" já aparece em `services.msc`, com arranque
   automático. Para o iniciar já sem reiniciar o Windows:
   ```
   nssm start SQLMonitor
   ```

Para parar, remover ou reconfigurar mais tarde:

```
nssm stop SQLMonitor
nssm restart SQLMonitor
nssm remove SQLMonitor confirm
nssm edit SQLMonitor
```

Como serviço, a app não mostra nenhuma janela — para veres se está a
funcionar, abre o browser em `http://127.0.0.1:5000` (ou consulta o
estado do serviço em `services.msc`).

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
                                    # perfil principal)
  templates/                       # Bootstrap 5
run.py             # arranque em modo de desenvolvimento
serve.py            # arranque em modo de produção (waitress) — é este que
                     # se compila com o PyInstaller
build.bat            # script que compila o serve.py num SQLMonitor.exe
requirements.txt      # dependências da app
requirements-build.txt # dependências só para compilar (PyInstaller)
```

---

Rodrigo BTX — 31 de agosto de 2026
