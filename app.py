import streamlit as st
import pandas as pd
from datetime import date, datetime, time, timedelta
import os
import io
import zipfile
import logging
import urllib.parse
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Cantinho do Caruru", page_icon="🦐", layout="wide")

# ==============================================================================
# 🔒 SISTEMA DE LOGIN
# ==============================================================================
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.title("🔒 Acesso Restrito")
    st.text_input("Digite a senha:", type="password", key="password", on_change=password_entered)
    if "password_correct" in st.session_state:
        st.error("Senha incorreta.")
    return False

# Comente a linha abaixo se for rodar localmente sem senha
if not check_password():
    st.stop()

# ==============================================================================
# CONFIGURAÇÕES
# ==============================================================================
ARQUIVO_LOG = "system_errors.log"
ARQUIVO_PEDIDOS = "banco_de_dados_caruru.csv"
ARQUIVO_CLIENTES = "banco_de_dados_clientes.csv"
ARQUIVO_HISTORICO = "historico_alteracoes.csv"
CHAVE_PIX = "79999296722"
OPCOES_STATUS = ["🔴 Pendente", "🟡 Em Produção", "✅ Entregue", "🚫 Cancelado"]
OPCOES_PAGAMENTO = ["PAGO", "NÃO PAGO", "METADE"]
PRECO_BASE = 70.0
VERSAO = "17.3 (Reset Manual)"

logging.basicConfig(filename=ARQUIVO_LOG, level=logging.ERROR, format='%(asctime)s | %(levelname)s | %(message)s', force=True)
logger = logging.getLogger("cantinho")

# ==============================================================================
# FUNÇÕES DE VALIDAÇÃO
# ==============================================================================
def limpar_telefone(telefone):
    if not telefone: return ""
    return re.sub(r'\D', '', str(telefone))

def validar_telefone(telefone):
    limpo = limpar_telefone(telefone)
    if not limpo: return "", None
    if limpo.startswith("55") and len(limpo) > 11: limpo = limpo[2:]
    if len(limpo) < 10 or len(limpo) > 11: return limpo, "⚠️ Telefone estranho."
    return limpo, None

def validar_quantidade(valor, nome_campo):
    try:
        v = float(str(valor).replace(",", "."))
        if v < 0: return 0.0, f"⚠️ {nome_campo} negativo."
        return round(v, 1), None
    except: return 0.0, None

def validar_desconto(valor):
    try:
        v = float(str(valor).replace(",", "."))
        if v < 0 or v > 100: return 0.0, "⚠️ Desconto inválido."
        return round(v, 2), None
    except: return 0.0, None

def validar_data_pedido(data, permitir_passado=False):
    if data is None: return date.today(), None
    return data, None

def validar_hora(hora):
    if hora is None: return time(12, 0), None
    return hora, None

def limpar_hora_rigoroso(h):
    try:
        if h in [None, "", "nan", "NaT"] or pd.isna(h): return None
        if isinstance(h, time): return h
        hs = str(h).strip()
        for fmt in ("%H:%M", "%H:%M:%S"):
            try: return datetime.strptime(hs, fmt).time()
            except: pass
        t = pd.to_datetime(hs, errors='coerce')
        if not pd.isna(t): return t.time()
        return None
    except: return None

# ==============================================================================
# FUNÇÕES DE CÁLCULO E DB
# ==============================================================================
def gerar_id_sequencial(df):
    try:
        if df.empty: return 1
        df = df.copy()
        df['ID_Pedido'] = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
        return int(df['ID_Pedido'].max()) + 1
    except: return 1

def calcular_total(caruru, bobo, desconto):
    try:
        c = max(0.0, float(caruru or 0))
        b = max(0.0, float(bobo or 0))
        d = max(0.0, min(100.0, float(desconto or 0)))
        total = (c * PRECO_BASE) + (b * PRECO_BASE)
        if d > 0: total = total * (1 - d / 100.0)
        return round(total, 2)
    except: return 0.0

def gerar_link_whatsapp(telefone, mensagem):
    tel_limpo = limpar_telefone(telefone)
    if len(tel_limpo) < 10: return None
    msg_encoded = urllib.parse.quote(mensagem)
    return f"https://wa.me/55{tel_limpo}?text={msg_encoded}"

def carregar_clientes():
    colunas = ["Nome", "Contato", "Observacoes"]
    if not os.path.exists(ARQUIVO_CLIENTES): return pd.DataFrame(columns=colunas)
    try:
        df = pd.read_csv(ARQUIVO_CLIENTES, dtype=str).fillna("")
        for c in colunas:
            if c not in df.columns: df[c] = ""
        return df[colunas]
    except: return pd.DataFrame(columns=colunas)

def carregar_pedidos():
    colunas_padrao = ["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]
    if not os.path.exists(ARQUIVO_PEDIDOS): return pd.DataFrame(columns=colunas_padrao)
    try:
        df = pd.read_csv(ARQUIVO_PEDIDOS)
        for c in colunas_padrao:
            if c not in df.columns: df[c] = None
        
        df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.date
        df["Hora"] = df["Hora"].apply(limpar_hora_rigoroso)
        for col in ["Caruru", "Bobo", "Desconto", "Valor"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        df['ID_Pedido'] = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
        
        if df['ID_Pedido'].duplicated().any() or (not df.empty and df['ID_Pedido'].max() == 0):
            df['ID_Pedido'] = range(1, len(df) + 1)
        
        mapa = {"Pendente": "🔴 Pendente", "Em Produção": "🟡 Em Produção", "Entregue": "✅ Entregue", "Cancelado": "🚫 Cancelado"}
        df['Status'] = df['Status'].replace(mapa)
        
        for c in ["Cliente", "Status", "Pagamento", "Contato", "Observacoes"]:
            df[c] = df[c].fillna("").astype(str)
            
        return df[colunas_padrao]
    except: return pd.DataFrame(columns=colunas_padrao)

def salvar_pedidos(df):
    try:
        salvar = df.copy()
        salvar['Data'] = salvar['Data'].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x)
        salvar['Hora'] = salvar['Hora'].apply(lambda x: x.strftime('%H:%M') if isinstance(x, time) else str(x))
        salvar.to_csv(ARQUIVO_PEDIDOS, index=False)
        return True
    except: return False

def salvar_clientes(df):
    try:
        df.to_csv(ARQUIVO_CLIENTES, index=False)
        return True
    except: return False

def registrar_alteracao(tipo, id_pedido, campo, valor_antigo, valor_novo):
    try:
        registro = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Tipo": tipo, "ID_Pedido": id_pedido, "Campo": campo,
            "Valor_Antigo": str(valor_antigo)[:50], "Valor_Novo": str(valor_novo)[:50]
        }
        if os.path.exists(ARQUIVO_HISTORICO): df = pd.read_csv(ARQUIVO_HISTORICO)
        else: df = pd.DataFrame()
        df = pd.concat([df, pd.DataFrame([registro])], ignore_index=True)
        if len(df) > 500: df = df.tail(500)
        df.to_csv(ARQUIVO_HISTORICO, index=False)
    except: pass

# ==============================================================================
# PDF
# ==============================================================================
def desenhar_cabecalho(p, titulo):
    if os.path.exists("logo.png"):
        try: p.drawImage("logo.png", 30, 750, width=100, height=50, mask='auto', preserveAspectRatio=True)
        except: pass
    p.setFont("Helvetica-Bold", 16); p.drawString(150, 775, "Cantinho do Caruru")
    p.setFont("Helvetica", 10); p.drawString(150, 760, "Comprovante / Relatório")
    p.setFont("Helvetica-Bold", 14); p.drawRightString(565, 765, titulo)
    p.setLineWidth(1); p.line(30, 740, 565, 740)

def gerar_recibo_pdf(dados):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        id_p = dados.get('ID_Pedido', 'NOVO')
        desenhar_cabecalho(p, f"Pedido #{id_p}")

        y = 700
        p.setFont("Helvetica-Bold", 12); p.drawString(30, y, "DADOS DO CLIENTE"); y-=20
        p.setFont("Helvetica", 12)
        p.drawString(30, y, f"Nome: {dados.get('Cliente', '')}")
        p.drawString(300, y, f"WhatsApp: {dados.get('Contato', '')}")
        y-=20
        
        dt = dados.get('Data'); dt_s = dt.strftime('%d/%m/%Y') if hasattr(dt, 'strftime') else str(dt)
        hr = dados.get('Hora'); hr_s = hr.strftime('%H:%M') if isinstance(hr, time) else str(hr)[:5]
        p.drawString(30, y, f"Data: {dt_s}"); p.drawString(300, y, f"Hora: {hr_s}")
        
        y-=40; p.setFillColor(colors.lightgrey); p.rect(30, y-5, 535, 20, fill=1, stroke=0)
        p.setFillColor(colors.black); p.setFont("Helvetica-Bold", 10)
        p.drawString(40, y, "ITEM"); p.drawString(400, y, "QUANTIDADE"); y-=25
        p.setFont("Helvetica", 10)
        
        if float(dados.get('Caruru', 0)) > 0:
            p.drawString(40, y, "Caruru Tradicional"); p.drawString(400, y, f"{int(float(dados.get('Caruru')))}"); y-=15
        if float(dados.get('Bobo', 0)) > 0:
            p.drawString(40, y, "Bobó de Camarão"); p.drawString(400, y, f"{int(float(dados.get('Bobo')))}"); y-=15
        
        p.line(30, y-5, 565, y-5)
        y-=40; p.setFont("Helvetica-Bold", 14)
        lbl = "TOTAL PAGO" if dados.get('Pagamento') == "PAGO" else "VALOR A PAGAR"
        p.drawString(350, y, f"{lbl}: R$ {float(dados.get('Valor', 0)):.2f}")
        
        y-=25; p.setFont("Helvetica-Bold", 12)
        sit = dados.get('Pagamento')
        if sit == "PAGO":
            p.setFillColor(colors.green); p.drawString(30, y+25, "SITUAÇÃO: PAGO ✅")
        else:
            p.setFillColor(colors.red); p.drawString(30, y+25, "SITUAÇÃO: PENDENTE ❌")
            p.setFillColor(colors.black); p.setFont("Helvetica", 10); p.drawString(30, y, f"Pix: {CHAVE_PIX}")
        
        p.setFillColor(colors.black)
        if dados.get('Observacoes'):
            y-=30; p.setFont("Helvetica-Oblique", 10); p.drawString(30, y, f"Obs: {dados.get('Observacoes')[:80]}")
            
        y_ass = 150; p.setLineWidth(1); p.line(150, y_ass, 450, y_ass)
        p.setFont("Helvetica", 10); p.drawCentredString(300, y_ass-15, "Cantinho do Caruru")
        p.setFont("Helvetica-Oblique", 8); p.drawCentredString(300, y_ass-30, f"Emitido em: {datetime.now().strftime('%d/%m/%Y')}")
        
        p.showPage(); p.save(); buffer.seek(0)
        return buffer
    except: return None

def gerar_relatorio_pdf(df_filtrado, titulo_relatorio):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        y = 700; desenhar_cabecalho(p, titulo_relatorio)
        p.setFont("Helvetica-Bold", 9)
        cols = [30, 60, 110, 230, 280, 330, 400, 480]
        hdrs = ["ID", "Data", "Cliente", "Car", "Bob", "Valor", "Status", "Pagto"]
        for x, h in zip(cols, hdrs): p.drawString(x, y, h)
        y-=20; p.setFont("Helvetica", 9); total=0
        
        for _, row in df_filtrado.iterrows():
            if y < 60: p.showPage(); desenhar_cabecalho(p, titulo_relatorio); y=700
            d_s = row['Data'].strftime('%d/%m') if hasattr(row['Data'], 'strftime') else ""
            st_cl = str(row['Status']).replace("🔴","").replace("✅","").replace("🟡","").replace("🚫","").strip()[:12]
            p.drawString(30, y, str(row.get('ID_Pedido', '')))
            p.drawString(60, y, d_s)
            p.drawString(110, y, str(row.get('Cliente', ''))[:15])
            p.drawString(230, y, str(int(row.get('Caruru', 0))))
            p.drawString(280, y, str(int(row.get('Bobo', 0))))
            p.drawString(330, y, f"{row.get('Valor', 0):.2f}")
            p.drawString(400, y, st_cl)
            p.drawString(480, y, str(row.get('Pagamento', ''))[:10])
            total += row.get('Valor', 0); y-=12
        p.line(30, y, 565, y); p.setFont("Helvetica-Bold", 11); p.drawString(280, y-20, f"TOTAL GERAL: R$ {total:,.2f}")
        p.showPage(); p.save(); buffer.seek(0)
        return buffer
    except: return None

def gerar_lista_clientes_pdf(df_clientes):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        y = 700; desenhar_cabecalho(p, "Lista de Clientes")
        p.setFont("Helvetica-Bold", 10)
        p.drawString(30, y, "Nome"); p.drawString(250, y, "WhatsApp"); p.drawString(380, y, "Obs")
        y-=20; p.setFont("Helvetica", 10)
        for _, row in df_clientes.sort_values('Nome').iterrows():
            if y < 60: p.showPage(); desenhar_cabecalho(p, "Lista de Clientes"); y=700
            p.drawString(30, y, str(row.get('Nome', ''))[:28])
            p.drawString(250, y, str(row.get('Contato', ''))[:18])
            p.drawString(380, y, str(row.get('Observacoes', ''))[:30])
            y-=12; p.setLineWidth(0.5); p.setStrokeColor(colors.lightgrey); p.line(30, y+5, 565, y+5)
        p.showPage(); p.save(); buffer.seek(0)
        return buffer
    except: return None

# ==============================================================================
# INICIALIZAÇÃO
# ==============================================================================
if 'pedidos' not in st.session_state:
    st.session_state.pedidos = carregar_pedidos()
if 'clientes' not in st.session_state:
    st.session_state.clientes = carregar_clientes()
if 'chave_contato_automatico' not in st.session_state:
    st.session_state['chave_contato_automatico'] = ""

# ==============================================================================
# SIDEBAR
# ==============================================================================
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=250)
    else:
        st.title("🦐 Cantinho do Caruru")
    st.divider()
    menu = st.radio(
        "Navegação",
        [
            "Dashboard do Dia",
            "Novo Pedido",
            "✏️ Editar Pedido",
            "🗑️ Excluir Pedido",
            "Gerenciar Tudo",
            "🖨️ Relatórios & Recibos",
            "📢 Promoções",
            "👥 Cadastrar Clientes",
            "🛠️ Manutenção"
        ]
    )
    st.divider()
    
    # Mini resumo
    df_hoje = st.session_state.pedidos[st.session_state.pedidos['Data'] == date.today()]
    if not df_hoje.empty:
        pend = df_hoje[~df_hoje['Status'].str.contains("Entregue|Cancelado", na=False)]
        st.caption(f"📅 Hoje: {len(df_hoje)} pedidos")
        st.caption(f"⏳ Pendentes: {len(pend)}")
    
    st.divider()
    st.caption(f"Versão {VERSAO}")

# ==============================================================================
# PÁGINAS
# ==============================================================================

# --- DASHBOARD ---
if menu == "Dashboard do Dia":
    st.title("🦐🏍️ Expedição do Dia")
    df = st.session_state.pedidos
    
    if df.empty:
        st.info("Sem dados cadastrados.")
    else:
        dt_filter = st.date_input("📅 Data:", date.today(), format="DD/MM/YYYY")
        df_dia = df[df['Data'] == dt_filter].copy()
        
        try:
            df_dia['h_sort'] = df_dia['Hora'].apply(lambda x: x if isinstance(x, time) else time(23, 59))
            df_dia = df_dia.sort_values('h_sort').drop(columns=['h_sort'])
        except: pass
        
        c1, c2, c3, c4 = st.columns(4)
        pend = df_dia[
            (~df_dia['Status'].str.contains("Entregue", na=False)) & 
            (~df_dia['Status'].str.contains("Cancelado", na=False))
        ]
        c1.metric("🥘 Caruru (Pend)", int(pend['Caruru'].sum()))
        c2.metric("🦐 Bobó (Pend)", int(pend['Bobo'].sum()))
        c3.metric("💰 Faturamento", f"R$ {df_dia['Valor'].sum():,.2f}")
        rec = df_dia[df_dia['Pagamento'] != 'PAGO']['Valor'].sum()
        c4.metric("📥 A Receber", f"R$ {rec:,.2f}", delta_color="inverse")
        
        st.divider()
        st.subheader("📋 Entregas do Dia")
        
        if not df_dia.empty:
            edited = st.data_editor(
                df_dia,
                column_order=["ID_Pedido", "Hora", "Status", "Cliente", "Caruru", "Bobo", "Valor", "Pagamento", "Observacoes"],
                disabled=["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Hora"],
                hide_index=True, use_container_width=True, key="dash_editor",
                column_config={
                    "ID_Pedido": st.column_config.NumberColumn("#", width="small"),
                    "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                    "Pagamento": st.column_config.SelectboxColumn(options=OPCOES_PAGAMENTO, required=True),
                    "Hora": st.column_config.TimeColumn(format="HH:mm"),
                    "Valor": st.column_config.NumberColumn(format="R$ %.2f")
                }
            )
            
            if not edited.equals(df_dia):
                df_glob = st.session_state.pedidos.copy()
                for i in edited.index:
                    idp = edited.at[i, 'ID_Pedido']
                    mask = df_glob['ID_Pedido'] == idp
                    if mask.any():
                        for col in ['Status', 'Pagamento', 'Observacoes']:
                            if col in edited.columns:
                                df_glob.loc[mask, col] = edited.at[i, col]
                
                st.session_state.pedidos = df_glob
                salvar_pedidos(df_glob)
                st.toast("✅ Atualizado!", icon="✅")
                st.rerun()
        else:
            st.info(f"Nenhum pedido para {dt_filter.strftime('%d/%m/%Y')}")

# --- NOVO PEDIDO ---
elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    
    # ------------------ LOGICA DE RESET (RESETAR CAMPOS) ------------------
    if st.session_state.get('resetar_cliente_novo', False):
        st.session_state.cliente_novo_index = 0
        st.session_state.resetar_cliente_novo = False
    
    if 'cliente_novo_index' not in st.session_state:
        st.session_state.cliente_novo_index = 0
    
    try:
        clis = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
    except:
        clis = []
    
    lista_clientes = ["-- Selecione --"] + clis

    st.markdown("### 1️⃣ Cliente")
    
    c_sel = st.selectbox(
        "👤 Nome do Cliente", 
        lista_clientes,
        index=st.session_state.cliente_novo_index,
        key="sel_cliente_novo"
    )
    
    if c_sel in lista_clientes:
        st.session_state.cliente_novo_index = lista_clientes.index(c_sel)
    
    contato_cliente = ""
    if c_sel and c_sel != "-- Selecione --":
        try:
            res = st.session_state.clientes[st.session_state.clientes['Nome'] == c_sel]
            if not res.empty:
                contato_cliente = str(res.iloc[0]['Contato']) if pd.notna(res.iloc[0]['Contato']) else ""
        except:
            contato_cliente = ""
    else:
        c_sel = ""
    
    if not c_sel:
        st.info("💡 Selecione um cliente cadastrado ou cadastre um novo em '👥 Cadastrar Clientes'")
    else:
        st.success(f"📱 Contato encontrado: **{contato_cliente}**" if contato_cliente else "⚠️ Cliente sem telefone cadastrado")
    
    st.markdown("### 2️⃣ Dados do Pedido")
    
    # clear_on_submit=False porque vamos limpar manualmente
    with st.form("form_novo_pedido", clear_on_submit=False):
        c1, c2, c3 = st.columns(3)
        with c1:
            cont = st.text_input("📱 WhatsApp", value=contato_cliente, placeholder="79999999999", key="np_contato")
        with c2:
            dt = st.date_input("📅 Data Entrega", min_value=date.today(), format="DD/MM/YYYY", key="np_data")
        with c3:
            h_ent = st.time_input("⏰ Hora Retirada", value=time(12, 0), key="np_hora")
        
        st.markdown("### 3️⃣ Itens do Pedido")
        c3, c4, c5 = st.columns(3)
        with c3:
            qc = st.number_input("🥘 Caruru (qtd)", min_value=0, max_value=999, step=1, value=0, key="np_caruru")
        with c4:
            qb = st.number_input("🦐 Bobó (qtd)", min_value=0, max_value=999, step=1, value=0, key="np_bobo")
        with c5:
            dc = st.number_input("💸 Desconto %", min_value=0, max_value=100, step=5, value=0, key="np_desc")
        
        obs = st.text_area("📝 Observações", placeholder="Ex: Sem pimenta...", key="np_obs")
        
        c6, c7 = st.columns(2)
        with c6:
            pg = st.selectbox("💳 Pagamento", OPCOES_PAGAMENTO, key="np_pgto")
        with c7:
            stt = st.selectbox("📊 Status", OPCOES_STATUS, key="np_status")
        
        submitted = st.form_submit_button("💾 SALVAR PEDIDO", use_container_width=True, type="primary")
        
        if submitted:
            cliente_final = c_sel if c_sel and c_sel != "-- Selecione --" else ""
            
            id_criado, erros, avisos = criar_pedido(
                cliente=cliente_final, caruru=qc, bobo=qb, data=dt, hora=h_ent,
                status=stt, pagamento=pg, contato=cont, desconto=dc, observacoes=obs
            )
            
            for aviso in avisos: st.warning(aviso)
            
            if erros:
                for erro in erros: st.error(erro)
            else:
                st.success(f"✅ Pedido #{id_criado} criado!")
                st.balloons()
                
                # --- RESET MANUAL DOS CAMPOS ---
                st.session_state.resetar_cliente_novo = True
                st.session_state.np_caruru = 0
                st.session_state.np_bobo = 0
                st.session_state.np_desc = 0
                st.session_state.np_obs = ""
                st.session_state.np_contato = ""
                
                st.rerun()

# --- EDITAR PEDIDO ---
elif menu == "✏️ Editar Pedido":
    st.title("✏️ Editar Pedido")
    df = st.session_state.pedidos
    if df.empty:
        st.warning("Nenhum pedido cadastrado.")
    else:
        st.markdown("### 🔍 Localizar Pedido")
        c1, c2, c3 = st.columns([1, 2, 2])
        with c1:
            busca_id = st.number_input("Buscar por ID", min_value=0, value=0, step=1)
        with c2:
            clientes_unicos = ["Todos"] + sorted(df['Cliente'].unique().tolist())
            filtro_cliente = st.selectbox("Filtrar por Cliente", clientes_unicos)
        with c3:
            filtro_data = st.date_input("Filtrar por Data", value=None, format="DD/MM/YYYY")
        
        df_filtrado = df.copy()
        if busca_id > 0: df_filtrado = df_filtrado[df_filtrado['ID_Pedido'] == busca_id]
        if filtro_cliente != "Todos": df_filtrado = df_filtrado[df_filtrado['Cliente'] == filtro_cliente]
        if filtro_data: df_filtrado = df_filtrado[df_filtrado['Data'] == filtro_data]
        
        if df_filtrado.empty:
            st.info("Nenhum pedido encontrado.")
        else:
            df_filtrado = df_filtrado.sort_values(['Data', 'ID_Pedido'], ascending=[False, False])
            opcoes_pedido = {
                row['ID_Pedido']: f"#{row['ID_Pedido']} | {row['Cliente']} | {row['Data'].strftime('%d/%m/%Y') if hasattr(row['Data'], 'strftime') else row['Data']} | R$ {row['Valor']:.2f} | {row['Status']}"
                for _, row in df_filtrado.iterrows()
            }
            pedido_selecionado = st.selectbox("Selecione para editar:", options=list(opcoes_pedido.keys()), format_func=lambda x: opcoes_pedido[x])
            
            if pedido_selecionado:
                pedido = buscar_pedido(pedido_selecionado)
                if pedido:
                    st.divider()
                    st.markdown(f"### 📝 Editando Pedido #{pedido_selecionado}")
                    with st.form("form_editar"):
                        c1, c2 = st.columns(2)
                        with c1:
                            try: clis = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
                            except: clis = []
                            c_atual = pedido.get('Cliente', '')
                            if c_atual and c_atual not in clis: clis = [c_atual] + clis
                            idx = clis.index(c_atual) if c_atual in clis else 0
                            novo_cli = st.selectbox("👤 Cliente", clis, index=idx)
                            
                            novo_dt = st.date_input("📅 Data", value=pedido.get('Data') or date.today(), format="DD/MM/YYYY")
                            hr_at = pedido.get('Hora'); hr_at = hr_at if isinstance(hr_at, time) else time(12,0)
                            novo_hr = st.time_input("⏰ Hora", value=hr_at)
                        
                        with c2:
                            novo_cont = st.text_input("📱 Contato", value=str(pedido.get('Contato', '')))
                            novo_st = st.selectbox("📊 Status", OPCOES_STATUS, index=OPCOES_STATUS.index(pedido.get('Status', '🔴 Pendente')) if pedido.get('Status') in OPCOES_STATUS else 0)
                            novo_pg = st.selectbox("💳 Pagamento", OPCOES_PAGAMENTO, index=OPCOES_PAGAMENTO.index(pedido.get('Pagamento', 'NÃO PAGO')) if pedido.get('Pagamento') in OPCOES_PAGAMENTO else 1)
                        
                        st.markdown("#### 🍽️ Itens")
                        c3, c4, c5 = st.columns(3)
                        with c3: n_car = st.number_input("🥘 Caruru", min_value=0, max_value=999, step=1, value=int(pedido.get('Caruru', 0)))
                        with c4: n_bob = st.number_input("🦐 Bobó", min_value=0, max_value=999, step=1, value=int(pedido.get('Bobo', 0)))
                        with c5: n_dsc = st.number_input("💸 Desc %", min_value=0, max_value=100, step=5, value=int(pedido.get('Desconto', 0)))
                        
                        n_obs = st.text_area("📝 Obs", value=str(pedido.get('Observacoes', '')))
                        
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1: btn_salvar = st.form_submit_button("💾 SALVAR ALTERAÇÕES", use_container_width=True, type="primary")
                        with col_btn2: btn_cancelar = st.form_submit_button("❌ Cancelar", use_container_width=True)
                        
                        if btn_salvar:
                            if n_car == 0 and n_bob == 0: st.error("❌ Pedido deve ter pelo menos 1 item.")
                            else:
                                campos = {
                                    "Cliente": novo_cli, "Data": novo_dt, "Hora": novo_hr, "Contato": novo_cont,
                                    "Status": novo_st, "Pagamento": novo_pg, "Caruru": n_car, "Bobo": n_bob,
                                    "Desconto": n_dsc, "Observacoes": n_obs
                                }
                                sucesso, msg = atualizar_pedido(pedido_selecionado, campos)
                                if sucesso: st.success(msg); st.rerun()
                                else: st.error(msg)
                        if btn_cancelar: st.rerun()

# --- EXCLUIR PEDIDO ---
elif menu == "🗑️ Excluir Pedido":
    st.title("🗑️ Excluir Pedido")
    df = st.session_state.pedidos
    if df.empty:
        st.warning("Nenhum pedido cadastrado.")
    else:
        st.warning("⚠️ **Atenção:** A exclusão é permanente!")
        st.markdown("### 🔍 Localizar Pedido")
        c1, c2 = st.columns(2)
        with c1: busca_id = st.number_input("Buscar por ID", min_value=0, value=0, step=1, key="del_id")
        with c2: 
            clis = ["Todos"] + sorted(df['Cliente'].unique().tolist())
            filtro_cli = st.selectbox("Filtrar por Cliente", clis, key="del_cli")
        
        df_del = df.copy()
        if busca_id > 0: df_del = df_del[df_del['ID_Pedido'] == busca_id]
        if filtro_cli != "Todos": df_del = df_del[df_del['Cliente'] == filtro_cli]
        
        if df_del.empty: st.info("Nenhum pedido encontrado.")
        else:
            df_del = df_del.sort_values(['Data', 'ID_Pedido'], ascending=[False, False])
            opcoes = {r['ID_Pedido']: f"#{r['ID_Pedido']} | {r['Cliente']} | R$ {r['Valor']:.2f}" for _, r in df_del.iterrows()}
            ped_exc = st.selectbox("Selecione para EXCLUIR:", options=list(opcoes.keys()), format_func=lambda x: opcoes[x], key="sel_del")
            
            if ped_exc:
                info = buscar_pedido(ped_exc)
                if info:
                    st.divider()
                    st.markdown(f"### 📋 Detalhes do Pedido #{ped_exc}")
                    st.write(f"**Cliente:** {info.get('Cliente')} | **Data:** {info.get('Data')} | **Valor:** R$ {info.get('Valor', 0):.2f}")
                    st.divider()
                    confirma = st.checkbox(f"✅ Confirmo a exclusão")
                    if st.button("🗑️ EXCLUIR", type="primary", disabled=not confirma, use_container_width=True):
                        sucesso, msg = excluir_pedido(ped_exc, "Manual")
                        if sucesso: st.success(msg); st.rerun()
                        else: st.error(msg)

# --- GERENCIAR TUDO ---
elif menu == "Gerenciar Tudo":
    st.title("📦 Todos os Pedidos")
    df = st.session_state.pedidos
    if not df.empty:
        try:
            df['sort'] = df['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
            df = df.sort_values(['Data', 'sort'], ascending=[False, True]).drop(columns=['sort'])
        except: pass
        
        with st.expander("🔍 Filtros", expanded=False):
            c1, c2, c3 = st.columns(3)
            with c1: f_st = st.multiselect("Status", OPCOES_STATUS, default=OPCOES_STATUS)
            with c2: f_pg = st.multiselect("Pagamento", OPCOES_PAGAMENTO, default=OPCOES_PAGAMENTO)
            with c3: f_per = st.selectbox("Período", ["Todos", "Hoje", "Esta Semana", "Este Mês"])
        
        df_view = df[df['Status'].isin(f_st) & df['Pagamento'].isin(f_pg)]
        if f_per == "Hoje": df_view = df_view[df_view['Data'] == date.today()]
        elif f_per == "Esta Semana": df_view = df_view[df_view['Data'] >= (date.today() - timedelta(days=date.today().weekday()))]
        elif f_per == "Este Mês": df_view = df_view[df_view['Data'] >= date.today().replace(day=1)]
        
        st.markdown(f"**{len(df_view)}** pedidos | **Total:** R$ {df_view['Valor'].sum():,.2f}")
        
        edited = st.data_editor(
            df_view, num_rows="fixed", use_container_width=True, hide_index=True,
            column_config={
                "ID_Pedido": st.column_config.NumberColumn("#", disabled=True, width="small"),
                "Valor": st.column_config.NumberColumn("Total", format="R$ %.2f", disabled=True),
                "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "Hora": st.column_config.TimeColumn("Hora", format="HH:mm"),
                "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                "Pagamento": st.column_config.SelectboxColumn(options=OPCOES_PAGAMENTO, required=True),
                "Caruru": st.column_config.NumberColumn("Caruru", min_value=0, max_value=999, format="%d"),
                "Bobo": st.column_config.NumberColumn("Bobó", min_value=0, max_value=999, format="%d"),
                "Desconto": st.column_config.NumberColumn("Desc %", min_value=0, max_value=100, format="%d"),
            }
        )
        if not edited.equals(df_view):
            try:
                edited['Valor'] = edited.apply(lambda row: calcular_total(row['Caruru'], row['Bobo'], row['Desconto']), axis=1)
                df_master = st.session_state.pedidos.copy()
                for idx in edited.index:
                    mask = df_master['ID_Pedido'] == edited.at[idx, 'ID_Pedido']
                    if mask.any():
                        for col in edited.columns:
                            if col != 'ID_Pedido': df_master.loc[mask, col] = edited.at[idx, col]
                st.session_state.pedidos = df_master
                salvar_pedidos(df_master)
                st.toast("💾 Salvo!", icon="✅")
                st.rerun()
            except Exception as e: st.error(f"Erro ao salvar: {e}")
        
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("💬 WhatsApp Rápido")
            if not df_view.empty:
                sel = st.selectbox("Cliente:", sorted(df_view['Cliente'].unique()), key="zap_cli")
                if sel:
                    d = df_view[df_view['Cliente'] == sel].iloc[-1]
                    msg = f"Olá {sel}! 🦐\n\nSeu pedido:\n"
                    if d['Caruru'] > 0: msg += f"• {int(d['Caruru'])}x Caruru\n"
                    if d['Bobo'] > 0: msg += f"• {int(d['Bobo'])}x Bobó\n"
                    msg += f"\n💵 Total: R$ {d['Valor']:.2f}"
                    if d['Pagamento'] in ["NÃO PAGO", "METADE"]: msg += f"\n\n📲 Pix: {CHAVE_PIX}"
                    lnk = gerar_link_whatsapp(d['Contato'], msg)
                    if lnk: st.link_button("📱 Enviar WhatsApp", lnk, use_container_width=True)
                    else: st.warning("Contato inválido.")
    else: st.info("Nenhum pedido.")
    
    st.divider()
    with st.expander("💾 Backup & Restauração"):
        st.write("### 📥 Fazer Backup")
        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED, False) as z:
                z.writestr("pedidos.csv", st.session_state.pedidos.to_csv(index=False))
                z.writestr("clientes.csv", st.session_state.clientes.to_csv(index=False))
                if os.path.exists(ARQUIVO_HISTORICO):
                    with open(ARQUIVO_HISTORICO, 'r') as f: z.writestr("historico.csv", f.read())
            st.download_button("📥 Baixar Backup Completo (ZIP)", buf.getvalue(), f"backup_{date.today()}.zip", "application/zip")
        except: st.error("Erro backup.")
        
        st.write("### 📤 Restaurar Pedidos")
        up = st.file_uploader("Arquivo Pedidos (CSV)", type="csv", key="rest_ped")
        if up and st.button("⚠️ Restaurar Pedidos"):
            try:
                df_n = pd.read_csv(up)
                salvar_pedidos(df_n)
                st.session_state.pedidos = carregar_pedidos()
                st.success("✅ Restaurado!")
                st.rerun()
            except: st.error("Erro.")

# --- RELATÓRIOS ---
elif menu == "🖨️ Relatórios & Recibos":
    st.title("🖨️ Impressão de Documentos")
    t1, t2 = st.tabs(["📄 Recibo Individual", "📊 Relatório Geral"])
    df = st.session_state.pedidos
    
    with t1:
        if df.empty: st.info("Sem pedidos.")
        else:
            cli = st.selectbox("👤 Cliente:", sorted(df['Cliente'].unique()))
            peds = df[df['Cliente'] == cli].sort_values("Data", ascending=False)
            if not peds.empty:
                opc = {i: f"#{p['ID_Pedido']} | {p['Data'].strftime('%d/%m/%Y') if hasattr(p['Data'], 'strftime') else p['Data']} | R$ {p['Valor']:.2f} | {p['Status']}" for i, p in peds.iterrows()}
                sid = st.selectbox("📋 Selecione o pedido:", options=opc.keys(), format_func=lambda x: opc[x])
                if st.button("📄 Gerar Recibo PDF", use_container_width=True, type="primary"):
                    pdf = gerar_recibo_pdf(peds.loc[sid].to_dict())
                    if pdf: st.download_button("⬇️ Baixar Recibo", pdf, f"Recibo_{cli}_{peds.loc[sid]['ID_Pedido']}.pdf", "application/pdf")
                    else: st.error("Erro ao gerar PDF.")
    with t2:
        tipo = st.radio("📅 Filtro:", ["Dia Específico", "Período", "Tudo"], horizontal=True)
        if tipo == "Dia Específico":
            dt = st.date_input("Data:", date.today(), format="DD/MM/YYYY", key="rel_data")
            df_rel = df[df['Data'] == dt]
            nome = f"Relatorio_{dt.strftime('%d-%m-%Y')}.pdf"
        elif tipo == "Período":
            c1, c2 = st.columns(2)
            with c1: dt_ini = st.date_input("De:", date.today()-timedelta(days=7), format="DD/MM/YYYY")
            with c2: dt_fim = st.date_input("Até:", date.today(), format="DD/MM/YYYY")
            df_rel = df[(df['Data'] >= dt_ini) & (df['Data'] <= dt_fim)]
            nome = f"Relatorio_{dt_ini.strftime('%d-%m')}_{dt_fim.strftime('%d-%m-%Y')}.pdf"
        else:
            df_rel = df; nome = "Relatorio_Geral.pdf"
        st.write(f"📊 **{len(df_rel)}** pedidos | **Total:** R$ {df_rel['Valor'].sum():,.2f}")
        if not df_rel.empty:
            if st.button("📊 Gerar Relatório PDF", use_container_width=True, type="primary"):
                pdf = gerar_relatorio_pdf(df_rel, nome.replace(".pdf", ""))
                if pdf: st.download_button("⬇️ Baixar Relatório", pdf, nome, "application/pdf")
                else: st.error("Erro ao gerar PDF.")

# --- PROMOÇÕES ---
elif menu == "📢 Promoções":
    st.title("📢 Marketing & Promoções")
    st.subheader("1️⃣ Configurar Mensagem")
    c_img, c_txt = st.columns([1, 2])
    with c_img:
        up = st.file_uploader("🖼️ Banner", type=["jpg","png"])
        if up: st.image(up, caption="Preview", use_column_width=True); st.info("Anexe manualmente no WhatsApp.")
    with c_txt:
        msg = st.text_area("✏️ Texto", "Olá! 🦐\nHoje tem caruru fresquinho!", height=200)
    st.divider()
    st.subheader("2️⃣ Enviar")
    df_c = st.session_state.clientes
    if df_c.empty: st.warning("Sem clientes.")
    else:
        filtro = st.text_input("🔍 Buscar:")
        if filtro: df_c = df_c[df_c['Nome'].str.contains(filtro, case=False, na=False)]
        msg_enc = urllib.parse.quote(msg)
        df_show = df_c[['Nome','Contato']].copy()
        df_show['Link'] = df_show['Contato'].apply(lambda x: gerar_link_whatsapp(x, msg))
        st.data_editor(df_show, column_config={"Link": st.column_config.LinkColumn("Ação", display_text="📱 Enviar"), "Nome": st.column_config.TextColumn(disabled=True), "Contato": st.column_config.TextColumn(disabled=True)}, hide_index=True, use_container_width=True)

# --- CLIENTES ---
elif menu == "👥 Cadastrar Clientes":
    st.title("👥 Gestão de Clientes")
    t1, t2, t3 = st.tabs(["➕ Cadastrar", "📋 Lista", "🗑️ Excluir"])
    with t1:
        st.subheader("Novo Cliente")
        with st.form("cli_form", clear_on_submit=True):
            n = st.text_input("👤 Nome*", placeholder="Ex: João Silva")
            z = st.text_input("📱 WhatsApp", placeholder="79999999999")
            o = st.text_area("📝 Observações")
            if st.form_submit_button("💾 Cadastrar", use_container_width=True, type="primary"):
                if not n.strip(): st.error("❌ Nome é obrigatório!")
                else:
                    nomes = st.session_state.clientes['Nome'].str.lower().str.strip().tolist()
                    if n.lower().strip() in nomes: st.warning(f"⚠️ Cliente '{n}' já cadastrado!")
                    else:
                        tel, msg = validar_telefone(z)
                        if msg: st.warning(msg)
                        novo = pd.DataFrame([{"Nome": n.strip(), "Contato": tel, "Observacoes": o.strip()}])
                        st.session_state.clientes = pd.concat([st.session_state.clientes, novo], ignore_index=True)
                        salvar_clientes(st.session_state.clientes)
                        st.success(f"✅ Cliente '{n}' cadastrado!"); st.rerun()
    with t2:
        st.subheader("Lista de Clientes")
        if not st.session_state.clientes.empty:
            edited = st.data_editor(st.session_state.clientes, num_rows="fixed", use_container_width=True, hide_index=True)
            if not edited.equals(st.session_state.clientes):
                st.session_state.clientes = edited
                salvar_clientes(edited)
                st.toast("💾 Salvo!")
            st.divider()
            c1, c2 = st.columns(2)
            with c1:
                if st.button("📄 Exportar Lista PDF", use_container_width=True):
                    pdf = gerar_lista_clientes_pdf(st.session_state.clientes)
                    if pdf: st.download_button("⬇️ Baixar PDF", pdf, "Clientes.pdf", "application/pdf")
            with c2:
                csv = st.session_state.clientes.to_csv(index=False).encode('utf-8')
                st.download_button("📊 Exportar CSV", csv, "clientes.csv", "text/csv", use_container_width=True)
        else: st.info("Nenhum cliente.")
        with st.expander("📤 Importar Clientes"):
            up = st.file_uploader("Arquivo CSV", type="csv", key="imp_cli")
            if up and st.button("⚠️ Importar"):
                try:
                    df = pd.read_csv(up)
                    salvar_clientes(df)
                    st.session_state.clientes = carregar_clientes()
                    st.success("✅ Importado!"); st.rerun()
                except Exception as e: st.error(f"Erro: {e}")
    with t3:
        if not st.session_state.clientes.empty:
            l = st.session_state.clientes['Nome'].unique().tolist()
            d = st.selectbox("👤 Selecione o cliente:", l)
            if st.button("🗑️ Excluir Cliente", type="primary", use_container_width=True):
                st.session_state.clientes = st.session_state.clientes[st.session_state.clientes['Nome'] != d]
                salvar_clientes(st.session_state.clientes)
                st.success(f"✅ Cliente '{d}' excluído!"); st.rerun()
        else: st.info("Nenhum cliente.")

# --- ADMIN ---
elif menu == "🛠️ Manutenção":
    st.title("🛠️ Manutenção")
    t1, t2, t3 = st.tabs(["📋 Logs", "📜 Histórico", "⚙️ Config"])
    with t1:
        if os.path.exists(ARQUIVO_LOG):
            with open(ARQUIVO_LOG, "r") as f: log = f.read()
            st.text_area("", log, height=300)
            if st.button("🗑️ Limpar Logs"): open(ARQUIVO_LOG, 'w').close(); st.rerun()
    with t2:
        if os.path.exists(ARQUIVO_HISTORICO):
            try:
                df = pd.read_csv(ARQUIVO_HISTORICO).sort_values('Timestamp', ascending=False)
                st.dataframe(df, use_container_width=True, hide_index=True)
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Exportar", csv, "historico.csv", "text/csv")
                if st.button("🗑️ Limpar Histórico"): os.remove(ARQUIVO_HISTORICO); st.rerun()
            except: st.info("Histórico vazio.")
    with t3:
        st.write(f"**Versão:** {VERSAO}")
        st.write(f"**Pedidos:** {len(st.session_state.pedidos)}")
        st.write(f"**Clientes:** {len(st.session_state.clientes)}")
        if st.button("🔄 Recarregar Dados", use_container_width=True):
            st.session_state.pedidos = carregar_pedidos()
            st.session_state.clientes = carregar_clientes()
            st.success("✅ Recarregado!"); st.rerun()
