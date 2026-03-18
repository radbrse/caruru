"""
Sistema de Gestão de Pedidos - Cantinho do Caruru
Versão 21.0 - Modularizado

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
    verificar_status_sheets, sincronizar_automaticamente
)

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

# ==============================================================================
# SIDEBAR
# ==============================================================================
with st.sidebar:
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
        ]
    )
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

    with st.expander("☁️ Sync Google Sheets"):
        if status_sheets:
            st.success("✅ Sheets conectado")

            sync_habilitado = st.toggle(
                "🔄 Sincronização Automática",
                value=st.session_state.get('sync_automatico_habilitado', False),
                help="Sincroniza automaticamente com Google Sheets após criar/editar/excluir pedidos"
            )

            st.session_state['sync_automatico_habilitado'] = sync_habilitado

            if sync_habilitado:
                st.info("🟢 Sync ativo - Dados são enviados automaticamente ao Sheets")
            else:
                st.caption("⚪ Sync desativado - Use os botões manuais na aba Manutenção")

            st.divider()
            st.caption("📊 **Diagnóstico de Sincronização**")

            stats = st.session_state.get('sync_stats', {})

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Tentativas", stats.get('total_tentativas', 0), delta=None)
            with col2:
                st.metric("✅ Sucessos", stats.get('sucessos', 0), delta=None)
            with col3:
                st.metric("❌ Falhas", stats.get('falhas', 0), delta=None)

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
                    st.caption(f"🕐 Última sync: {ultima_sync}")

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
        except:
            pass

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
