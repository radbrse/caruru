"""
Cantinho do Caruru — Versão 10.1 (com Backup na aba 'Gerenciar Tudo' e st.rerun)
- Refatorado e consolidado
- Inclui: clientes, pedidos, backups (CSV/ZIP), restauração, PDFs e UI completa Streamlit
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime, time
import os
import io
import zipfile
import logging
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

# ---------------------------- CONFIG ----------------------------
ARQUIVO_LOG = "system_errors.log"
ARQUIVO_PEDIDOS = "banco_de_dados_caruru.csv"
ARQUIVO_CLIENTES = "banco_de_dados_clientes.csv"
CHAVE_PIX = "79999296722"
OPCOES_STATUS = ["🔴 Pendente", "🟡 Em Produção", "✅ Entregue", "🚫 Cancelado"]
OPCOES_PAGAMENTO = ["PAGO", "NÃO PAGO", "METADE"]
PRECO_BASE = 70.0
VERSAO = "10.1"

# ---------------------------- LOGGING ----------------------------
logging.basicConfig(
    filename=ARQUIVO_LOG,
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    force=True,
)
logger = logging.getLogger("cantinho")

# ---------------------------- HELPERS ----------------------------
def limpar_hora_rigoroso(h):
    """Normaliza diversos formatos de hora para datetime.time ou None."""
    try:
        if h is None or (isinstance(h, float) and pd.isna(h)):
            return None
        if isinstance(h, time):
            return h
        hs = str(h).strip()
        if hs == "" or hs.lower() in {"nan", "nat", "none"}:
            return None
        # Tenta parses comuns
        for fmt in ("%H:%M", "%H:%M:%S"):
            try:
                return datetime.strptime(hs, fmt).time()
            except Exception:
                pass
        # Tenta pandas (mais tolerante)
        try:
            t = pd.to_datetime(hs, errors="coerce")
            if pd.isna(t):
                logger.warning(f"Hora inválida: {h}")
                return None
            return t.time()
        except Exception as e:
            logger.exception("Erro parse hora com pandas")
            return None
    except Exception as e:
        logger.exception(f"limpar_hora_rigoroso falhou para {h}: {e}")
        return None


def gerar_id_sequencial(df, coluna='ID_Pedido'):
    """Gera próximo ID com base no DataFrame, evitando duplicatas."""
    try:
        if df is None or df.empty:
            return 1
        df = df.copy()
        df[coluna] = pd.to_numeric(df[coluna], errors='coerce').fillna(0).astype(int)
        max_id = int(df[coluna].max())
        if df[coluna].duplicated().any() or max_id <= 0:
            df = df.reset_index(drop=True)
            df[coluna] = range(1, len(df) + 1)
            return int(df[coluna].max()) + 1
        return max_id + 1
    except Exception as e:
        logger.exception(f"Erro gerar_id_sequencial: {e}")
        return 1


def calcular_total(caruru, bobo, desconto, preco_base=PRECO_BASE):
    try:
        caruru = float(caruru or 0)
        bobo = float(bobo or 0)
        desconto = float(desconto or 0)
        total = (caruru * preco_base) + (bobo * preco_base)
        if desconto and desconto > 0:
            total = total * (1 - desconto / 100.0)
        return round(total, 2)
    except Exception as e:
        logger.exception(f"Erro calcular_total: {e}")
        return 0.0

# ---------------------------- DB UTILS ----------------------------
def carregar_clientes():
    colunas = ["Nome", "Contato", "Observacoes"]
    if not os.path.exists(ARQUIVO_CLIENTES):
        return pd.DataFrame(columns=colunas)
    try:
        df = pd.read_csv(ARQUIVO_CLIENTES, dtype=str).fillna("")
        for c in colunas:
            if c not in df.columns:
                df[c] = ""
        df = df[colunas]
        return df
    except Exception as e:
        logger.exception(f"Erro carregar_clientes: {e}")
        return pd.DataFrame(columns=colunas)


def carregar_pedidos():
    colunas_padrao = ["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]
    if not os.path.exists(ARQUIVO_PEDIDOS):
        return pd.DataFrame(columns=colunas_padrao)

    try:
        df = pd.read_csv(ARQUIVO_PEDIDOS)
        for c in colunas_padrao:
            if c not in df.columns:
                df[c] = None

        df['Caruru'] = pd.to_numeric(df['Caruru'], errors='coerce').fillna(0).astype(float)
        df['Bobo'] = pd.to_numeric(df['Bobo'], errors='coerce').fillna(0).astype(float)
        df['Desconto'] = pd.to_numeric(df['Desconto'], errors='coerce').fillna(0).astype(float)
        df['Valor'] = pd.to_numeric(df['Valor'], errors='coerce').fillna(0).astype(float)

        df['ID_Pedido'] = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
        if df['ID_Pedido'].duplicated().any() or df['ID_Pedido'].min() <= 0:
            df = df.reset_index(drop=True)
            df['ID_Pedido'] = range(1, len(df) + 1)

        mapa_status = {"Pendente": "🔴 Pendente", "Em Produção": "🟡 Em Produção", "Entregue": "✅ Entregue", "Cancelado": "🚫 Cancelado"}
        df['Status'] = df['Status'].fillna("").astype(str).replace(mapa_status)

        df['Data'] = pd.to_datetime(df['Data'], errors='coerce').dt.date
        df['Hora'] = df['Hora'].apply(limpar_hora_rigoroso)

        for c in ['Cliente', 'Status', 'Pagamento', 'Contato', 'Observacoes']:
            if c in df.columns:
                df[c] = df[c].fillna("").astype(str)

        return df[colunas_padrao]
    except Exception as e:
        logger.exception(f"Erro carregar_pedidos: {e}")
        return pd.DataFrame(columns=colunas_padrao)


def salvar_pedidos(df):
    try:
        df_to_save = df.copy()
        if 'Data' in df_to_save.columns:
            df_to_save['Data'] = df_to_save['Data'].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x)
        if 'Hora' in df_to_save.columns:
            df_to_save['Hora'] = df_to_save['Hora'].apply(lambda x: x.strftime('%H:%M') if isinstance(x, time) else str(x))
        df_to_save.to_csv(ARQUIVO_PEDIDOS, index=False)
    except Exception as e:
        logger.exception(f"Erro salvar_pedidos: {e}")


def salvar_clientes(df):
    try:
        df.to_csv(ARQUIVO_CLIENTES, index=False)
    except Exception as e:
        logger.exception(f"Erro salvar_clientes: {e}")

# ---------------------------- PDF UTILS ----------------------------
def desenhar_cabecalho(p, titulo):
    try:
        if os.path.exists("logo.png"):
            try:
                p.drawImage("logo.png", 30, 750, width=100, height=50, mask='auto', preserveAspectRatio=True)
            except Exception:
                logger.warning("logo.png existe mas não foi possível inserir")
        p.setFont("Helvetica-Bold", 16)
        p.drawString(150, 775, "Cantinho do Caruru")
        p.setFont("Helvetica", 10)
        p.drawString(150, 760, "Comprovante / Relatório")
        p.setFont("Helvetica-Bold", 14)
        p.drawRightString(565, 765, titulo)
        p.setLineWidth(1)
        p.line(30, 740, 565, 740)
    except Exception as e:
        logger.exception(f"Erro desenhar_cabecalho: {e}")


def gerar_recibo_pdf(dados: dict):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)

        id_pedido = dados.get('ID_Pedido', 'NOVO')
        desenhar_cabecalho(p, f"Pedido #{id_pedido}")

        y = 700
        p.setFont("Helvetica-Bold", 12)
        p.drawString(30, y, "DADOS DO CLIENTE")
        y -= 20
        p.setFont("Helvetica", 12)
        p.drawString(30, y, f"Nome: {dados.get('Cliente', '')}")
        p.drawString(300, y, f"WhatsApp: {dados.get('Contato', '')}")
        y -= 20

        data_val = dados.get('Data')
        data_str = data_val.strftime('%d/%m/%Y') if hasattr(data_val, 'strftime') else str(data_val or "")
        hora_val = dados.get('Hora')
        hora_str = hora_val.strftime('%H:%M') if isinstance(hora_val, time) else (str(hora_val)[:5] if hora_val else "--:--")
        p.drawString(30, y, f"Data de Entrega: {data_str}")
        p.drawString(300, y, f"Horário: {hora_str}")

        y -= 40
        p.setFillColor(colors.lightgrey)
        p.rect(30, y - 5, 535, 20, fill=1, stroke=0)
        p.setFillColor(colors.black)
        p.setFont("Helvetica-Bold", 10)
        p.drawString(40, y, "ITEM")
        p.drawString(400, y, "QUANTIDADE")
        y -= 25
        p.setFont("Helvetica", 10)

        caruru = float(dados.get('Caruru') or 0)
        bobo = float(dados.get('Bobo') or 0)
        if caruru > 0:
            p.drawString(40, y, "Caruru Tradicional (Kg/Unid)")
            p.drawString(400, y, f"{int(caruru)}")
            y -= 15
        if bobo > 0:
            p.drawString(40, y, "Bobó de Camarão (Kg/Unid)")
            p.drawString(400, y, f"{int(bobo)}")
            y -= 15

        p.line(30, y - 5, 565, y - 5)

        y -= 40
        p.setFont("Helvetica-Bold", 14)
        rotulo = "TOTAL PAGO" if dados.get('Pagamento') == "PAGO" else "VALOR A PAGAR"
        p.drawString(350, y, f"{rotulo}: R$ {float(dados.get('Valor') or 0):.2f}")

        y -= 25
        p.setFont("Helvetica-Bold", 12)
        sit = dados.get('Pagamento')
        if sit == "PAGO":
            p.setFillColor(colors.green)
            p.drawString(30, y + 25, "SITUAÇÃO: PAGO ✅")
        elif sit == "METADE":
            p.setFillColor(colors.orange)
            p.drawString(30, y + 25, "SITUAÇÃO: PARCIAL (50%) ⚠️")
            p.setFillColor(colors.black)
            p.setFont("Helvetica", 10)
            p.drawString(30, y, f"Chave PIX: {CHAVE_PIX}")
        else:
            p.setFillColor(colors.red)
            p.drawString(30, y + 25, "SITUAÇÃO: NÃO PAGO ❌")
            p.setFillColor(colors.black)
            p.setFont("Helvetica", 10)
            p.drawString(30, y, f"Chave PIX: {CHAVE_PIX}")

        p.setFillColor(colors.black)
        obs = dados.get('Observacoes')
        if obs and str(obs).strip().lower() not in {"", "nan"}:
            y -= 30
            p.setFont("Helvetica-Oblique", 10)
            p.drawString(30, y, f"Obs: {obs}")

        # Assinatura
        y_ass = 150
        p.setLineWidth(1)
        p.line(150, y_ass, 450, y_ass)
        p.setFont("Helvetica", 10)
        p.drawCentredString(300, y_ass - 15, "Cantinho do Caruru")
        data_hoje = datetime.now().strftime('%d/%m/%Y')
        p.setFont("Helvetica-Oblique", 8)
        p.drawCentredString(300, y_ass - 30, f"Emitido em: {data_hoje}")

        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.exception(f"Erro gerar_recibo_pdf: {e}")
        return None


def gerar_relatorio_pdf(df_filtrado, titulo_relatorio):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        y = 700
        desenhar_cabecalho(p, titulo_relatorio)
        p.setFont("Helvetica-Bold", 9)
        header_x = [30, 60, 110, 230, 280, 330, 400, 480]
        headers = ["ID", "Data", "Cliente", "Caruru", "Bobó", "Valor", "Status", "Pagto"]
        for x, h in zip(header_x, headers):
            p.drawString(x, y, h)
        y -= 20
        p.setFont("Helvetica", 9)
        total_valor = 0
        for index, row in df_filtrado.iterrows():
            if y < 60:
                p.showPage()
                desenhar_cabecalho(p, titulo_relatorio)
                y = 700
            id_ped = str(int(row.get('ID_Pedido') or 0))
            data_str = row.get('Data').strftime('%d/%m') if hasattr(row.get('Data'), 'strftime') else str(row.get('Data') or "")
            cliente = str(row.get('Cliente') or "")[:18]
            caruru = int(row.get('Caruru') or 0)
            bobo = int(row.get('Bobo') or 0)
            valor = float(row.get('Valor') or 0)
            status_clean = (row.get('Status') or "")
            if isinstance(status_clean, str):
                for prefix in ["✅ ", "🔴 ", "🟡 ", "🚫 "]:
                    status_clean = status_clean.replace(prefix, "")
            p.drawString(30, y, id_ped)
            p.drawString(60, y, data_str)
            p.drawString(110, y, cliente)
            p.drawString(230, y, str(caruru))
            p.drawString(280, y, str(bobo))
            p.drawString(330, y, f"R$ {valor:.2f}")
            p.drawString(400, y, str(status_clean)[:12])
            p.drawString(480, y, str(row.get('Pagamento') or ""))
            total_valor += valor
            y -= 15
        p.line(30, y, 565, y)
        y -= 20
        p.setFont("Helvetica-Bold", 11)
        p.drawString(30, y, f"TOTAL GERAL: R$ {total_valor:,.2f}")
        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.exception(f"Erro gerar_relatorio_pdf: {e}")
        return None


def gerar_lista_clientes_pdf(df_clientes):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        y = 700
        desenhar_cabecalho(p, "Lista de Clientes Cadastrados")
        p.setFont("Helvetica-Bold", 10)
        p.drawString(30, y, "Nome do Cliente")
        p.drawString(250, y, "WhatsApp")
        p.drawString(380, y, "Observações Fixas")
        y -= 20
        p.setFont("Helvetica", 10)

        df_clientes = df_clientes.sort_values(by="Nome") if not df_clientes.empty else df_clientes

        for index, row in df_clientes.iterrows():
            if y < 60:
                p.showPage()
                desenhar_cabecalho(p, "Lista de Clientes Cadastrados")
                y = 700
            p.drawString(30, y, str(row.get('Nome') or "")[:35])
            p.drawString(250, y, str(row.get('Contato') or ""))
            p.drawString(380, y, str(row.get('Observacoes') or "")[:30])
            y -= 20
            p.setLineWidth(0.5)
            p.setStrokeColor(colors.lightgrey)
            p.line(30, y + 15, 565, y + 15)

        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.exception(f"Erro gerar_lista_clientes_pdf: {e}")
        return None

# ---------------------------- APP START ----------------------------
st.set_page_config(page_title="Cantinho do Caruru", page_icon="🦐", layout="wide")

# Inicializa sessao (garante chaves antes da criação de widgets)
if 'pedidos' not in st.session_state:
    st.session_state.pedidos = carregar_pedidos()
if 'clientes' not in st.session_state:
    st.session_state.clientes = carregar_clientes()
if 'chave_contato_automatico' not in st.session_state:
    st.session_state['chave_contato_automatico'] = ""

# CSS simples
st.markdown("""
<style>
    .metric-card {background-color: #f9f9f9; border-left: 5px solid #ff4b4b; padding: 10px; border-radius: 5px;}
    .stButton>button {width: 100%; border-radius: 12px; font-weight: bold; height: 50px;}
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=250)
    else:
        st.title("🦐 Cantinho do Caruru")
    st.divider()
    menu = st.radio("Ir para:", ["Dashboard do Dia", "Novo Pedido", "Gerenciar Tudo", "🖨️ Relatórios & Recibos", "👥 Cadastrar Clientes", "🛠️ Manutenção"])
    st.divider()
    st.caption(f"Sistema Online (v{VERSAO})")

# ---------------------------- DASHBOARD ----------------------------
if menu == "Dashboard do Dia":
    st.title("🦐🏍️💨 Expedição do Dia")
    df = st.session_state.pedidos
    if df.empty:
        st.info("Sem dados.")
    else:
        data_analise = st.date_input("📅 Data:", date.today(), format="DD/MM/YYYY")
        df_dia = df[df['Data'] == data_analise].copy()
        try:
            df_dia['Hora_Temp'] = df_dia['Hora'].apply(lambda x: x if x is not None else time(23, 59))
            df_dia = df_dia.sort_values(by="Hora_Temp").drop(columns=['Hora_Temp'])
        except Exception:
            df_dia = df_dia.sort_values(by="Data")

        col1, col2, col3, col4 = st.columns(4)
        pendentes = df_dia[df_dia['Status'] != '✅ Entregue']
        col1.metric("Caruru (Pend)", f"{int(pendentes['Caruru'].sum())}")
        col2.metric("Bobó (Pend)", f"{int(pendentes['Bobo'].sum())}")
        col3.metric("Faturamento", f"R$ {df_dia['Valor'].sum():,.2f}")
        col4.metric("A Receber", f"R$ {df_dia[df_dia['Pagamento'] != 'PAGO']['Valor'].sum():,.2f}", delta_color="inverse")
        st.divider()
        st.subheader(f"📋 Entregas")

        if not df_dia.empty:
            try:
                df_baixa = st.data_editor(
                    df_dia,
                    column_order=["ID_Pedido", "Hora", "Status", "Cliente", "Caruru", "Bobo", "Valor", "Pagamento", "Observacoes"],
                    disabled=["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Hora"],
                    hide_index=True, use_container_width=True, key="dash_edit",
                    column_config={
                        "ID_Pedido": st.column_config.NumberColumn("#", width="small"),
                        "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                        "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                        "Hora": st.column_config.TimeColumn(format="HH:mm"),
                    }
                )
                if not df_baixa.equals(df_dia):
                    df_global = st.session_state.pedidos.copy()
                    for idx in df_baixa.index:
                        idp = int(df_baixa.at[idx, 'ID_Pedido'])
                        mask = df_global['ID_Pedido'] == idp
                        if mask.any():
                            df_global.loc[mask, df_baixa.columns] = df_baixa.loc[idx, :].values
                    st.session_state.pedidos = df_global
                    salvar_pedidos(df_global)
                    st.success("Atualizado!")
                    st.rerun()
            except Exception as e:
                st.error("Erro visual. Dados seguros.")
                logger.exception(f"Erro Dash: {e}")

# ---------------------------- NOVO PEDIDO ----------------------------
elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    try:
        lista_cli = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
    except Exception:
        lista_cli = []

    st.markdown("### 1. Identificação")
    c1, c2 = st.columns([3, 1])
    with c1:
        nome_sel = st.selectbox("Cliente", [""] + lista_cli, key="chave_cliente_selecionado")
    with c2:
        hora_ent = st.time_input("Hora", value=time(12, 0), key="hora_ent")

    st.markdown("### 2. Detalhes")
    with st.form("form_pedido", clear_on_submit=False):
        c1, c2 = st.columns(2)
        with c1:
            cont = st.text_input("WhatsApp", key="chave_contato_automatico")
        with c2:
            dt_ent = st.date_input("Data", min_value=date.today(), format="DD/MM/YYYY", key="dt_ent")
        c3, c4, c5 = st.columns(3)
        with c3:
            caruru = st.number_input("Caruru", 0.0, step=1.0, key="caruru")
        with c4:
            bobo = st.number_input("Bobó", 0.0, step=1.0, key="bobo")
        with c5:
            desc = st.number_input("Desc %", 0, 100, key="desc")
        obs = st.text_area("Obs", key="obs")
        c6, c7 = st.columns(2)
        with c6:
            pgto = st.selectbox("Pagto", OPCOES_PAGAMENTO, key="pgto")
        with c7:
            status = st.selectbox("Status", OPCOES_STATUS, key="status")

        def salvar_pedido_callback():
            try:
                cli_final = st.session_state.get('chave_cliente_selecionado', "")
                if not cli_final:
                    st.warning("Selecione um cliente.")
                    return
                car = st.session_state.get("caruru", 0)
                bob = st.session_state.get("bobo", 0)
                des = st.session_state.get("desc", 0)
                dt = st.session_state.get("dt_ent", date.today())
                hora_v = st.session_state.get("hora_ent", time(12, 0))
                cont_v = st.session_state.get("chave_contato_automatico", "")
                pg = st.session_state.get("pgto", "NÃO PAGO")
                st_status = st.session_state.get("status", "🔴 Pendente")
                obs_v = st.session_state.get("obs", "")
                val = calcular_total(car, bob, des)
                df_atual = st.session_state.pedidos
                novo_id = gerar_id_sequencial(df_atual)
                novo = {
                    "ID_Pedido": int(novo_id),
                    "Cliente": cli_final,
                    "Caruru": float(car),
                    "Bobo": float(bob),
                    "Valor": float(val),
                    "Data": dt,
                    "Hora": hora_v.strftime("%H:%M") if isinstance(hora_v, time) else str(hora_v)[:5],
                    "Status": st_status,
                    "Pagamento": pg,
                    "Contato": cont_v,
                    "Desconto": float(des),
                    "Observacoes": obs_v,
                }
                df_novo = pd.DataFrame([novo])
                df_novo['Data'] = pd.to_datetime(df_novo['Data']).dt.date
                st.session_state.pedidos = pd.concat([st.session_state.pedidos, df_novo], ignore_index=True)
                salvar_pedidos(st.session_state.pedidos)
                st.success(f"Pedido #{novo_id} Salvo!")
                # Reset seguro dentro do callback
                st.session_state['chave_contato_automatico'] = ""
                st.session_state['caruru'] = 0.0
                st.session_state['bobo'] = 0.0
                st.session_state['desc'] = 0
                st.session_state['obs'] = ""
                st.session_state['chave_cliente_selecionado'] = ""
                st.rerun()
            except Exception as e:
                logger.exception(f"Erro Novo Pedido (callback): {e}")
                st.error("Erro ao salvar. Veja logs.")

        st.form_submit_button("💾 SALVAR", on_click=salvar_pedido_callback)

# ---------------------------- GERENCIAR TUDO ----------------------------
elif menu == "Gerenciar Tudo":
    st.title("📦 Todos os Pedidos")
    df = st.session_state.pedidos
    if df.empty:
        st.info("Sem pedidos cadastrados.")
    else:
        try:
            df = df.copy()
            df['Hora_Temp'] = df['Hora'].apply(lambda x: x if x is not None else time(0, 0))
            df = df.sort_values(by=["Data", "Hora_Temp"], ascending=[True, True]).drop(columns=['Hora_Temp'])
        except Exception:
            df = df.sort_values(by="Data")

        try:
            df['Hora'] = df['Hora'].apply(limpar_hora_rigoroso)
            df_editado = st.data_editor(
                df,
                num_rows="dynamic", use_container_width=True, hide_index=True,
                column_config={
                    "ID_Pedido": st.column_config.NumberColumn("#", width="small", disabled=True),
                    "Valor": st.column_config.NumberColumn("Total", format="R$ %.2f", disabled=True),
                    "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                    "Hora": st.column_config.TimeColumn("Hora", format="HH:mm"),
                    "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                    "Pagamento": st.column_config.SelectboxColumn(options=OPCOES_PAGAMENTO, required=True),
                    "Caruru": st.column_config.NumberColumn(format="%d"),
                    "Bobo": st.column_config.NumberColumn(format="%d"),
                }
            )
            if not df_editado.equals(df):
                df_editado = df_editado.copy()
                df_editado['Valor'] = ((df_editado['Caruru'] * PRECO_BASE) + (df_editado['Bobo'] * PRECO_BASE)) * (1 - (df_editado['Desconto'] / 100))
                st.session_state.pedidos = df_editado
                salvar_pedidos(df_editado)
                st.success("Salvo!")
                st.rerun()
        except Exception as e:
            st.error(f"Erro na tabela. Veja logs.")
            logger.exception(f"Erro Table Editor: {e}")

        st.divider()
        try:
            cli_unicos = sorted(df['Cliente'].unique())
            sel = st.selectbox("Cliente:", cli_unicos)
            if sel:
                d = df[df['Cliente'] == sel].iloc[-1]
                t = str(d.get('Contato') or "").replace(".0", "").replace(" ", "").replace("-", "")
                dt = d['Data'].strftime('%d/%m') if hasattr(d['Data'], 'strftime') else str(d['Data'])
                try:
                    hr = d['Hora'].strftime('%H:%M') if isinstance(d['Hora'], time) else str(d['Hora'])
                except Exception:
                    hr = str(d['Hora'])
                msg = f"Olá {sel}, pedido #{int(d['ID_Pedido'])} confirmado!\n🗓 {dt} às {hr}\n📦 {int(d['Caruru'])} Caruru, {int(d['Bobo'])} Bobó\n💰 R$ {d['Valor']:.2f}"
                if d['Pagamento'] in ["NÃO PAGO", "METADE"]:
                    msg += f"\n🔑 Pix: {CHAVE_PIX}"
                lnk = f"https://wa.me/55{t}?text={msg.replace(' ', '%20').replace(chr(10), '%0A')}"
                st.markdown(f"[Enviar Zap]({lnk})")
        except Exception:
            logger.exception("Erro gerando link zap")

        # ----------------- BACKUP & RESTAURAR (MOVED HERE) -----------------
        st.divider()
        with st.expander("💾 Segurança (Backup & Restaurar)"):
            st.write("### 1. Fazer Backup")
            try:
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                    zip_file.writestr("pedidos.csv", st.session_state.pedidos.to_csv(index=False))
                    zip_file.writestr("clientes.csv", st.session_state.clientes.to_csv(index=False))
                st.download_button("📥 Baixar Tudo (ZIP)", zip_buffer.getvalue(), f"backup_{date.today()}.zip", "application/zip")
            except Exception:
                st.error("Erro ao preparar backup")
                logger.exception("Erro backup")

            st.write("### 2. Restaurar")
            st.markdown("**Aceita:** CSV de `pedidos` (colunas padrão), CSV de `clientes`, ou ZIP com `pedidos.csv` e/ou `clientes.csv`.")

            col_r1, col_r2 = st.columns(2)

            with col_r1:
                st.write("⚠️ **Restaurar Pedidos (CSV / ZIP)**")
                up = st.file_uploader("Arquivo Pedidos (CSV ou ZIP):", type=["csv", "zip"], key="res_ped_man")
                if up:
                    try:
                        # Se for ZIP, tenta extrair pedidos.csv
                        if (hasattr(up, "type") and up.type == "application/zip") or (hasattr(up, "name") and up.name.lower().endswith(".zip")):
                            zbuf = io.BytesIO(up.read())
                            with zipfile.ZipFile(zbuf, "r") as zf:
                                if "pedidos.csv" in zf.namelist():
                                    df_new = pd.read_csv(io.BytesIO(zf.read("pedidos.csv")))
                                else:
                                    st.error("ZIP não contém 'pedidos.csv'.")
                                    df_new = None
                        else:
                            up.seek(0)
                            df_new = pd.read_csv(up)

                        if df_new is not None:
                            # valida cols mínimas (alerta se faltando)
                            req_cols = {"ID_Pedido","Cliente","Caruru","Bobo","Valor","Data","Hora","Status","Pagamento","Contato","Desconto","Observacoes"}
                            if not req_cols.issubset(set(df_new.columns)):
                                st.warning("CSV carregado não tem todas as colunas esperadas. A restauração tentará normalizar o mínimo possível.")
                            salvar_pedidos(df_new)
                            st.session_state.pedidos = carregar_pedidos()
                            st.success("Pedidos restaurados com sucesso!")
                            st.rerun()
                    except Exception as e:
                        st.error("Erro ao restaurar pedidos. Veja logs.")
                        logger.exception(f"Erro restaurar pedidos: {e}")

            with col_r2:
                st.write("👥 **Restaurar Clientes (CSV / ZIP)**")
                upc = st.file_uploader("Arquivo Clientes (CSV ou ZIP):", type=["csv", "zip"], key="res_cli_man")
                if upc:
                    try:
                        if (hasattr(upc, "type") and upc.type == "application/zip") or (hasattr(upc, "name") and upc.name.lower().endswith(".zip")):
                            zbuf = io.BytesIO(upc.read())
                            with zipfile.ZipFile(zbuf, "r") as zf:
                                if "clientes.csv" in zf.namelist():
                                    df_new = pd.read_csv(io.BytesIO(zf.read("clientes.csv")))
                                else:
                                    st.error("ZIP não contém 'clientes.csv'.")
                                    df_new = None
                        else:
                            upc.seek(0)
                            df_new = pd.read_csv(upc)

                        if df_new is not None:
                            req_cols = {"Nome","Contato","Observacoes"}
                            if not req_cols.issubset(set(df_new.columns)):
                                st.warning("CSV de clientes não tem todas as colunas esperadas. A restauração tentará ajustar.")
                            salvar_clientes(df_new)
                            st.session_state.clientes = carregar_clientes()
                            st.success("Clientes restaurados com sucesso!")
                            st.rerun()
                    except Exception as e:
                        st.error("Erro ao restaurar clientes. Veja logs.")
                        logger.exception(f"Erro restaurar clientes: {e}")

# ---------------------------- RECIBOS ----------------------------
elif menu == "🖨️ Relatórios & Recibos":
    st.title("🖨️ Impressão")
    t1, t2 = st.tabs(["Recibo", "Relatório"])
    df = st.session_state.pedidos
    with t1:
        if df.empty:
            st.info("Sem dados.")
        else:
            cli = st.selectbox("Cliente:", sorted(df['Cliente'].unique()))
            ped_cli = df[df['Cliente'] == cli].sort_values(by="Data", ascending=False)
            if not ped_cli.empty:
                opc = {i: f"#{int(p['ID_Pedido'])} | {p['Data']} - R$ {p['Valor']}" for i, p in ped_cli.iterrows()}
                id_p = st.selectbox("Pedido:", options=opc.keys(), format_func=lambda x: opc[x])
                if st.button("Gerar Recibo"):
                    row = ped_cli.loc[id_p]
                    pdf = gerar_recibo_pdf(row.to_dict())
                    if pdf:
                        st.download_button("Baixar PDF", pdf, f"Recibo_{cli}.pdf", "application/pdf")
                    else:
                        st.error("Falha ao gerar PDF")
    with t2:
        tipo = st.radio("Tipo:", ["Dia", "Geral"])
        if tipo == "Dia":
            dt = st.date_input("Dia:", date.today(), format="DD/MM/YYYY")
            df_rel = df[df['Data'] == dt]
            tit = f"Relatório - {dt.strftime('%d/%m')}"
        else:
            df_rel = df
            tit = "Geral"
        if not df_rel.empty:
            if st.button("Gerar Relatório"):
                pdf = gerar_relatorio_pdf(df_rel, tit)
                if pdf:
                    st.download_button("Baixar Relatório", pdf, "relatorio.pdf", "application/pdf")
                else:
                    st.error("Erro ao gerar relatório")

# ---------------------------- CLIENTES ----------------------------
elif menu == "👥 Cadastrar Clientes":
    st.title("👥 Clientes")
    tab1, tab2 = st.tabs(["Novo", "Excluir"])
    with tab1:
        with st.form("f_cli", clear_on_submit=True):
            n = st.text_input("Nome", key="cli_n")
            z = st.text_input("Zap", key="cli_z")
            o = st.text_area("Obs", key="cli_o")
            if st.form_submit_button("Cadastrar") and n:
                novo = pd.DataFrame([{"Nome": n, "Contato": z, "Observacoes": o}])
                st.session_state.clientes = pd.concat([st.session_state.clientes, novo], ignore_index=True)
                salvar_clientes(st.session_state.clientes)
                st.success("Ok!")
                st.rerun()
        if not st.session_state.clientes.empty:
            df_c = st.data_editor(st.session_state.clientes, num_rows="dynamic", use_container_width=True, hide_index=True)
            if not df_c.equals(st.session_state.clientes):
                st.session_state.clientes = df_c
                salvar_clientes(df_c)
        st.divider()

        if not st.session_state.clientes.empty:
            st.write("📄 **Exportar Lista**")
            if st.button("Gerar PDF de Clientes"):
                pdf_cli = gerar_lista_clientes_pdf(st.session_state.clientes)
                if pdf_cli:
                    st.download_button("📥 Baixar PDF Clientes", pdf_cli, "lista_clientes.pdf", "application/pdf")
                else:
                    st.error("Erro ao gerar PDF")

        st.divider()
        with st.expander("💾 Backup Clientes"):
            try:
                csv_cli = st.session_state.clientes.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Baixar CSV Clientes", data=csv_cli, file_name=f"clientes_{date.today()}.csv", mime="text/csv")
            except Exception:
                logger.exception("Erro backup clientes")
    with tab2:
        if not st.session_state.clientes.empty:
            l_exc = st.session_state.clientes['Nome'].unique()
            exc = st.selectbox("Excluir:", l_exc)
            if st.button("Confirmar"):
                st.session_state.clientes = st.session_state.clientes[st.session_state.clientes['Nome'] != exc]
                salvar_clientes(st.session_state.clientes)
                st.rerun()

# ---------------------------- MANUTENÇÃO ----------------------------
elif menu == "🛠️ Manutenção":
    st.title("🛠️ Admin")
    st.write("Logs de Erro:")
    if os.path.exists(ARQUIVO_LOG):
        with open(ARQUIVO_LOG, "r") as f:
            log = f.read()
        st.text_area("Log", log, height=200)
        st.download_button("Baixar Log", log, "log.txt")
        if st.button("Limpar Log"):
            open(ARQUIVO_LOG, 'w').close()
            st.rerun()
    else:
        st.success("Sistema saudável.")

# ---------------------------- FIM ----------------------------
st.caption(f"Versão {VERSAO} — Cantinho do Caruru")
