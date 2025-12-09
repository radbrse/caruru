import streamlit as st
import pandas as pd
from datetime import date, datetime, time
import os
import io
import zipfile
import time as tm
import logging
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

# --- CONFIGURAÇÃO DE LOGS ---
ARQUIVO_LOG = "system_errors.log"
logging.basicConfig(filename=ARQUIVO_LOG, level=logging.ERROR, format='%(asctime)s - %(message)s', force=True)

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Cantinho do Caruru", page_icon="🦐", layout="wide")

# Arquivos
ARQUIVO_PEDIDOS = "banco_de_dados_caruru.csv"
ARQUIVO_CLIENTES = "banco_de_dados_clientes.csv"
CHAVE_PIX = "79999296722"

# Opções
OPCOES_STATUS = ["🔴 Pendente", "🟡 Em Produção", "✅ Entregue", "🚫 Cancelado"]
OPCOES_PAGAMENTO = ["PAGO", "NÃO PAGO", "METADE"]

# --- FUNÇÃO DE LIMPEZA DE DADOS (O CORAÇÃO DA CORREÇÃO) ---
def limpar_dataframe_pedidos(df):
    """
    Esta função pega qualquer bagunça no CSV e padroniza para o formato 
    que o Streamlit exige, evitando o erro de compatibilidade.
    """
    colunas_padrao = ["Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]
    
    # 1. Garante colunas
    for col in colunas_padrao:
        if col not in df.columns: df[col] = None
        
    # 2. Numéricos (Força zero se der erro)
    for col in ['Caruru', 'Bobo', 'Desconto', 'Valor']:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        
    # 3. Textos (Força string vazia se for nulo)
    for col in ['Cliente', 'Status', 'Pagamento', 'Contato', 'Observacoes']:
        df[col] = df[col].astype(str).replace('nan', '').replace('None', '')

    # 4. Data (Força objeto Date)
    df['Data'] = pd.to_datetime(df['Data'], errors='coerce').dt.date
    
    # 5. HORA (CORREÇÃO CRÍTICA)
    def forcar_relogio(valor):
        if pd.isna(valor) or str(valor).strip() == "" or str(valor).lower() in ["nan", "none", "nat"]:
            return None
        
        # Se já for relógio, retorna
        if isinstance(valor, time):
            return valor
            
        # Se for datetime completo, pega só a hora
        if isinstance(valor, datetime):
            return valor.time()
            
        # Tenta converter texto
        valor_str = str(valor).strip()
        try: return datetime.strptime(valor_str, "%H:%M:%S").time()
        except:
            try: return datetime.strptime(valor_str, "%H:%M").time()
            except: return None # Desiste e retorna vazio (não trava)

    df['Hora'] = df['Hora'].apply(forcar_relogio)
    
    # 6. Status e Pagamento (Validação)
    # Se o status não for um dos oficiais, vira Pendente (evita erro de selectbox)
    df.loc[~df['Status'].isin(OPCOES_STATUS), 'Status'] = "🔴 Pendente"
    df.loc[~df['Pagamento'].isin(OPCOES_PAGAMENTO), 'Pagamento'] = "NÃO PAGO"
    
    return df[colunas_padrao] # Retorna apenas as colunas certas na ordem certa

# --- CARREGAMENTO ---
def carregar_clientes():
    colunas = ["Nome", "Contato", "Observacoes"]
    if os.path.exists(ARQUIVO_CLIENTES):
        try:
            df = pd.read_csv(ARQUIVO_CLIENTES)
            for col in colunas:
                if col not in df.columns: df[col] = ""
            df['Nome'] = df['Nome'].astype(str)
            df['Contato'] = df['Contato'].astype(str).replace('nan', '')
            df['Observacoes'] = df['Observacoes'].astype(str).replace('nan', '')
            return df
        except: return pd.DataFrame(columns=colunas)
    else: return pd.DataFrame(columns=colunas)

def carregar_pedidos():
    if os.path.exists(ARQUIVO_PEDIDOS):
        try:
            df = pd.read_csv(ARQUIVO_PEDIDOS)
            # Passa pela limpeza rigorosa antes de devolver
            return limpar_dataframe_pedidos(df)
        except Exception as e:
            logging.error(f"Erro ao ler CSV: {e}")
            return limpar_dataframe_pedidos(pd.DataFrame())
    else:
        return limpar_dataframe_pedidos(pd.DataFrame())

def salvar_pedidos(df):
    try: df.to_csv(ARQUIVO_PEDIDOS, index=False)
    except Exception as e: logging.error(f"Erro salvar pedidos: {e}")

def salvar_clientes(df):
    try: df.to_csv(ARQUIVO_CLIENTES, index=False)
    except Exception as e: logging.error(f"Erro salvar clientes: {e}")

def calcular_total(caruru, bobo, desconto):
    try:
        preco_base = 70.0
        total = (caruru * preco_base) + (bobo * preco_base)
        if desconto > 0:
            total = total * (1 - (desconto/100))
        return total
    except: return 0.0

def atualizar_contato_novo_pedido():
    try:
        c_at = st.session_state.get('chave_cliente_selecionado')
        if c_at:
            busca = st.session_state.clientes[st.session_state.clientes['Nome'] == c_at]
            if not busca.empty: st.session_state['chave_contato_automatico'] = busca.iloc[0]['Contato']
            else: st.session_state['chave_contato_automatico'] = ""
        else: st.session_state['chave_contato_automatico'] = ""
    except: pass

# --- FUNÇÕES PDF ---
def desenhar_cabecalho(p, titulo):
    if os.path.exists("logo.png"):
        try: p.drawImage("logo.png", 30, 750, width=100, height=50, mask='auto', preserveAspectRatio=True)
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
        desenhar_cabecalho(p, f"Pedido #{str(int(dados.name) if isinstance(dados.name, int) else 'UNK')}")
        y = 700
        p.setFont("Helvetica-Bold", 12)
        p.drawString(30, y, "DADOS DO CLIENTE")
        y -= 20
        p.setFont("Helvetica", 12)
        p.drawString(30, y, f"Nome: {dados['Cliente']}")
        p.drawString(300, y, f"WhatsApp: {dados['Contato']}")
        y -= 20
        data_str = dados['Data'].strftime('%d/%m/%Y') if hasattr(dados['Data'], 'strftime') else str(dados['Data'])
        try: hora_str = str(dados['Hora'])[:5]
        except: hora_str = "--:--"
        p.drawString(30, y, f"Data de Entrega: {data_str}")
        p.drawString(300, y, f"Horário: {hora_str}")
        y -= 40
        p.setFillColor(colors.lightgrey)
        p.rect(30, y-5, 535, 20, fill=1, stroke=0)
        p.setFillColor(colors.black)
        p.setFont("Helvetica-Bold", 10)
        p.drawString(40, y, "ITEM")
        p.drawString(400, y, "QUANTIDADE")
        y -= 25
        p.setFont("Helvetica", 10)
        if dados['Caruru'] > 0:
            p.drawString(40, y, "Caruru Tradicional (Kg/Unid)")
            p.drawString(400, y, f"{int(dados['Caruru'])}")
            y -= 15
        if dados['Bobo'] > 0:
            p.drawString(40, y, "Bobó de Camarão (Kg/Unid)")
            p.drawString(400, y, f"{int(dados['Bobo'])}")
            y -= 15
        p.line(30, y-5, 565, y-5)
        y -= 40
        p.setFont("Helvetica-Bold", 14)
        rotulo = "TOTAL PAGO" if dados['Pagamento'] == "PAGO" else "VALOR A PAGAR"
        p.drawString(350, y, f"{rotulo}: R$ {dados['Valor']:.2f}")
        y -= 25
        p.setFont("Helvetica-Bold", 12)
        if dados['Pagamento'] == "PAGO":
            p.setFillColor(colors.green)
            p.drawString(30, y+25, "SITUAÇÃO: PAGO ✅")
        elif dados['Pagamento'] == "METADE":
            p.setFillColor(colors.orange)
            p.drawString(30, y+25, "SITUAÇÃO: PARCIAL (50%) ⚠️")
            p.setFillColor(colors.black)
            p.setFont("Helvetica", 10)
            p.drawString(30, y, f"Chave PIX: {CHAVE_PIX}")
        else:
            p.setFillColor(colors.red)
            p.drawString(30, y+25, "SITUAÇÃO: NÃO PAGO ❌")
            p.setFillColor(colors.black)
            p.setFont("Helvetica", 10)
            p.drawString(30, y, f"Chave PIX: {CHAVE_PIX}")
        p.setFillColor(colors.black)
        if dados['Observacoes'] and dados['Observacoes'] != "nan":
            y -= 30
            p.setFont("Helvetica-Oblique", 10)
            p.drawString(30, y, f"Obs: {dados['Observacoes']}")
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
    except: return None

def gerar_relatorio_pdf(df_filtrado, titulo_relatorio):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        y = 700
        desenhar_cabecalho(p, titulo_relatorio)
        p.setFont("Helvetica-Bold", 10)
        p.drawString(30, y, "Data")
        p.drawString(90, y, "Cliente")
        p.drawString(230, y, "Caruru")
        p.drawString(280, y, "Bobó")
        p.drawString(330, y, "Valor")
        p.drawString(400, y, "Status")
        p.drawString(480, y, "Pagto")
        y -= 20
        p.setFont("Helvetica", 9)
        total_valor = 0
        for index, row in df_filtrado.iterrows():
            if y < 50:
                p.showPage()
                desenhar_cabecalho(p, titulo_relatorio)
                y = 700
            data_str = row['Data'].strftime('%d/%m') if hasattr(row['Data'], 'strftime') else str(row['Data'])
            p.drawString(30, y, data_str)
            p.drawString(90, y, str(row['Cliente'])[:20])
            p.drawString(230, y, str(int(row['Caruru'])))
            p.drawString(280, y, str(int(row['Bobo'])))
            p.drawString(330, y, f"R$ {row['Valor']:.2f}")
            status_clean = row['Status'].replace("✅ ", "").replace("🔴 ", "").replace("🟡 ", "").replace("🚫 ", "")
            p.drawString(400, y, status_clean[:12])
            p.drawString(480, y, row['Pagamento'])
            total_valor += row['Valor']
            y -= 15
        p.line(30, y, 565, y)
        y -= 20
        p.setFont("Helvetica-Bold", 11)
        p.drawString(30, y, f"TOTAL GERAL: R$ {total_valor:,.2f}")
        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except: return None

# Inicializa Sessão
if 'pedidos' not in st.session_state:
    st.session_state.pedidos = carregar_pedidos()
if 'clientes' not in st.session_state:
    st.session_state.clientes = carregar_clientes()

# CSS
st.markdown("""
<style>
    .metric-card {background-color: #f9f9f9; border-left: 5px solid #ff4b4b; padding: 10px; border-radius: 5px;}
    .stButton>button {width: 100%; border-radius: 12px; font-weight: bold; height: 50px;}
</style>
""", unsafe_allow_html=True)

# --- MENU ---
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=250)
    else: st.title("🦐 Cantinho do Caruru")
    st.divider()
    menu = st.radio("Ir para:", ["Dashboard do Dia", "Novo Pedido", "Gerenciar Tudo", "🖨️ Relatórios & Recibos", "👥 Cadastrar Clientes", "🛠️ Manutenção"])
    st.divider()
    st.caption("Sistema Online v7.0")

# --- DASHBOARD ---
if menu == "Dashboard do Dia":
    st.title("🚚 Expedição do Dia")
    df = st.session_state.pedidos
    if df.empty: st.info("Sem dados.")
    else:
        data_analise = st.date_input("📅 Data:", date.today(), format="DD/MM/YYYY")
        df_dia = df[df['Data'] == data_analise].copy()
        
        try:
            df_dia['Hora_Temp'] = df_dia['Hora'].apply(lambda x: x if x is not None else time(23,59))
            df_dia = df_dia.sort_values(by="Hora_Temp").drop(columns=['Hora_Temp'])
        except: pass
        
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
                    column_order=["Hora", "Status", "Cliente", "Caruru", "Bobo", "Valor", "Pagamento", "Observacoes"],
                    disabled=["Cliente", "Caruru", "Bobo", "Valor", "Hora"], 
                    hide_index=True, use_container_width=True, key="dash_edit",
                    column_config={
                        "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                        "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                        "Hora": st.column_config.TimeColumn(format="HH:mm"),
                    }
                )
                if not df_baixa.equals(df_dia):
                    # Salva
                    df.update(df_baixa)
                    st.session_state.pedidos = df
                    salvar_pedidos(df)
                    st.toast("Atualizado!", icon="✅")
                    tm.sleep(0.5)
                    st.rerun()
            except Exception as e:
                st.error("Erro visual. Dados seguros.")
                logging.error(f"Erro Dash: {e}")

# --- NOVO PEDIDO ---
elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    try: lista_cli = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
    except: lista_cli = []
    
    st.markdown("### 1. Identificação")
    c1, c2 = st.columns([3,1])
    with c1: nome_sel = st.selectbox("Cliente", [""]+lista_cli, key="chave_cliente_selecionado", on_change=atualizar_contato_novo_pedido)
    with c2: hora_ent = st.time_input("Hora", value=time(12, 0))
    
    st.markdown("### 2. Detalhes")
    with st.form("form_pedido", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1: cont = st.text_input("WhatsApp", key="chave_contato_automatico")
        with c2: dt_ent = st.date_input("Data", min_value=date.today(), format="DD/MM/YYYY")
        c3, c4, c5 = st.columns(3)
        with c3: caruru = st.number_input("Caruru", 0.0, step=1.0)
        with c4: bobo = st.number_input("Bobó", 0.0, step=1.0)
        with c5: desc = st.number_input("Desc %", 0, 100)
        obs = st.text_area("Obs")
        c6, c7 = st.columns(2)
        with c6: pgto = st.selectbox("Pagto", OPCOES_PAGAMENTO)
        with c7: status = st.selectbox("Status", OPCOES_STATUS)
        
        if st.form_submit_button("💾 SALVAR"):
            cli_final = st.session_state.chave_cliente_selecionado
            if not cli_final: st.error("Selecione um cliente.")
            else:
                try:
                    val = calcular_total(caruru, bobo, desc)
                    # SALVA HORA COMO STRING HH:MM PARA CSV
                    h_str = hora_ent.strftime("%H:%M")
                    
                    novo = {"Cliente": cli_final, "Caruru": caruru, "Bobo": bobo, "Valor": val, "Data": dt_ent, "Hora": h_str, "Status": status, "Pagamento": pgto, "Contato": cont, "Desconto": desc, "Observacoes": obs}
                    df_novo = pd.DataFrame([novo])
                    df_novo['Data'] = pd.to_datetime(df_novo['Data']).dt.date
                    
                    # Concatena
                    st.session_state.pedidos = pd.concat([st.session_state.pedidos, df_novo], ignore_index=True)
                    
                    # SALVA O CSV BRUTO
                    salvar_pedidos(st.session_state.pedidos)
                    
                    # RECARREGA VIA FUNÇÃO DE LIMPEZA PARA GARANTIR TIPOS
                    st.session_state.pedidos = carregar_pedidos()
                    
                    st.success("Salvo!")
                    st.session_state['chave_contato_automatico'] = ""
                    tm.sleep(0.5)
                    st.rerun()
                except Exception as e:
                    st.error("Erro ao salvar.")
                    logging.error(f"Erro Novo Pedido: {e}")

# --- GERENCIAR TUDO ---
elif menu == "Gerenciar Tudo":
    st.title("📦 Todos os Pedidos")
    df = st.session_state.pedidos
    
    if not df.empty:
        try:
            df['Hora_Temp'] = df['Hora'].apply(lambda x: x if x is not None else time(0,0))
            df = df.sort_values(by=["Data", "Hora_Temp"], ascending=[True, True]).drop(columns=['Hora_Temp'])
        except: df = df.sort_values(by="Data")
        
        try:
            df_editado = st.data_editor(
                df,
                num_rows="dynamic", use_container_width=True, hide_index=True,
                column_config={
                    "Valor": st.column_config.NumberColumn("Total", format="R$ %.2f", disabled=True),
                    "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                    # COLUNA HORA AGORA É SEGURA
                    "Hora": st.column_config.TimeColumn("Hora", format="HH:mm"),
                    "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                    "Pagamento": st.column_config.SelectboxColumn(options=OPCOES_PAGAMENTO, required=True),
                    "Caruru": st.column_config.NumberColumn(format="%d"),
                    "Bobo": st.column_config.NumberColumn(format="%d"),
                }
            )
            
            if not df_editado.equals(df):
                preco = 70.0
                df_editado['Valor'] = ((df_editado['Caruru'] * preco) + (df_editado['Bobo'] * preco)) * (1 - (df_editado['Desconto'] / 100))
                st.session_state.pedidos = df_editado
                salvar_pedidos(df_editado)
                st.toast("Salvo!", icon="💾")
                tm.sleep(0.5)
                st.rerun()
        except Exception as e:
            st.error(f"Erro de visualização. O banco de dados foi limpo mas algo persiste.")
            logging.error(f"Erro Table Editor: {e}")
            
        st.divider()
        try:
            cli_unicos = sorted(df['Cliente'].unique())
            sel = st.selectbox("Cliente:", cli_unicos)
            if sel:
                d = df[df['Cliente'] == sel].iloc[-1]
                t = str(d['Contato']).replace(".0", "").replace(" ", "").replace("-", "")
                dt = d['Data'].strftime('%d/%m') if hasattr(d['Data'], 'strftime') else str(d['Data'])
                try: hr = d['Hora'].strftime('%H:%M')
                except: hr = str(d['Hora'])
                msg = f"Olá {sel}, pedido confirmado!\n🗓 {dt} às {hr}\n📦 {int(d['Caruru'])} Caruru, {int(d['Bobo'])} Bobó\n💰 R$ {d['Valor']:.2f}"
                if d['Pagamento'] in ["NÃO PAGO", "METADE"]: msg += f"\n🔑 Pix: {CHAVE_PIX}"
                lnk = f"https://wa.me/55{t}?text={msg.replace(' ', '%20').replace(chr(10), '%0A')}"
                st.link_button("Enviar Zap", lnk)
        except: pass
    
    st.divider()
    with st.expander("💾 Segurança (Backup & Restaurar)"):
        st.write("### 1. Fazer Backup")
        try:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
                zip_file.writestr("pedidos.csv", df.to_csv(index=False))
                zip_file.writestr("clientes.csv", st.session_state.clientes.to_csv(index=False))
            st.download_button("📥 Baixar Tudo (ZIP)", zip_buffer.getvalue(), f"backup_{date.today()}.zip", "application/zip")
        except: st.error("Erro.")
        
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            st.write("⚠️ **Restaurar Pedidos**")
            up = st.file_uploader("Arquivo Pedidos (CSV):", type=["csv"], key="res_ped_man")
            if up and st.button("Restaurar P"):
                try:
                    # Lê o CSV bruto
                    df_new = pd.read_csv(up)
                    # Passa pelo LIMPADOR RIGOROSO
                    df_clean = limpar_dataframe_pedidos(df_new)
                    # Salva
                    salvar_pedidos(df_clean)
                    # Recarrega
                    st.session_state.pedidos = carregar_pedidos()
                    st.success("OK! Tabela corrigida e restaurada.")
                    tm.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")
        
        with col_r2:
            st.write("👥 **Restaurar Clientes**")
            up_cli = st.file_uploader("Arquivo Clientes (CSV):", type=["csv"], key="res_cli_man")
            if up_cli and st.button("Restaurar C"):
                try:
                    df_new = pd.read_csv(up_cli)
                    salvar_clientes(df_new)
                    st.session_state.clientes = carregar_clientes()
                    st.success("OK!")
                    st.rerun()
                except: st.error("Erro.")

# --- RECIBOS ---
elif menu == "🖨️ Relatórios & Recibos":
    st.title("🖨️ Impressão")
    t1, t2 = st.tabs(["Recibo", "Relatório"])
    df = st.session_state.pedidos
    with t1:
        if df.empty: st.info("Sem dados.")
        else:
            cli = st.selectbox("Cliente:", sorted(df['Cliente'].unique()))
            ped_cli = df[df['Cliente'] == cli].sort_values(by="Data", ascending=False)
            if not ped_cli.empty:
                opc = {i: f"{p['Data']} - R$ {p['Valor']}" for i, p in ped_cli.iterrows()}
                id_p = st.selectbox("Pedido:", options=opc.keys(), format_func=lambda x: opc[x])
                if st.button("Gerar Recibo"):
                    pdf = gerar_recibo_pdf(ped_cli.loc[id_p])
                    if pdf: st.download_button("Baixar PDF", pdf, f"Recibo_{cli}.pdf", "application/pdf")
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
                if pdf: st.download_button("Baixar Relatório", pdf, "relatorio.pdf", "application/pdf")

# --- CLIENTES ---
elif menu == "👥 Cadastrar Clientes":
    st.title("👥 Clientes")
    t1, t2 = st.tabs(["Novo", "Excluir"])
    with t1:
        with st.form("f_cli", clear_on_submit=True):
            n = st.text_input("Nome")
            z = st.text_input("Zap")
            o = st.text_area("Obs")
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
    with t2:
        l_exc = st.session_state.clientes['Nome'].unique()
        exc = st.selectbox("Excluir:", l_exc)
        if st.button("Confirmar"):
            st.session_state.clientes = st.session_state.clientes[st.session_state.clientes['Nome'] != exc]
            salvar_clientes(st.session_state.clientes)
            st.rerun()

# --- MANUTENÇÃO ---
elif menu == "🛠️ Manutenção":
    st.title("🛠️ Admin")
    st.write("Logs de Erro:")
    if os.path.exists(ARQUIVO_LOG):
        with open(ARQUIVO_LOG, "r") as f: log = f.read()
        st.text_area("Log", log, height=200)
        st.download_button("Baixar Log", log, "log.txt")
        if st.button("Limpar Log"):
            open(ARQUIVO_LOG, 'w').close()
            st.rerun()
    else: st.success("Sistema saudável.")
