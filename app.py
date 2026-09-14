"""
Sistema de Gestão de Pedidos - Cantinho do Caruru
Versão 21.1 - Persistência e regras financeiras revisadas

Módulos:
  config.py    - Constantes, logger, configurações
  auth.py      - Sistema de login
  utils.py     - Validações, formatação, badges
  database.py  - File locking, CSV, backups, histórico
  sheets.py    - Google Sheets sync
  pedidos.py   - CRUD de pedidos
  pdf.py       - Geração de PDFs
  views/       - Páginas da interface
"""

import os
import streamlit as st

# --- CONFIGURAÇÃO DA PÁGINA (deve ser primeiro comando Streamlit) ---
st.set_page_config(page_title="Cantinho do Caruru", page_icon="🦐", layout="wide")

# --- LOGIN ---
from auth import check_password
if not check_password():
    st.stop()

# --- IMPORTS DOS MÓDULOS ---
from config import (
    logger, hoje_brasil, VERSAO
)
from database import carregar_pedidos, carregar_clientes
from sheets import (
    conectar_google_sheets, obter_ou_criar_planilha,
    verificar_status_sheets, sincronizar_automaticamente,
    sincronizar_com_sheets
)

# Recupera configuração permanente antes de permitir novos pedidos.
from config import carregar_config, PrecoNaoConfigurado, atualizar_preco_base
try:
    st.session_state.config = carregar_config()
except PrecoNaoConfigurado as e:
    st.warning(str(e))
    st.caption('Informe o preço vigente. Ele será salvo na aba Config do Google Sheets.')
    preco_inicial = st.number_input('Preço vigente por kg (R$)', min_value=0.01, value=None, step=1.0)
    if st.button('Confirmar e salvar preço', disabled=preco_inicial is None):
        ok, mensagem = atualizar_preco_base(preco_inicial)
        if ok:
            st.rerun()
        st.error(mensagem)
    st.stop()
except Exception as e:
    st.error(f'Não foi possível recuperar o preço vigente: {e}')
    if st.button('Tentar recuperar novamente'):
        conectar_google_sheets.clear()
        obter_ou_criar_planilha.clear()
        st.rerun()
    st.stop()

# Verificar disponibilidade do gspread
try:
    import gspread
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

# ==============================================================================
# INICIALIZAÇÃO
# ==============================================================================
if 'pedidos' not in st.session_state:
    st.session_state.pedidos = carregar_pedidos()
if 'clientes' not in st.session_state:
    st.session_state.clientes = carregar_clientes()
if 'chave_contato_automatico' not in st.session_state:
    st.session_state['chave_contato_automatico'] = ""
if 'sync_automatico_habilitado' not in st.session_state:
    st.session_state['sync_automatico_habilitado'] = True

if 'sync_stats' not in st.session_state:
    st.session_state['sync_stats'] = {
        'total_tentativas': 0,
        'sucessos': 0,
        'falhas': 0,
        'ultima_sync': None,
        'ultimo_status': None,
        'ultimo_erro': None
    }

# 🔄 AUTO-RESTORE: Detecta CSV vazio e restaura do Google Sheets
if 'auto_restore_tentado' not in st.session_state:
    st.session_state['auto_restore_tentado'] = False

if not st.session_state['auto_restore_tentado']:
    from config import ARQUIVO_PEDIDOS, ARQUIVO_CLIENTES
    st.session_state['auto_restore_tentado'] = True
    if not os.path.exists(ARQUIVO_PEDIDOS) or not os.path.exists(ARQUIVO_CLIENTES):
        with st.spinner('Recuperando pedidos, clientes e preço do backup...'):
            sucesso, msg = sincronizar_com_sheets('receber')
        if not sucesso:
            st.session_state['auto_restore_tentado'] = False
            st.error(f'Recuperação não concluída. Nenhum novo pedido pode ser salvo: {msg}')
            if st.button('Tentar restaurar novamente'):
                st.rerun()
            st.stop()
        st.toast('Dados restaurados do backup em nuvem.', icon='✅')
        st.rerun()

# ==============================================================================
# SIDEBAR
# ==============================================================================
with st.sidebar:
    # Destaque visual do item de menu selecionado ("acende" em laranja).
    # Apenas CSS — não altera o roteamento. Degrada graciosamente em
    # navegadores sem suporte a :has() (o menu só não fica destacado).
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"] div[role="radiogroup"] { gap: 2px; }
        section[data-testid="stSidebar"] div[role="radiogroup"] > label {
            display: flex; align-items: center; width: 100%;
            padding: 9px 14px; margin: 1px 0; border-radius: 10px;
            cursor: pointer; transition: background .15s ease, box-shadow .15s ease;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
            background: #fff1e8;
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
            background: linear-gradient(135deg, #ff9a56 0%, #ff6b35 100%);
            box-shadow: 0 2px 10px rgba(255, 107, 53, 0.35);
        }
        section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p {
            color: #ffffff !important; font-weight: 700;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # Relógio em tempo real
    import streamlit.components.v1 as components
    components.html(
        """
        <div style="text-align: center; padding: 10px; background: linear-gradient(135deg, #ff9a56 0%, #ff6b35 100%); border-radius: 10px; margin-bottom: 15px;">
            <p id="clock" style="font-size: 24px; font-weight: bold; color: white; margin: 0; font-family: 'Courier New', monospace;"></p>
            <p id="date" style="font-size: 12px; color: #f0f0f0; margin: 5px 0 0 0;"></p>
        </div>
        <script>
            function updateClock() {
                const now = new Date();
                const hours = String(now.getHours()).padStart(2, '0');
                const minutes = String(now.getMinutes()).padStart(2, '0');
                const seconds = String(now.getSeconds()).padStart(2, '0');
                document.getElementById('clock').textContent = hours + ':' + minutes + ':' + seconds;

                const days = ['Dom', 'Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb'];
                const months = ['Jan', 'Fev', 'Mar', 'Abr', 'Mai', 'Jun', 'Jul', 'Ago', 'Set', 'Out', 'Nov', 'Dez'];
                const dayName = days[now.getDay()];
                const day = String(now.getDate()).padStart(2, '0');
                const month = months[now.getMonth()];
                const year = now.getFullYear();
                document.getElementById('date').textContent = dayName + ', ' + day + ' ' + month + ' ' + year;
            }
            updateClock();
            setInterval(updateClock, 1000);
        </script>
        """,
        height=90
    )

    if os.path.exists("logo.png"):
        st.image("logo.png", width=250)
    else:
        st.title("🦐 Cantinho do Caruru")

    # 🛡️ INDICADOR DE PROTEÇÃO (sempre visível)
    st.divider()
    from storage import estado_backup
    nivel_backup, mensagem_backup = estado_backup(st.session_state.get('sync_automatico_habilitado', True))
    getattr(st, nivel_backup)(mensagem_backup)

    st.divider()
    menu = st.radio(
        "Navegação",
        [
            "📅 Pedidos do Dia",
            "Novo Pedido",
            "Gerenciar Tudo",
            "📜 Histórico",
            "🖨️ Relatórios & Recibos",
            "📢 Promoções",
            "👥 Cadastrar Clientes",
            "🛠️ Manutenção"
        ],
        key="menu_navegacao_principal"
    )
    # Aviso persistente quando sync está desabilitado
    if not st.session_state.get('sync_automatico_habilitado', True):
        st.error("🔴 SEM BACKUP — dados em risco!")

    st.divider()

    # Mini resumo
    from utils import formatar_valor_br
    df_hoje = st.session_state.pedidos[st.session_state.pedidos['Data'] == hoje_brasil()]
    if not df_hoje.empty:
        pend = df_hoje[~df_hoje['Status'].str.contains("Entregue|Cancelado", na=False)]
        st.caption(f"📅 Hoje: {len(df_hoje)} pedidos")
        st.caption(f"⏳ Pendentes: {len(pend)}")

    st.divider()

    # Configuração de Sincronização Automática
    status_sheets, msg_sheets = verificar_status_sheets()

    with st.expander("☁️ Sync Google Sheets", expanded=True):
        if status_sheets:
            st.success("✅ Sheets conectado")

            sync_atual = st.session_state.get('sync_automatico_habilitado', True)

            sync_habilitado = st.toggle(
                "🔄 Sincronização Automática",
                value=sync_atual,
                help="Sincroniza automaticamente com Google Sheets após criar/editar/excluir pedidos"
            )

            # ⚠️ AVISO DE SEGURANÇA ao desligar
            if not sync_habilitado and sync_atual:
                st.error("⚠️ **ATENÇÃO: RISCO DE PERDA DE DADOS!**")
                st.warning("""
                Se você desabilitar o sync automático:
                - ❌ Pedidos ficam APENAS no servidor (efêmero)
                - ❌ Ao hibernar, o Streamlit **PERDE TODOS OS DADOS**
                - ⚠️ Você precisará fazer backup MANUAL na aba Manutenção
                """)

                confirmar_desligar = st.checkbox(
                    "✅ Entendo o risco e quero desabilitar o sync automático",
                    key="confirmar_desligar_sync"
                )

                if confirmar_desligar:
                    st.session_state['sync_automatico_habilitado'] = False
                    st.toast("⚠️ Sync automático DESABILITADO", icon="⚠️")
                else:
                    st.session_state['sync_automatico_habilitado'] = True
                    st.rerun()
            else:
                st.session_state['sync_automatico_habilitado'] = sync_habilitado

            nivel, mensagem = estado_backup(st.session_state.get('sync_automatico_habilitado', True))
            getattr(st, nivel)(mensagem)
            if st.button('Confirmar backup agora', key='backup_agora_sidebar'):
                ok, msg = sincronizar_com_sheets('enviar')
                if ok:
                    st.rerun()
                st.error(msg)

            st.divider()
            st.markdown("### 📊 Diagnóstico de Sincronização")

            stats = st.session_state.get('sync_stats', {})

            # Taxa de sucesso: usa apenas tentativas reais (não conta syncs desabilitados)
            sucessos = stats.get('sucessos', 0)
            falhas = stats.get('falhas', 0)
            efetivas = sucessos + falhas
            if efetivas > 0:
                taxa_sucesso = (sucessos / efetivas) * 100
                st.metric(
                    "Taxa de Sucesso",
                    f"{taxa_sucesso:.1f}%",
                    delta=f"{sucessos}/{efetivas}",
                    delta_color="normal"
                )

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Tentativas", stats.get('total_tentativas', 0))
            with col2:
                st.metric("✅ Sucessos", sucessos)
            with col3:
                st.metric("❌ Falhas", falhas)

            ultimo_status = stats.get('ultimo_status')
            if ultimo_status:
                if '✅' in ultimo_status:
                    st.success(f"**Último Status:** {ultimo_status}")
                elif '⚠️' in ultimo_status:
                    st.warning(f"**Último Status:** {ultimo_status}")
                elif '⚪' in ultimo_status:
                    st.info(f"**Último Status:** {ultimo_status}")
                else:
                    st.error(f"**Último Status:** {ultimo_status}")

                ultima_sync = stats.get('ultima_sync')
                if ultima_sync:
                    st.info(f"🕐 **Última sincronização:**\n{ultima_sync}")

                ultimo_erro = stats.get('ultimo_erro')
                if ultimo_erro:
                    with st.expander("🔍 Detalhes do Erro"):
                        st.code(ultimo_erro, language=None)
            else:
                st.info("**Status:** Nenhuma sincronização realizada ainda")
        else:
            st.warning("⚠️ Sheets não configurado")
            st.caption("Configure na aba 🛠️ Manutenção")

    st.divider()

    # Botão de acesso rápido ao Google Sheets
    if status_sheets:
        try:
            client = conectar_google_sheets()
            if client:
                spreadsheet = obter_ou_criar_planilha(client)
                if spreadsheet:
                    sheets_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet.id}"
                    st.link_button(
                        "📊 Abrir Google Sheets",
                        sheets_url,
                        use_container_width=True,
                        type="secondary"
                    )
        except Exception as e:
            logger.debug(f"Sidebar Sheets link indisponível: {e}")

    st.caption(f"Versão {VERSAO}")

# ==============================================================================
# ROTEAMENTO DE PÁGINAS
# ==============================================================================
if menu == "📅 Pedidos do Dia":
    from views.pedidos_dia import render
    render()

elif menu == "Novo Pedido":
    from views.novo_pedido import render
    render()

elif menu == "Gerenciar Tudo":
    from views.gerenciar import render
    render()

elif menu == "📜 Histórico":
    from views.historico import render
    render()

elif menu == "🖨️ Relatórios & Recibos":
    from views.relatorios import render
    render()

elif menu == "📢 Promoções":
    from views.promocoes import render
    render()

elif menu == "👥 Cadastrar Clientes":
    from views.clientes import render
    render()

elif menu == "🛠️ Manutenção":
    from views.manutencao import render
    render()
