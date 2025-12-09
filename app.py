import streamlit as st
import pandas as pd
from datetime import date, datetime, time
import os
import io
import zipfile
import logging
import urllib.parse
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
CHAVE_PIX = "79999296722"
OPCOES_STATUS = ["🔴 Pendente", "🟡 Em Produção", "✅ Entregue", "🚫 Cancelado"]
OPCOES_PAGAMENTO = ["PAGO", "NÃO PAGO", "METADE"]
PRECO_BASE = 70.0
VERSAO = "17.0"

logging.basicConfig(filename=ARQUIVO_LOG, level=logging.ERROR, format='%(asctime)s | %(levelname)s | %(message)s', force=True)
logger = logging.getLogger("cantinho")

# ==============================================================================
# FUNÇÕES DE LIMPEZA E CÁLCULO
# ==============================================================================
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

def gerar_id_sequencial(df):
    try:
        if df.empty: return 1
        df = df.copy()
        df['ID_Pedido'] = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
        return int(df['ID_Pedido'].max()) + 1
    except: return 1

def calcular_total(caruru, bobo, desconto):
    try:
        total = (float(caruru or 0) * PRECO_BASE) + (float(bobo or 0) * PRECO_BASE)
        if desconto and float(desconto) > 0:
            total = total * (1 - float(desconto) / 100.0)
        return round(total, 2)
    except: return 0.0

# ==============================================================================
# BANCO DE DADOS
# ==============================================================================
def carregar_clientes():
    colunas = ["Nome", "Contato", "Observacoes"]
    if not os.path.exists(ARQUIVO_CLIENTES): return pd.DataFrame(columns=colunas)
    try:
        df = pd.read_csv(ARQUIVO_CLIENTES, dtype=str).fillna("")
        for c in colunas:
            if c not in df.columns: df[c] = ""
        return df[colunas]
    except Exception as e:
        logger.error(f"Erro carregar clientes: {e}")
        return pd.DataFrame(columns=colunas)

def carregar_pedidos():
    colunas_padrao = ["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]
    if not os.path.exists(ARQUIVO_PEDIDOS): return pd.DataFrame(columns=colunas_padrao)
    try:
        df = pd.read_csv(ARQUIVO_PEDIDOS)
        for c in colunas_padrao:
            if c not in df.columns: df[c] = None
        
        # Conversões
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
    except Exception as e:
        logger.error(f"Erro carregar pedidos: {e}")
        return pd.DataFrame(columns=colunas_padrao)

def salvar_pedidos(df):
    try:
        salvar = df.copy()
        salvar['Data'] = salvar['Data'].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x)
        salvar['Hora'] = salvar['Hora'].apply(lambda x: x.strftime('%H:%M') if isinstance(x, time) else str(x))
        salvar.to_csv(ARQUIVO_PEDIDOS, index=False)
    except Exception as e: logger.error(f"Erro salvar pedidos: {e}")

def salvar_clientes(df):
    try: df.to_csv(ARQUIVO_CLIENTES, index=False)
    except Exception as e: logger.error(f"Erro salvar clientes: {e}")

# ==============================================================================
# PDF GENERATOR
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
        p.drawString(30, y, f"Nome: {dados.get('Cliente','')}")
        p.drawString(300, y, f"WhatsApp: {dados.get('Contato','')}")
        y-=20
        
        dt = dados.get('Data'); dt_s = dt.strftime('%d/%m/%Y') if hasattr(dt, 'strftime') else str(dt)
        hr = dados.get('Hora'); hr_s = hr.strftime('%H:%M') if isinstance(hr, time) else str(hr)[:5]
        p.drawString(30, y, f"Data: {dt_s}"); p.drawString(300, y, f"Hora: {hr_s}")
        
        y-=40; p.setFillColor(colors.lightgrey); p.rect(30, y-5, 535, 20, fill=1, stroke=0)
        p.setFillColor(colors.black); p.setFont("Helvetica-Bold", 10)
        p.drawString(40, y, "ITEM"); p.drawString(400, y, "QTD"); y-=25
        p.setFont("Helvetica", 10)
        
        if float(dados.get('Caruru',0)) > 0:
            p.drawString(40, y, "Caruru Tradicional"); p.drawString(400, y, f"{int(float(dados.get('Caruru')))}"); y-=15
        if float(dados.get('Bobo',0)) > 0:
            p.drawString(40, y, "Bobó de Camarão"); p.drawString(400, y, f"{int(float(dados.get('Bobo')))}"); y-=15
        p.line(30, y-5, 565, y-5)
        
        y-=40; p.setFont("Helvetica-Bold", 14)
        lbl = "TOTAL PAGO" if dados.get('Pagamento') == "PAGO" else "VALOR A PAGAR"
        p.drawString(350, y, f"{lbl}: R$ {float(dados.get('Valor',0)):.2f}")
        
        y-=25; p.setFont("Helvetica-Bold", 12)
        sit = dados.get('Pagamento')
        if sit == "PAGO":
            p.setFillColor(colors.green); p.drawString(30, y+25, "SITUAÇÃO: PAGO ✅")
        else:
            p.setFillColor(colors.red); p.drawString(30, y+25, "SITUAÇÃO: PENDENTE ❌")
            p.setFillColor(colors.black); p.setFont("Helvetica", 10); p.drawString(30, y, f"Pix: {CHAVE_PIX}")
        
        p.setFillColor(colors.black)
        if dados.get('Observacoes'):
            y-=30; p.setFont("Helvetica-Oblique", 10); p.drawString(30, y, f"Obs: {dados.get('Observacoes')}")
            
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
        cols = [30, 60, 110, 230, 270, 320, 380, 470]
        hdrs = ["ID", "Data", "Cliente", "Caruru", "Bobó", "Valor", "Status", "Pagto"]
        for x, h in zip(cols, hdrs): p.drawString(x, y, h)
        y-=20; p.setFont("Helvetica", 9); total=0
        
        for _, row in df_filtrado.iterrows():
            if y < 60: p.showPage(); desenhar_cabecalho(p, titulo_relatorio); y=700
            d_s = row['Data'].strftime('%d/%m') if hasattr(row['Data'], 'strftime') else ""
            st_cl = str(row['Status']).replace("🔴","").replace("✅","").replace("🟡","").strip()[:10]
            
            p.drawString(30, y, str(row.get('ID_Pedido','')))
            p.drawString(60, y, d_s)
            p.drawString(110, y, str(row.get('Cliente',''))[:18])
            p.drawString(230, y, str(int(row.get('Caruru',0))))
            p.drawString(270, y, str(int(row.get('Bobo',0))))
            p.drawString(320, y, f"{row.get('Valor',0):.2f}")
            p.drawString(380, y, st_cl)
            p.drawString(470, y, str(row.get('Pagamento','')))
            total += row.get('Valor', 0); y-=15
            
        p.line(30, y, 565, y); p.setFont("Helvetica-Bold", 11); p.drawString(320, y-20, f"TOTAL: R$ {total:,.2f}")
        p.showPage(); p.save(); buffer.seek(0)
        return buffer
    except: return None

def gerar_lista_clientes_pdf(df):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        y = 700; desenhar_cabecalho(p, "Lista de Clientes")
        p.setFont("Helvetica-Bold", 10)
        p.drawString(30, y, "Nome"); p.drawString(250, y, "WhatsApp"); p.drawString(380, y, "Obs")
        y-=20; p.setFont("Helvetica", 10)
        for _, row in df.sort_values('Nome').iterrows():
            if y < 60: p.showPage(); desenhar_cabecalho(p, "Lista de Clientes"); y=700
            p.drawString(30, y, str(row['Nome'])[:35])
            p.drawString(250, y, str(row['Contato']))
            p.drawString(380, y, str(row['Observacoes'])[:30])
            y-=20; p.setLineWidth(0.5); p.setStrokeColor(colors.lightgrey); p.line(30, y+15, 565, y+15)
        p.showPage(); p.save(); buffer.seek(0)
        return buffer
    except: return None

def atualizar_contato_novo_pedido():
    try:
        c_at = st.session_state.get('chave_cliente_selecionado')
        if c_at:
            busca = st.session_state.clientes[st.session_state.clientes['Nome'] == c_at]
            if not busca.empty: st.session_state['chave_contato_automatico'] = busca.iloc[0]['Contato']
            else: st.session_state['chave_contato_automatico'] = ""
        else: st.session_state['chave_contato_automatico'] = ""
    except: pass

# ---------------------------- START ----------------------------
if 'pedidos' not in st.session_state: st.session_state.pedidos = carregar_pedidos()
if 'clientes' not in st.session_state: st.session_state.clientes = carregar_clientes()
if 'chave_contato_automatico' not in st.session_state: st.session_state['chave_contato_automatico'] = ""

with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=250)
    else: st.title("🦐 Cantinho do Caruru")
    st.divider()
    menu = st.radio("Navegação", ["Dashboard do Dia", "Novo Pedido", "Gerenciar Tudo", "🖨️ Relatórios & Recibos", "📢 Promoções", "👥 Cadastrar Clientes", "🛠️ Manutenção"])
    st.divider()
    st.caption(f"Versão {VERSAO}")

# ---------------------------- PÁGINAS ----------------------------

if menu == "Dashboard do Dia":
    st.title("🦐🏍️ Expedição do Dia")
    df = st.session_state.pedidos
    if df.empty: st.info("Sem dados.")
    else:
        dt_filter = st.date_input("Data:", date.today(), format="DD/MM/YYYY")
        df_dia = df[df['Data'] == dt_filter].copy()
        
        try:
            df_dia['h'] = df_dia['Hora'].apply(lambda x: x if x else time(23,59))
            df_dia = df_dia.sort_values('h')
        except: pass
        
        c1, c2, c3, c4 = st.columns(4)
        pend = df_dia[
            (~df_dia['Status'].str.contains("Entregue", na=False)) & 
            (~df_dia['Status'].str.contains("Cancelado", na=False))
        ]
        c1.metric("Caruru (Pend)", int(pend['Caruru'].sum()))
        c2.metric("Bobó (Pend)", int(pend['Bobo'].sum()))
        c3.metric("Faturamento", f"R$ {df_dia['Valor'].sum():,.2f}")
        rec = df_dia[df_dia['Pagamento'] != 'PAGO']['Valor'].sum()
        c4.metric("A Receber", f"R$ {rec:,.2f}", delta_color="inverse")
        
        st.divider(); st.subheader("📋 Entregas")
        if not df_dia.empty:
            df_dia['Hora'] = df_dia['Hora'].apply(limpar_hora_rigoroso)
            edited = st.data_editor(
                df_dia,
                column_order=["ID_Pedido", "Hora", "Status", "Cliente", "Caruru", "Bobo", "Valor", "Pagamento", "Observacoes"],
                disabled=["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Hora"],
                hide_index=True, use_container_width=True, key="dash",
                column_config={
                    "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
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
                        df_glob.loc[mask, edited.columns] = edited.loc[i].values
                st.session_state.pedidos = df_glob
                salvar_pedidos(df_glob)
                st.toast("Atualizado!", icon="✅")
                st.rerun()

elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    try: clis = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
    except: clis = []
    
    def update_cont():
        sel = st.session_state.get("sel_cli")
        if sel:
            res = st.session_state.clientes[st.session_state.clientes['Nome'] == sel]
            st.session_state["auto_contato"] = res.iloc[0]['Contato'] if not res.empty else ""
        else: st.session_state["auto_contato"] = ""

    st.markdown("### 1. Cliente")
    c1, c2 = st.columns([3, 1])
    with c1: c_sel = st.selectbox("Nome", [""]+clis, key="sel_cli", on_change=update_cont)
    with c2: h_ent = st.time_input("Hora", value=time(12,0))
    
    st.markdown("### 2. Dados")
    with st.form("form_novo", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1: cont = st.text_input("WhatsApp", key="auto_contato")
        with c2: dt = st.date_input("Data", min_value=date.today(), format="DD/MM/YYYY")
        c3, c4, c5 = st.columns(3)
        with c3: qc = st.number_input("Caruru", 0.0, step=1.0)
        with c4: qb = st.number_input("Bobó", 0.0, step=1.0)
        with c5: dc = st.number_input("Desc %", 0, 100)
        obs = st.text_area("Obs")
        c6, c7 = st.columns(2)
        with c6: pg = st.selectbox("Pagto", OPCOES_PAGAMENTO)
        with c7: stt = st.selectbox("Status", OPCOES_STATUS)
        
        if st.form_submit_button("💾 SALVAR"):
            if not c_sel: st.error("Selecione um cliente.")
            else:
                try:
                    df_p = st.session_state.pedidos
                    nid = gerar_id_sequencial(df_p)
                    val = calcular_total(qc, qb, dc)
                    novo = {
                        "ID_Pedido": nid, "Cliente": c_sel, "Caruru": qc, "Bobo": qb, "Valor": val,
                        "Data": dt, "Hora": h_ent.strftime("%H:%M"), "Status": stt, "Pagamento": pg,
                        "Contato": cont, "Desconto": dc, "Observacoes": obs
                    }
                    df_novo = pd.DataFrame([novo])
                    df_novo['Data'] = pd.to_datetime(df_novo['Data']).dt.date
                    st.session_state.pedidos = pd.concat([df_p, df_novo], ignore_index=True)
                    salvar_pedidos(st.session_state.pedidos)
                    st.session_state.pedidos = carregar_pedidos()
                    st.success(f"Pedido #{nid} criado!")
                    st.rerun()
                except Exception as e:
                    logger.error(f"Erro novo pedido: {e}")
                    st.error("Erro ao salvar.")

elif menu == "Gerenciar Tudo":
    st.title("📦 Todos os Pedidos")
    st.info("💡 Dica: Clique em qualquer célula da tabela para editar Nome, Data, Hora, etc.")
    
    df = st.session_state.pedidos
    if not df.empty:
        try:
            df['sort'] = df['Hora'].apply(lambda x: x if x else time(0,0))
            df = df.sort_values(['Data', 'sort']).drop(columns=['sort'])
        except: pass
        
        df['Hora'] = df['Hora'].apply(limpar_hora_rigoroso)

        edited = st.data_editor(
            df,
            num_rows="dynamic", use_container_width=True, hide_index=True,
            column_config={
                "ID_Pedido": st.column_config.NumberColumn("#", disabled=True, width="small"),
                "Valor": st.column_config.NumberColumn("Total", format="R$ %.2f", disabled=True),
                "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "Hora": st.column_config.TimeColumn("Hora", format="HH:mm"),
                "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                "Pagamento": st.column_config.SelectboxColumn(options=OPCOES_PAGAMENTO, required=True),
            }
        )
        if not edited.equals(df):
            try:
                edited['Valor'] = ((edited['Caruru'] * PRECO_BASE) + (edited['Bobo'] * PRECO_BASE)) * (1 - (edited['Desconto']/100))
                st.session_state.pedidos = edited
                salvar_pedidos(edited)
                st.toast("Salvo!", icon="💾")
                st.rerun()
            except: st.error("Erro ao salvar edição.")
            
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("💬 Zap")
            try:
                sel = st.selectbox("Cliente:", sorted(df['Cliente'].unique()))
                if sel:
                    d = df[df['Cliente'] == sel].iloc[-1]
                    t = str(d.get('Contato') or "").replace(".0", "").replace(" ", "").replace("-", "")
                    msg = f"Olá {sel}, pedido confirmado! R$ {d['Valor']:.2f}"
                    if d['Pagamento'] in ["NÃO PAGO", "METADE"]: msg += f"\nPix: {CHAVE_PIX}"
                    lnk = f"https://wa.me/55{t}?text={msg.replace(' ', '%20')}"
                    st.link_button("Enviar Zap", lnk)
            except: pass
        
        # --- ÁREA DE EXCLUSÃO (VOLTOU!) ---
        with c2:
             st.subheader("🗑️ Excluir Pedido")
             with st.expander("Abrir Exclusão"):
                 st.warning("Cuidado: Ação permanente.")
                 df['Display_Del'] = df.apply(lambda x: f"#{int(x['ID_Pedido'])} - {x['Cliente']} ({x['Data']})", axis=1)
                 lista_del = df['Display_Del'].tolist()
                 ped_del = st.selectbox("Escolha:", options=lista_del)
                 if st.button("CONFIRMAR EXCLUSÃO"):
                     if ped_del:
                         id_apagar = int(ped_del.split(' - ')[0].replace('#', ''))
                         st.session_state.pedidos = st.session_state.pedidos[st.session_state.pedidos['ID_Pedido'] != id_apagar]
                         salvar_pedidos(st.session_state.pedidos)
                         st.success(f"Excluído!")
                         st.rerun()

    st.divider()
    with st.expander("💾 Backup & Restauração (Pedidos)"):
        st.write("### 1. Fazer Backup")
        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED, False) as z:
                z.writestr("pedidos.csv", st.session_state.pedidos.to_csv(index=False))
                z.writestr("clientes.csv", st.session_state.clientes.to_csv(index=False))
            st.download_button("📥 Baixar Tudo (ZIP)", buf.getvalue(), f"backup_{date.today()}.zip", "application/zip")
        except: st.error("Erro backup.")
        
        st.write("### 2. Restaurar Pedidos")
        up = st.file_uploader("Arquivo Pedidos (CSV)", type="csv", key="rest_ped")
        if up and st.button("Restaurar Pedidos"):
            try:
                df_n = pd.read_csv(up)
                salvar_pedidos(df_n)
                st.session_state.pedidos = carregar_pedidos()
                st.success("OK!")
                st.rerun()
            except: st.error("Erro restauração.")

elif menu == "Relatórios & Recibos":
    st.title("🖨️ Impressão")
    t1, t2 = st.tabs(["Recibo Individual", "Relatório Geral"])
    df = st.session_state.pedidos
    with t1:
        if df.empty: st.info("Sem pedidos.")
        else:
            cli = st.selectbox("Cliente:", sorted(df['Cliente'].unique()))
            peds = df[df['Cliente'] == cli].sort_values("Data", ascending=False)
            if not peds.empty:
                opc = {i: f"#{p['ID_Pedido']} | {p['Data']} | R$ {p['Valor']:.2f}" for i, p in peds.iterrows()}
                sid = st.selectbox("Selecione:", options=opc.keys(), format_func=lambda x: opc[x])
                if st.button("📄 Gerar PDF"):
                    pdf = gerar_recibo_pdf(peds.loc[sid])
                    if pdf: st.download_button("Baixar", pdf, f"Recibo_{cli}.pdf", "application/pdf")
                    else: st.error("Erro ao gerar PDF.")
    with t2:
        tipo = st.radio("Filtro:", ["Dia Específico", "Tudo"])
        if tipo == "Dia Específico":
            dt = st.date_input("Data:", date.today(), format="DD/MM/YYYY")
            df_rel = df[df['Data'] == dt]
            nome = f"Relatorio_{dt}.pdf"
        else:
            df_rel = df; nome = "Relatorio_Geral.pdf"
        st.write(f"Linhas: {len(df_rel)}")
        if not df_rel.empty:
            if st.button("📊 Gerar Relatório"):
                pdf = gerar_relatorio_pdf(df_rel, nome.replace(".pdf", ""))
                if pdf: st.download_button("Baixar PDF", pdf, nome, "application/pdf")

elif menu == "📢 Promoções":
    st.title("📢 Marketing & Promoções")
    st.subheader("1. Configurar Mensagem")
    c_img, c_txt = st.columns([1, 2])
    with c_img:
        up_img = st.file_uploader("Banner (Visualização)", type=["jpg","png","jpeg"])
        if up_img: st.image(up_img, caption="Banner", use_column_width=True); st.info("Anexe a imagem manualmente no WhatsApp.")
    with c_txt:
        txt_padrao = "Olá! 🦐\n\nHoje tem *Caruru Fresquinho*!\nPeça já o seu. 😋"
        msg = st.text_area("Texto", value=txt_padrao, height=200)
    
    st.divider()
    st.subheader("2. Enviar")
    df_c = st.session_state.clientes
    if df_c.empty: st.warning("Sem clientes.")
    else:
        filtro = st.text_input("🔍 Buscar:")
        if filtro: df_c = df_c[df_c['Nome'].str.contains(filtro, case=False) | df_c['Contato'].str.contains(filtro)]
        
        msg_enc = urllib.parse.quote(msg)
        df_show = df_c[['Nome','Contato']].copy()
        
        def link_zap(tel):
            t = str(tel).replace(" ","").replace("-","").replace(".0","")
            return f"https://wa.me/55{t}?text={msg_enc}" if len(t) >= 10 else None
            
        df_show['Link'] = df_show['Contato'].apply(link_zap)
        
        st.data_editor(
            df_show,
            column_config={
                "Link": st.column_config.LinkColumn("Ação", display_text="Enviar 🚀"),
                "Nome": st.column_config.TextColumn(disabled=True),
                "Contato": st.column_config.TextColumn(disabled=True)
            },
            hide_index=True,
            use_container_width=True
        )

elif menu == "👥 Cadastrar Clientes":
    st.title("👥 Clientes")
    t1, t2 = st.tabs(["Cadastro", "Excluir"])
    with t1:
        with st.form("cli_form", clear_on_submit=True):
            n = st.text_input("Nome"); z = st.text_input("Zap"); o = st.text_area("Obs")
            if st.form_submit_button("Salvar") and n:
                novo = pd.DataFrame([{"Nome": n, "Contato": z, "Observacoes": o}])
                st.session_state.clientes = pd.concat([st.session_state.clientes, novo], ignore_index=True)
                salvar_clientes(st.session_state.clientes)
                st.success("Cadastrado!")
                st.rerun()
        if not st.session_state.clientes.empty:
            edited = st.data_editor(st.session_state.clientes, num_rows="dynamic", use_container_width=True, hide_index=True)
            if not edited.equals(st.session_state.clientes):
                st.session_state.clientes = edited
                salvar_clientes(edited)
                st.toast("Salvo!")
        st.divider()
        if st.button("📄 Exportar Lista PDF"):
            pdf = gerar_lista_clientes_pdf(st.session_state.clientes)
            if pdf: st.download_button("Baixar Lista PDF", pdf, "Clientes.pdf", "application/pdf")
        with st.expander("💾 Backup Clientes"):
            try:
                csv = st.session_state.clientes.to_csv(index=False).encode('utf-8')
                st.download_button("Baixar CSV", csv, "clientes.csv", "text/csv")
            except: pass
            up_c = st.file_uploader("Restaurar Clientes", type="csv", key="rest_cli")
            if up_c and st.button("Restaurar"):
                try:
                    df_c = pd.read_csv(up_c)
                    salvar_clientes(df_c)
                    st.session_state.clientes = carregar_clientes()
                    st.success("OK!"); st.rerun()
                except: st.error("Erro.")
    with t2:
        l = st.session_state.clientes['Nome'].unique()
        d = st.selectbox("Excluir quem?", l)
        if st.button("Confirmar"):
            st.session_state.clientes = st.session_state.clientes[st.session_state.clientes['Nome'] != d]
            salvar_clientes(st.session_state.clientes)
            st.rerun()

elif menu == "🛠️ Manutenção":
    st.title("🛠️ Admin")
    if os.path.exists(ARQUIVO_LOG):
        with open(ARQUIVO_LOG, "r") as f: log = f.read()
        with st.expander("Ver Logs"):
            st.text_area("", log)
            if st.button("Limpar"): open(ARQUIVO_LOG, 'w').close(); st.rerun()
