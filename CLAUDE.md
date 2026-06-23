# Cantinho do Caruru — Documentação Técnica

Sistema de gestão de pedidos para uma confeitaria baiana. Desenvolvido em Streamlit, hospedado no Streamlit Community Cloud. Versão atual: **21.0**.

---

## Arquitetura geral

```
app.py              — Entrypoint: login, init de session_state, sidebar, roteamento de abas
auth.py             — Autenticação por senha (rate-limit + secrets.compare_digest)
config.py           — Constantes, logger rotativo, fuso horário, preço base
database.py         — I/O CSV com file locking (fcntl), backups, histórico de alterações
sheets.py           — Integração Google Sheets (backup em nuvem + restauração)
pedidos.py          — CRUD de pedidos + sincronização de clientes
utils.py            — Validações (telefone, hora), formatação (BRL, WhatsApp links), badges HTML
pdf.py              — Geração de PDFs (recibos, lista de pedidos, clientes)
telegram_format.py  — Formatação compartilhada das mensagens Telegram (stdlib-only)
notificador.py      — Script standalone executado pelo GitHub Actions (Telegram)
views/
  novo_pedido.py    — Formulário de criação de pedido
  gerenciar.py      — Lista, edição e exclusão de pedidos com filtros
  pedidos_dia.py    — Visão de pedidos do dia (edição rápida de status/pagamento)
  clientes.py       — Cadastro, lista e exclusão de clientes
  historico.py      — Log de alterações
  relatorios.py     — Relatórios e exportação
  manutencao.py     — Logs, backups, Google Sheets, Telegram, configurações
  promocoes.py      — Funcionalidade de promoções
  historico.py      — Histórico de alterações por pedido
```

---

## Persistência de dados

### Camada primária — CSV local (efêmero no Streamlit Cloud)

| Arquivo | Conteúdo |
|---------|----------|
| `banco_de_dados_caruru.csv` | Pedidos |
| `banco_de_dados_clientes.csv` | Clientes |
| `historico_alteracoes.csv` | Log de 1000 últimas alterações |
| `config.json` | Configurações (preço base) |
| `system_errors.log` | Log rotativo (5 MB, 3 backups) |

**Atenção:** O Streamlit Community Cloud hiberna contêineres após inatividade e **apaga todos os arquivos**. Por isso o Google Sheets é o backup permanente.

### Camada secundária — Google Sheets (permanente)

- Planilha: `"Cantinho do Caruru - Dados"`
- Abas: `Pedidos`, `Clientes`, `Backups_Log`, `Config`
- Sincronização automática após cada operação de escrita (`sincronizar_automaticamente`)
- Auto-restore na inicialização: se CSV vazio e Sheets conectado, restaura automaticamente

### Invariante crítico de datas

A coluna `Data` é sempre `datetime.date` (Python nativo) em memória. Ao salvar no CSV, `_serializar_data()` converte para string ISO `YYYY-MM-DD`. Ao carregar, `pd.to_datetime(..., errors="coerce").dt.date` converte de volta.

**Nunca** escrever strings brutas na coluna `Data` sem passar por `_serializar_data()` — qualquer formato não reconhecido vira `""` no CSV e `NaT` no próximo carregamento.

### File locking

Todas as escritas em CSV usam `file_lock(filepath)` com `fcntl.flock` e timeout de 30s. Escreve em `.tmp` e faz `shutil.move` atômico para evitar corrupção parcial.

---

## Fluxo de inicialização (`app.py`)

```
1. check_password()         — bloqueia se não autenticado
2. carregar_pedidos()       — CSV → session_state.pedidos
3. carregar_clientes()      — CSV → session_state.clientes
4. auto-restore             — se pedidos vazio E Sheets OK → sincronizar(receber)
   ↳ auto_restore_tentado = True ANTES de st.rerun() (evitar loop infinito)
5. sidebar                  — relógio, métricas do dia, sync automático toggle
6. tabs                     — roteamento por aba selecionada
```

---

## Secrets necessários

### Streamlit Cloud (`.streamlit/secrets.toml`)

```toml
password = "senha_do_app"
chave_pix = "79999999999"

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN RSA PRIVATE KEY-----\n..."
client_email = "...@....iam.gserviceaccount.com"
# ... campos completos do JSON da service account
```

### GitHub Actions (Settings → Secrets → Actions)

| Secret | Valor |
|--------|-------|
| `GCP_SERVICE_ACCOUNT` | JSON completo da service account (sem aspas) |
| `TELEGRAM_BOT_TOKEN` | Token do bot (`123456789:ABCxyz...`) |
| `TELEGRAM_CHAT_ID` | ID numérico do chat Telegram |

---

## Notificações Telegram (GitHub Actions)

**Arquivo:** `notificador.py` + `.github/workflows/notificar_pedidos.yml`

- Cron: toda hora entre 07h e 15h UTC (04h–12h Brasília)
- Só envia se hora atual (Brasília) = horário configurado na aba `Config` do Sheets (chave `notification_hour`, default = 7)
- `workflow_dispatch` ignora verificação de horário (sempre envia)
- Sempre envia pedidos do **dia seguinte** (24h de antecedência)
- Formato: nome em Title Case, `N kg de Caruru`, `N kg de Bobó`, status de pagamento por cliente

### Configurar horário de envio

Na aba Manutenção → Telegram → ⏰ Horário Automático. Salva na aba `Config` do Sheets.

---

## Autenticação

- Senha única via `st.secrets["password"]`
- Comparação com `secrets.compare_digest()` (tempo constante, mitiga timing attack)
- Rate-limit exponencial: `2^n` segundos de delay após falha (cap 30s)
- Bloqueio após 5 tentativas (requer reload da página)

---

## Padrões de código críticos

### Serialização de datas ao salvar

```python
# Em database.py: salvar_pedidos()
def _serializar_data(x):
    if hasattr(x, 'strftime'):
        return x.strftime('%Y-%m-%d') if pd.notna(x) else ""
    s = str(x).strip()
    if not s or s in ('nan', 'NaT', 'None'):
        return ""
    try:
        return datetime.strptime(s[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
    except ValueError:
        pass
    try:
        return datetime.strptime(s, '%d/%m/%Y').strftime('%Y-%m-%d')
    except ValueError:
        pass
    return ""
```

Cobre: `date`, `Timestamp`, `NaT`, strings ISO e BR, `None`.

### Serialização de horas ao salvar

```python
def _serializar_hora(x, default="12:00"):
    if isinstance(x, time):
        return x.strftime('%H:%M')
    s = str(x).strip() if x is not None else ""
    return s if s and s not in ('nan', 'NaT', 'None', 'nat') else default
```

Strings `"nan"` eram gravadas literalmente no CSV — esta função impede isso.

### Guard antes de `.iloc[0]`

Qualquer busca por ID antes de `.iloc[0]` deve ter guard explícito:

```python
match = df[df['ID_Pedido'] == id_pedido]
if match.empty:
    st.error("Pedido não encontrado")
    st.stop()
pedido = match.iloc[0]
```

Padrão aplicado em: `gerenciar.py:251`, `gerenciar.py:344`, `pedidos_dia.py:262`.

### st.rerun() e flags de session_state

Toda flag de controle deve ser setada **antes** de `st.rerun()`:

```python
st.session_state['flag'] = True  # ← primeiro
st.rerun()                       # ← depois
```

`st.rerun()` interrompe a execução imediatamente; código depois dele nunca roda.

### Sync do Sheets no modo "receber"

Busca **ambas** as abas antes de salvar qualquer uma:

```python
df_pedidos, msg_p = carregar_do_sheets(client, "Pedidos")
df_clientes, msg_c = carregar_do_sheets(client, "Clientes")
# só salva depois que ambas foram carregadas
```

### Entrada (pagamento antecipado) e cálculo de "falta"

`Entrada` é o valor em R$ pago adiantado, complementar ao `Desconto` (%). A regra
em `telegram_format.calcular_falta(pagamento, valor, entrada)` é:

1. `Pagamento == "PAGO"` → falta `0` (quitado, ignora entrada).
2. `entrada > 0` → falta `max(0, valor - entrada)` (precisão sobrepõe o status textual).
3. Sem entrada → comportamento legado: `NÃO PAGO` → valor cheio, `METADE` → metade.

Invariante: `Entrada` nunca excede `Valor` — clampado em `criar_pedido`,
`atualizar_pedido` e nos forms de edição. Retrocompatível: pedidos/Sheets sem a
coluna carregam `Entrada = 0.0`.

### Carregar do Sheets com parse de datas

`carregar_do_sheets()` retorna strings brutas. A coluna `Data` é parseada logo após:

```python
df = pd.DataFrame(dados[1:], columns=dados[0])
if "Data" in df.columns:
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.date
```

---

## Schema das abas do Google Sheets

### Aba `Pedidos`

| Coluna | Tipo | Notas |
|--------|------|-------|
| ID_Pedido | int | Sequencial, sem gaps |
| Cliente | str | |
| Caruru | float | kg |
| Bobo | float | kg |
| Valor | float | R$ calculado |
| Data | str | `YYYY-MM-DD` |
| Hora | str | `HH:MM` |
| Hora_Entrega | str | `HH:MM` ou vazio |
| Status | str | `🔴 Pendente` / `🟡 Em Produção` / `✅ Entregue` / `🚫 Cancelado` |
| Pagamento | str | `PAGO` / `NÃO PAGO` / `METADE` |
| Contato | str | Apenas dígitos |
| Desconto | float | % |
| Entrada | float | R$ pago antecipadamente (nunca excede `Valor`) |
| Observacoes | str | |
| Extra | bool | |
| Vegano | bool | |
| Delivery | bool | |

### Aba `Config`

| Chave | Valor | Descrição |
|-------|-------|-----------|
| `notification_hour` | int | Hora (Brasília) do envio automático Telegram |

---

## Bugs corrigidos (histórico recente)

| Bug | Causa | Correção |
|-----|-------|----------|
| Datas virando `NaT` após sync Sheets | `carregar_do_sheets` retornava strings; `salvar_pedidos` não sabia serializar → gravava `""` no CSV → `NaT` no reload | Parse em `carregar_do_sheets` + `_serializar_data` robusto |
| Loop infinito de auto-restore | `st.rerun()` chamado antes de setar `auto_restore_tentado = True` | Flag setada antes do rerun |
| `UnboundLocalError` em `manutencao.py` | Imports dentro de função criavam variáveis locais usadas antes pela Python | Movidos para imports de nível de módulo |
| Horas `"nan"` gravadas no CSV | `pd.isna("nan")` retorna `False` — strings `"nan"` passavam pelo lambda | `_serializar_hora` filtra strings inválidas explicitamente |
| `IndexError` ao editar pedido excluído | `.iloc[0]` sem guard | Guard + mensagem clara + limpeza de estado |
| 400 Bad Request Telegram | `MarkdownV2` com `parse_mode: "Markdown"` | Corrigido para Markdown v1 |

---

## Variáveis de session_state relevantes

| Chave | Tipo | Descrição |
|-------|------|-----------|
| `pedidos` | DataFrame | Todos os pedidos em memória |
| `clientes` | DataFrame | Todos os clientes |
| `password_correct` | bool | Autenticado? |
| `auth_tentativas` | int | Contador de falhas de login |
| `auto_restore_tentado` | bool | Evita loop de auto-restore |
| `sync_automatico_habilitado` | bool | Toggle de sync |
| `sync_stats` | dict | Métricas de sincronização |
| `pedido_em_edicao_id` | int\|None | ID do pedido em edição em gerenciar.py |
| `pedido_em_edicao_dia_id` | int\|None | ID do pedido em edição em pedidos_dia.py |
| `config` | dict | Configurações locais (preço base) |

---

## Branch de desenvolvimento ativo

`claude/debug-streamlit-telegram-bPuJb` → merge em `main` via PR #116.
