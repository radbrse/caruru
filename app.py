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

# --- 1. CONFIGURAÇÃO GERAL E LOGS ---
st.set_page_config(page_title="Cantinho do Caruru", page_icon="🦐", layout="wide")

ARQUIVO_PEDIDOS = "banco_de_dados_caruru.csv"
ARQUIVO_CLIENTES = "banco_de_dados_clientes.csv"
ARQUIVO_LOG = "system_errors.log"
CHAVE_PIX = "79999296722"

# Configuração de Logging (Registra erros sem travar a tela)
logging.basicConfig(
    filename=ARQUIVO_LOG,
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s',
    force=True
)

# Constantes
OPCOES_STATUS = ["🔴 Pendente", "🟡 Em Produção", "✅ Entregue", "🚫 Cancelado"]
OPCOES_PAGAMENTO = ["PAGO", "NÃO PAGO", "METADE"]

# --- 2. FUNÇÕES UTILITÁRIAS (HELPER) ---

def limpar_hora_rigoroso(h):
    """Converte horários de diversos formatos para objeto time de forma segura"""
    if h in [None, "", "nan", "NaT"] or pd.isna(h):
        return None

    if isinstance(h, time):
        return h

    # Tenta formatos comuns
    formatos = ["%H:%M", "%H:%M:%S", "%H:%M:%S.%f"]
    for fmt in formatos:
        try:
            return datetime.strptime(str(h), fmt).time()
        except:
            continue

    logging.error(f"Hora inválida não convertida: {h}")
    return None

def calcular_total(caruru, bobo, desconto):
    """Centraliza o cálculo financeiro"""
    try:
        preco_base = 70.0
        total = (float(caruru) * preco_base) + (float(bobo) * preco_base)
        if desconto > 0:
            total = total * (1 - (float(desconto)/100))
        return round(total, 2)
    except Exception as e:
        logging.error(f"Erro no cálculo: {e}")
        return 0.0

# --- 3. BANCO DE DADOS (DB_UTILS) ---

def carregar_pedidos():
    """Carregamento robusto e tipado dos dados"""
    colunas = ["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]

    if not os.path.exists(ARQUIVO_PEDIDOS):
        return pd.DataFrame(columns=colunas)

    try:
        df = pd.read_csv(ARQUIVO_PEDIDOS)

        # Garante colunas obrigatórias
        for c in colunas:
            if c not in df.columns:
                df[c] = None

        # Conversões e Limpezas
        df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.date
        df["Hora"] = df["Hora"].apply(limpar_hora_rigoroso)
        
        # Numéricos
        for col in ["Caruru", "Bobo", "Desconto", "Valor"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

        # ID do Pedido
        df['ID_Pedido'] = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
        
        # Se houver IDs duplicados ou zerados, regenera sequencialmente
        if df['ID_Pedido'].duplicated().any() or df['ID_Pedido'].max() == 0:
            df['ID_Pedido'] = range(1, len(df) + 1)

        # Textos (Evita "nan" string)
        cols_txt = ["Cliente", "Status", "Pagamento", "Contato", "Observacoes"]
        for col in cols_txt:
            df[col] = df[col].fillna("").astype(str)

        return df

    except Exception as e:
        logging.error(f"Erro crítico carregando pedidos: {e}")
        st.error("Erro ao carregar banco de dados. Verifique os logs.")
        return pd.DataFrame(columns=colunas)

def carregar_clientes():
    colunas = ["Nome", "Contato", "Observacoes"]
    if not os.path.exists(ARQUIVO_CLIENTES):
        return pd.DataFrame(columns=colunas)
    try:
        df = pd.read_csv(ARQUIVO_CLIENTES)
        for c in colunas:
            if c not in df.columns: df[c] = ""
        return df.fillna("").astype(str)
    except:
        return pd.DataFrame(columns=colunas)

def salvar_dados(df, arquivo):
    try:
        df.to_csv(arquivo, index=False)
    except Exception as e:
        logging.error(f"Erro ao salvar {arquivo}: {e}")
        st.error("Falha ao salvar dados.")

# --- 4. RELATÓRIOS E PDF (PDF_UTILS) ---

def desenhar_cabecalho(p, titulo):
    if os.path.exists("logo.png"):
        try:
            p.drawImage("logo.png", 30, 750, width=100, height=50, mask='auto', preserveAspectRatio=True)
        except: pass
    
    p.setFont("Helvetica-Bold", 16)
    p.drawString(150, 775, "Cantinho do Caruru")
    p.setFont("Helvetica", 10)
    p.drawString(150, 760, "Comprovante de Encomenda")
    p.setFont("Helvetica-Bold", 14)
    p.drawRightString(565, 765, titulo)
    p.setLineWidth(1)
    p.line(30, 740, 565, 740)

def gerar_recibo_pdf(dados):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)

        # Garante acesso seguro aos dados (mesmo se faltar coluna)
        id_ped = dados.get("ID_Pedido", "UNK")
        desenhar_cabecalho(p, f"Pedido #{id_ped}")

        y = 700
        # Dados do Cliente
        p.setFont("Helvetica-Bold", 12); p.drawString(30, y, "DADOS DO CLIENTE"); y -= 20
        p.setFont("Helvetica", 12)
        p.drawString(30, y, f"Nome: {dados.get('Cliente', '')}")
        p.drawString(300, y, f"WhatsApp: {dados.get('Contato', '')}")
        y -= 20
        
        # Data
        data_val = dados.get('Data')
        data_str = data_val.strftime('%d/%m/%Y') if hasattr(data_val, 'strftime') else str(data_val)
        hora_val = dados.get('Hora')
        hora_str = str(hora_val)[:5] if hora_val else "--:--"
        
        p.drawString(30, y, f"Data de Entrega: {data_str}")
        p.drawString(300, y, f"Horário: {hora_str}")
        
        # Tabela
        y -= 40
        p.setFillColor(colors.lightgrey)
        p.rect(30, y-5, 535, 20, fill=1, stroke=0)
        p.setFillColor(colors.black)
        p.setFont("Helvetica-Bold", 10)
        p.drawString(40, y, "ITEM"); p.drawString(400, y, "QTD")
        
        y -= 25
        p.setFont("Helvetica", 10)
        itens = {"Caruru Tradicional": dados.get("Caruru", 0), "Bobó de Camarão": dados.get("Bobo", 0)}
        
        for nome, qtd in itens.items():
            if qtd > 0:
                p.drawString(40, y, nome)
                p.drawString(400, y, str(int(qtd)))
                y -= 15
        
        p.line(30, y-5, 565, y-5)
        
        # Total
        y -= 40
        p.setFont("Helvetica-Bold", 14)
        pgto = dados.get("Pagamento", "")
        rotulo = "TOTAL PAGO" if pgto == "PAGO" else "VALOR A PAGAR"
        p.drawString(350, y, f"{rotulo}: R$ {dados.get('Valor', 0):.2f}")
        
        # Status
        y -= 25
        p.setFont("Helvetica-Bold", 12)
        if pgto == "PAGO":
            p.setFillColor(colors.green); p.drawString(30, y+25, "SITUAÇÃO: PAGO ✅")
        else:
            p.setFillColor(colors.red); p.drawString(30, y+25, "SITUAÇÃO: PENDENTE ❌")
            p.setFillColor(colors.black); p.setFont("Helvetica", 10)
            p.drawString(30, y, f"Chave PIX: {CHAVE_PIX}")
            
        # Obs
        p.setFillColor(colors.black)
        obs = str(dados.get("Observacoes", ""))
        if obs and obs != "nan":
            y -= 30; p.setFont("Helvetica-Oblique", 10); p.drawString(30, y, f"Obs: {obs}")
            
        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        logging.error(f"Erro PDF Recibo: {e}")
        return None

def gerar_relatorio_pdf(df, titulo):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        y = 700
        desenhar_cabecalho(p, titulo)
        
        # Cabeçalho Tabela
        p.setFont("Helvetica-Bold", 9)
        cols = [("ID", 30), ("Data", 60), ("Cliente", 110), ("Caruru", 230), ("Bobó", 270), ("Valor", 320), ("Status", 380), ("Pagto", 470)]
        for nome, pos in cols: p.drawString(pos, y, nome)
        y -= 20; p.setFont("Helvetica", 9)
        
        total = 0
        for _, row in df.iterrows():
            if y < 50: p.showPage(); desenhar_cabecalho(p, titulo); y = 700
            
            d_str = row['Data'].strftime('%d/%m') if hasattr(row['Data'], 'strftime') else ""
            st_clean = str(row['Status']).replace("🔴", "").replace("✅", "").replace("🟡", "").strip()[:10]
            
            p.drawString(30, y, str(row.get('ID_Pedido', '-')))
            p.drawString(60, y, d_str)
            p.drawString(110, y, str(row['Cliente'])[:18])
            p.drawString(230, y, str(int(row['Caruru'])))
            p.drawString(270, y, str(int(row['Bobo'])))
            p.drawString(320, y, f"{row['Valor']:.2f}")
            p.drawString(380, y, st_clean)
            p.drawString(470, y, str(row['Pagamento']))
            
            total += row['Valor']
            y -= 15
            
        p.line(30, y, 565, y)
        p.setFont("Helvetica-Bold", 11)
        p.drawString(320, y-20, f"TOTAL: R$ {total:,.2f}")
        
        p.showPage(); p.save(); buffer.seek(0)
        return buffer
    except Exception as e:
        logging.error(f"Erro PDF Relatorio: {e}")
        return None

# --- 5. LÓGICA PRINCIPAL (APP) ---

# Inicialização
if 'pedidos' not in st.session_state:
    st.session_state.pedidos = carregar_pedidos()
if 'clientes' not in st.session_state:
    st.session_state.clientes = carregar_clientes()

# CSS
st.markdown("""<style>
    .metric-card {background-color: #f9f9f9; border-left: 5px solid #ff4b4b; padding: 10px; border-radius: 5px;}
    .stButton>button {width: 100%; border-radius: 12px; font-weight: bold; height: 50px;}
</style>""", unsafe_allow_html=True)

# --- MENU ---
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=250)
    else: st.title("🦐 Cantinho do Caruru")
    st.divider()
    menu = st.radio("Navegação", ["Dashboard", "Novo Pedido", "Gerenciar", "Relatórios", "Clientes", "Admin"])
    st.divider()
    st.caption("Sistema v9.0 (Professional Core)")

# --- PÁGINAS ---

if menu == "Dashboard":
    st.title("🦐🏍️ Expedição do Dia")
    df = st.session_state.pedidos
    
    if df.empty:
        st.info("Nenhum pedido registrado.")
    else:
        # Filtro Data
        dt_filter = st.date_input("Data:", date.today(), format="DD/MM/YYYY")
        df_dia = df[df['Data'] == dt_filter].copy()
        
        # Ordenação Segura
        try:
            df_dia['h_sort'] = df_dia['Hora'].apply(lambda x: x if x else time(23,59))
            df_dia = df_dia.sort_values('h_sort')
        except: pass
        
        # Métricas
        c1, c2, c3, c4 = st.columns(4)
        pend = df_dia[~df_dia['Status'].str.contains("Entregue", na=False)]
        
        c1.metric("Caruru (Pend)", int(pend['Caruru'].sum()))
        c2.metric("Bobó (Pend)", int(pend['Bobo'].sum()))
        c3.metric("Faturamento", f"R$ {df_dia['Valor'].sum():,.2f}")
        
        receber = df_dia[df_dia['Pagamento'] != 'PAGO']['Valor'].sum()
        c4.metric("A Receber", f"R$ {receber:,.2f}", delta_color="inverse")
        
        st.divider()
        st.subheader("📋 Lista de Entrega")
        
        if not df_dia.empty:
            # Editor
            edited = st.data_editor(
                df_dia,
                column_order=["ID_Pedido", "Hora", "Status", "Cliente", "Caruru", "Bobo", "Valor", "Pagamento", "Observacoes"],
                disabled=["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Hora"],
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                    "Hora": st.column_config.TimeColumn(format="HH:mm"),
                    "Valor": st.column_config.NumberColumn(format="R$ %.2f")
                }
            )
            
            # Salvar se houve mudança
            if not edited.equals(df_dia):
                df.update(edited)
                st.session_state.pedidos = df
                salvar_dados(df, ARQUIVO_PEDIDOS)
                st.toast("Status Atualizado!", icon="✅")
                tm.sleep(0.5)
                st.rerun()

elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    
    # Lista Clientes
    try: clientes = sorted(st.session_state.clientes['Nome'].unique())
    except: clientes = []
    
    st.markdown("### 1. Cliente")
    c1, c2 = st.columns([3, 1])
    
    # Callback para atualizar contato
    def update_contato():
        sel = st.session_state.get("sel_cli")
        if sel:
            res = st.session_state.clientes[st.session_state.clientes['Nome'] == sel]
            if not res.empty:
                st.session_state["auto_contato"] = res.iloc[0]['Contato']
            else: st.session_state["auto_contato"] = ""
            
    with c1:
        cli_sel = st.selectbox("Nome", [""] + clientes, key="sel_cli", on_change=update_contato)
    with c2:
        hora_ent = st.time_input("Hora", value=time(12,0))
        
    st.markdown("### 2. Dados")
    with st.form("form_novo", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1: cont = st.text_input("WhatsApp", key="auto_contato")
        with c2: dt = st.date_input("Data", min_value=date.today(), format="DD/MM/YYYY")
        
        c3, c4, c5 = st.columns(3)
        with c3: qtd_c = st.number_input("Caruru", 0.0, step=1.0)
        with c4: qtd_b = st.number_input("Bobó", 0.0, step=1.0)
        with c5: desc = st.number_input("Desc %", 0, 100)
        
        obs = st.text_area("Obs")
        c6, c7 = st.columns(2)
        with c6: pgto = st.selectbox("Pagto", OPCOES_PAGAMENTO)
        with c7: stat = st.selectbox("Status", OPCOES_STATUS)
        
        if st.form_submit_button("💾 SALVAR"):
            if not cli_sel:
                st.error("Selecione um cliente.")
            else:
                try:
                    # Gera ID Seguro
                    df_p = st.session_state.pedidos
                    novo_id = 1 if df_p.empty else df_p['ID_Pedido'].max() + 1
                    
                    val = calcular_total(qtd_c, qtd_b, desc)
                    
                    novo = {
                        "ID_Pedido": novo_id,
                        "Cliente": cli_sel, "Caruru": qtd_c, "Bobo": qtd_b, "Valor": val,
                        "Data": dt, "Hora": hora_ent, "Status": stat, "Pagamento": pgto,
                        "Contato": cont, "Desconto": desc, "Observacoes": obs
                    }
                    
                    # Salvar
                    df_novo = pd.DataFrame([novo])
                    # Garante conversão de data/hora antes de concatenar
                    df_novo['Data'] = pd.to_datetime(df_novo['Data']).dt.date
                    
                    st.session_state.pedidos = pd.concat([df_p, df_novo], ignore_index=True)
                    salvar_dados(st.session_state.pedidos, ARQUIVO_PEDIDOS)
                    
                    st.success(f"Pedido #{novo_id} criado!")
                    tm.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    logging.error(f"Erro novo pedido: {e}")
                    st.error("Erro ao salvar. Tente novamente.")

elif menu == "Gerenciar":
    st.title("📦 Todos os Pedidos")
    df = st.session_state.pedidos
    
    if not df.empty:
        # Ordenação
        try:
            df['sort'] = df['Hora'].apply(lambda x: x if x else time(0,0))
            df = df.sort_values(['Data', 'sort']).drop(columns=['sort'])
        except: pass
        
        # Editor
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
        
        # Salvar Edições
        if not edited.equals(df):
            # Recalcula valores se quantidades mudaram
            try:
                base = 70.0
                edited['Valor'] = ((edited['Caruru'] * base) + (edited['Bobo'] * base)) * (1 - (edited['Desconto']/100))
                
                st.session_state.pedidos = edited
                salvar_dados(edited, ARQUIVO_PEDIDOS)
                st.toast("Salvo!", icon="💾")
                tm.sleep(0.5)
                st.rerun()
            except Exception as e:
                st.error("Erro ao salvar edição.")
                logging.error(f"Erro edição: {e}")

elif menu == "Relatórios":
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
                sel_id = st.selectbox("Selecione:", options=opc.keys(), format_func=lambda x: opc[x])
                
                if st.button("📄 Gerar PDF"):
                    pdf = gerar_recibo_pdf(peds.loc[sel_id])
                    if pdf: st.download_button("Baixar", pdf, f"Recibo_{cli}.pdf", "application/pdf")
                    else: st.error("Erro ao gerar PDF.")
    
    with t2:
        tipo = st.radio("Filtro:", ["Dia Específico", "Tudo"])
        if tipo == "Dia Específico":
            dt = st.date_input("Data:", date.today(), format="DD/MM/YYYY")
            df_rel = df[df['Data'] == dt]
            nome = f"Relatorio_{dt}.pdf"
        else:
            df_rel = df
            nome = "Relatorio_Geral.pdf"
            
        st.write(f"Linhas: {len(df_rel)}")
        if not df_rel.empty:
            if st.button("📊 Gerar Relatório"):
                pdf = gerar_relatorio_pdf(df_rel, nome.replace(".pdf", ""))
                if pdf: st.download_button("Baixar PDF", pdf, nome, "application/pdf")

elif menu == "Clientes":
    st.title("👥 Base de Clientes")
    t1, t2 = st.tabs(["Cadastro", "Excluir"])
    
    with t1:
        with st.form("cli_form", clear_on_submit=True):
            n = st.text_input("Nome")
            z = st.text_input("Zap")
            o = st.text_area("Obs")
            if st.form_submit_button("Salvar") and n:
                novo = pd.DataFrame([{"Nome": n, "Contato": z, "Observacoes": o}])
                st.session_state.clientes = pd.concat([st.session_state.clientes, novo], ignore_index=True)
                salvar_dados(st.session_state.clientes, ARQUIVO_CLIENTES)
                st.success("Cadastrado!")
                st.rerun()
        
        if not st.session_state.clientes.empty:
            edited = st.data_editor(st.session_state.clientes, num_rows="dynamic", use_container_width=True, hide_index=True)
            if not edited.equals(st.session_state.clientes):
                st.session_state.clientes = edited
                salvar_dados(edited, ARQUIVO_CLIENTES)
                st.toast("Salvo!")
    
    with t2:
        l = st.session_state.clientes['Nome'].unique()
        d = st.selectbox("Excluir quem?", l)
        if st.button("Confirmar Exclusão"):
            st.session_state.clientes = st.session_state.clientes[st.session_state.clientes['Nome'] != d]
            salvar_dados(st.session_state.clientes, ARQUIVO_CLIENTES)
            st.rerun()

elif menu == "Admin":
    st.title("🛠️ Admin & Segurança")
    
    # Logs
    if os.path.exists(ARQUIVO_LOG):
        with open(ARQUIVO_LOG, "r") as f: log = f.read()
        with st.expander("Ver Logs de Erro"):
            st.text_area("", log)
            if st.button("Limpar Logs"):
                open(ARQUIVO_LOG, 'w').close()
                st.rerun()
                
    st.divider()
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("📦 Backup Geral")
        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED, False) as z:
                z.writestr("pedidos.csv", st.session_state.pedidos.to_csv(index=False))
                z.writestr("clientes.csv", st.session_state.clientes.to_csv(index=False))
            st.download_button("Baixar ZIP", buf.getvalue(), f"Backup_{date.today()}.zip", "application/zip")
        except: st.error("Erro backup.")
        
    with c2:
        st.subheader("⚠️ Restauração")
        up_ped = st.file_uploader("Restaurar Pedidos (CSV)", type="csv")
        if up_ped and st.button("Restaurar P"):
            try:
                df_n = pd.read_csv(up_ped)
                salvar_dados(df_n, ARQUIVO_PEDIDOS)
                st.session_state.pedidos = carregar_pedidos() # Passa pelo limpador
                st.success("OK!")
                tm.sleep(1)
                st.rerun()
            except: st.error("Erro.")
            
        up_cli = st.file_uploader("Restaurar Clientes (CSV)", type="csv")
        if up_cli and st.button("Restaurar C"):
            try:
                df_c = pd.read_csv(up_cli)
                salvar_dados(df_c, ARQUIVO_CLIENTES)
                st.session_state.clientes = carregar_clientes()
                st.success("OK!")
                tm.sleep(1)
                st.rerun()
            except: st.error("Erro.")
