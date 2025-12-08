import streamlit as st
import pandas as pd
from datetime import date, datetime, time
import os
import io
import zipfile
import numpy as np
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Cantinho do Caruru", page_icon="🦐", layout="wide")

# Arquivos
ARQUIVO_PEDIDOS = "banco_de_dados_caruru.csv"
ARQUIVO_CLIENTES = "banco_de_dados_clientes.csv"

# --- ATUALIZAÇÃO DO PIX ---
CHAVE_PIX = "79999296722"

# Opções
OPCOES_STATUS = ["🔴 Pendente", "🟡 Em Produção", "✅ Entregue", "🚫 Cancelado"]
OPCOES_PAGAMENTO = ["PAGO", "NÃO PAGO", "METADE"]

# --- FUNÇÕES DE PDF (RECIBO ATUALIZADO) ---
def desenhar_cabecalho(p, titulo):
    # LOGO NO RECIBO
    if os.path.exists("logo.png"):
        try:
            # Posição X, Y, Largura, Altura
            p.drawImage("logo.png", 30, 750, width=100, height=50, mask='auto', preserveAspectRatio=True)
        except:
            pass
    
    p.setFont("Helvetica-Bold", 16)
    p.drawString(150, 775, "Cantinho do Caruru")
    p.setFont("Helvetica", 10)
    p.drawString(150, 760, "Comprovante de Encomenda")
    
    p.setFont("Helvetica-Bold", 14)
    p.drawRightString(565, 765, titulo) # Título alinhado à direita
    
    p.setLineWidth(1)
    p.line(30, 740, 565, 740) # Linha horizontal

def gerar_recibo_pdf(dados):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    
    desenhar_cabecalho(p, f"Pedido #{str(int(dados.name) if isinstance(dados.name, int) else 'UNK')}")
    
    # --- DADOS DO CLIENTE ---
    y = 700
    p.setFont("Helvetica-Bold", 12)
    p.drawString(30, y, "DADOS DO CLIENTE")
    y -= 20
    p.setFont("Helvetica", 12)
    p.drawString(30, y, f"Nome: {dados['Cliente']}")
    p.drawString(300, y, f"WhatsApp: {dados['Contato']}")
    y -= 20
    
    # Formata data e hora
    data_str = dados['Data'].strftime('%d/%m/%Y')
    try:
        hora_str = str(dados['Hora'])[:5]
    except:
        hora_str = "--:--"
        
    p.drawString(30, y, f"Data de Entrega: {data_str}")
    p.drawString(300, y, f"Horário: {hora_str}")
    
    # --- CAIXA DO PEDIDO ---
    y -= 40
    p.setFillColor(colors.lightgrey)
    p.rect(30, y-5, 535, 20, fill=1, stroke=0) # Fundo cinza cabeçalho
    p.setFillColor(colors.black)
    p.setFont("Helvetica-Bold", 10)
    p.drawString(40, y, "ITEM")
    p.drawString(400, y, "QUANTIDADE")
    p.drawString(480, y, "TOTAL")
    
    y -= 25
    p.setFont("Helvetica", 10)
    
    # Item 1: Caruru
    if dados['Caruru'] > 0:
        p.drawString(40, y, "Caruru Tradicional (Kg/Unid)")
        p.drawString(400, y, f"{int(dados['Caruru'])}")
        y -= 15
        
    # Item 2: Bobó
    if dados['Bobo'] > 0:
        p.drawString(40, y, "Bobó de Camarão (Kg/Unid)")
        p.drawString(400, y, f"{int(dados['Bobo'])}")
        y -= 15
        
    p.line(30, y-5, 565, y-5) # Linha fim itens
    
    # --- TOTAIS E STATUS ---
    y -= 40
    p.setFont("Helvetica-Bold", 14)
    
    # LÓGICA INTELIGENTE DO RÓTULO
    rotulo_valor = "TOTAL PAGO" if dados['Pagamento'] == "PAGO" else "VALOR A PAGAR"
    
    p.drawString(350, y, f"{rotulo_valor}: R$ {dados['Valor']:.2f}")
    
    # Status Pagamento Visual
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
    
    # Observações
    p.setFillColor(colors.black)
    if dados['Observacoes'] and dados['Observacoes'] != "nan":
        y -= 30
        p.setFont("Helvetica-Oblique", 10)
        p.drawString(30, y, f"Obs: {dados['Observacoes']}")
    
    # --- ÁREA DE ASSINATURA (NOVA) ---
    y_ass = 150 # Posição fixa no fim da página
    p.setLineWidth(1)
    p.line(150, y_ass, 450, y_ass) # Linha da assinatura
    
    p.setFont("Helvetica", 10)
    p.drawCentredString(300, y_ass - 15, "Cantinho do Caruru")
    
    # Data de Emissão (Data de Hoje)
    data_hoje = datetime.now().strftime('%d/%m/%Y')
    p.setFont("Helvetica-Oblique", 8)
    p.drawCentredString(300, y_ass - 30, f"Recibo emitido em: {data_hoje}")
    
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

def gerar_relatorio_pdf(df_filtrado, titulo_relatorio):
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
    total_caruru = 0
    
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
        total_caruru += row['Caruru']
        y -= 15
        
    p.line(30, y, 565, y)
    y -= 20
    p.setFont("Helvetica-Bold", 11)
    p.drawString(30, y, f"TOTAL GERAL: R$ {total_valor:,.2f}")
    
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

# --- CARREGAMENTO E DADOS ---
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
        except:
            return pd.DataFrame(columns=colunas)
    else:
        return pd.DataFrame(columns=colunas)

def carregar_pedidos():
    colunas_padrao = ["Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]
    
    if os.path.exists(ARQUIVO_PEDIDOS):
        try:
            df = pd.read_csv(ARQUIVO_PEDIDOS)
            for col in colunas_padrao:
                if col not in df.columns: df[col] = None
            
            # Limpezas
            cols_num = ['Caruru', 'Bobo', 'Desconto', 'Valor']
            for col in cols_num:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
            
            cols_txt = ['Cliente', 'Status', 'Pagamento', 'Contato', 'Observacoes']
            for col in cols_txt:
                df[col] = df[col].astype(str).replace('nan', '')

            mapa_status = {"Pendente": "🔴 Pendente", "Em Produção": "🟡 Em Produção", "Entregue": "✅ Entregue", "Cancelado": "🚫 Cancelado"}
            df['Status'] = df['Status'].replace(mapa_status)
            
            df['Data'] = pd.to_datetime(df['Data'], errors='coerce').dt.date
            df['Data'] = df['Data'].where(pd.notnull(df['Data']), None)

            def limpar_hora_rigoroso(h):
                if pd.isna(h) or str(h).strip() == "" or str(h).lower() == "nan": return None
                if isinstance(h, time): return h
                try:
                    return pd.to_datetime(str(h), format='%H:%M').time()
                except:
                    try:
                        return pd.to_datetime(str(h), format='%H:%M:%S').time()
                    except:
                        return None

            df['Hora'] = df['Hora'].apply(limpar_hora_rigoroso)
            return df
        except:
            return pd.DataFrame(columns=colunas_padrao)
    else:
        return pd.DataFrame(columns=colunas_padrao)

def salvar_pedidos(df):
    df.to_csv(ARQUIVO_PEDIDOS, index=False)

def salvar_clientes(df):
    df.to_csv(ARQUIVO_CLIENTES, index=False)

def calcular_total(caruru, bobo, desconto):
    preco_base = 70.0
    total = (caruru * preco_base) + (bobo * preco_base)
    if desconto > 0:
        total = total * (1 - (desconto/100))
    return total

def atualizar_contato_novo_pedido():
    cliente_atual = st.session_state.get('chave_cliente_selecionado')
    if cliente_atual:
        df_cli = st.session_state.clientes
        busca = df_cli[df_cli['Nome'] == cliente_atual]
        if not busca.empty:
            st.session_state['chave_contato_automatico'] = busca.iloc[0]['Contato']
        else:
            st.session_state['chave_contato_automatico'] = ""
    else:
        st.session_state['chave_contato_automatico'] = ""

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
    if os.path.exists("logo.png"):
        st.image("logo.png", width=250)
    else:
        st.title("🦐 Cantinho do Caruru")
        
    st.divider()
    menu = st.radio("Ir para:", ["Dashboard do Dia", "Novo Pedido", "Gerenciar Tudo", "🖨️ Relatórios & Recibos", "👥 Cadastrar Clientes"])
    st.divider()
    st.caption("Sistema Online v5.1")

# =================================================================================
# DASHBOARD
# =================================================================================
if menu == "Dashboard do Dia":
    st.title("🚚 Expedição do Dia")
    
    df = st.session_state.pedidos
    
    if df.empty:
        st.info("Nenhum pedido no sistema.")
    else:
        data_analise = st.date_input("📅 Data de Entrega:", date.today(), format="DD/MM/YYYY")
        df_dia = df[df['Data'] == data_analise].copy()
        
        try:
            df_dia['Hora_Sort'] = df_dia['Hora'].apply(lambda x: x if x is not None else time(0,0))
            df_dia = df_dia.sort_values(by="Hora_Sort")
        except:
            pass
        
        col1, col2, col3, col4 = st.columns(4)
        pendentes = df_dia[df_dia['Status'] != '✅ Entregue']
        
        col1.metric("Caruru a Entregar", f"{int(pendentes['Caruru'].sum())} Unid")
        col2.metric("Bobó a Entregar", f"{int(pendentes['Bobo'].sum())} Unid")
        col3.metric("Faturamento Dia", f"R$ {df_dia['Valor'].sum():,.2f}")
        col4.metric("A Receber", f"R$ {df_dia[df_dia['Pagamento'] != 'PAGO']['Valor'].sum():,.2f}", delta_color="inverse")
        
        st.divider()
        st.subheader(f"📋 Entregas")
        
        if not df_dia.empty:
            df_baixa = st.data_editor(
                df_dia,
                column_order=["Hora", "Status", "Cliente", "Caruru", "Bobo", "Valor", "Pagamento", "Observacoes"],
                disabled=["Cliente", "Caruru", "Bobo", "Valor", "Hora"], 
                hide_index=True,
                use_container_width=True,
                key="editor_dashboard",
                column_config={
                    "Status": st.column_config.SelectboxColumn("Status", options=OPCOES_STATUS, required=True),
                    "Observacoes": st.column_config.TextColumn("Obs", width="large"),
                    "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Hora": st.column_config.TimeColumn("Hora", format="HH:mm"),
                }
            )
            
            if not df_baixa.equals(df_dia):
                df.update(df_baixa)
                st.session_state.pedidos = df
                salvar_pedidos(df)
                st.toast("Atualizado!", icon="✅")
                st.rerun()

# =================================================================================
# NOVO PEDIDO
# =================================================================================
elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    
    lista_clientes = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
    
    st.markdown("### 1. Identificação")
    col_sel, col_hora_sel = st.columns([3, 1])
    
    with col_sel:
        nome_selecionado = st.selectbox(
            "Selecione o Cliente", 
            options=[""] + lista_clientes, 
            key="chave_cliente_selecionado", 
            on_change=atualizar_contato_novo_pedido
        )
    
    with col_hora_sel:
        hora_entrega = st.time_input("Hora Retirada", value=time(12, 0))

    st.markdown("### 2. Detalhes do Pedido")
    with st.form("form_pedido", clear_on_submit=True): 
        
        col_contato, col_data = st.columns(2)
        with col_contato:
            contato = st.text_input("WhatsApp", key="chave_contato_automatico")
        with col_data:
            data_entrega = st.date_input("Data Entrega", min_value=date.today(), format="DD/MM/YYYY")
            
        col_qtd1, col_qtd2, col_desc = st.columns(3)
        with col_qtd1:
            qtd_caruru = st.number_input("Caruru (Unid)", min_value=0, step=1)
        with col_qtd2:
            qtd_bobo = st.number_input("Bobó (Unid)", min_value=0, step=1)
        with col_desc:
            desconto = st.number_input("Desc %", 0, 100)
            
        obs = st.text_area("Observações do Pedido")
            
        col_pag, col_st = st.columns(2)
        with col_pag:
            pagamento = st.selectbox("Pagamento", OPCOES_PAGAMENTO)
        with col_st:
            status = st.selectbox("Status", OPCOES_STATUS, index=0)
            
        submitted = st.form_submit_button("💾 SALVAR PEDIDO")
        
        if submitted:
            cliente_final = st.session_state.chave_cliente_selecionado
            if not cliente_final:
                st.error("Erro: Selecione um cliente na lista acima.")
            else:
                valor = calcular_total(qtd_caruru, qtd_bobo, desconto)
                hora_str = hora_entrega.strftime("%H:%M")
                
                novo = {
                    "Cliente": cliente_final, "Caruru": qtd_caruru, "Bobo": qtd_bobo,
                    "Valor": valor, "Data": data_entrega, "Hora": hora_str, 
                    "Status": status, "Pagamento": pagamento, "Contato": contato, 
                    "Desconto": desconto, "Observacoes": obs
                }
                novo_df = pd.DataFrame([novo])
                novo_df['Data'] = pd.to_datetime(novo_df['Data']).dt.date
                
                st.session_state.pedidos = pd.concat([st.session_state.pedidos, novo_df], ignore_index=True)
                salvar_pedidos(st.session_state.pedidos)
                
                st.success(f"Pedido de {cliente_final} Salvo!")
                st.session_state['chave_contato_automatico'] = "" 
                st.rerun()

# =================================================================================
# GERENCIAR TUDO
# =================================================================================
elif menu == "Gerenciar Tudo":
    st.title("📦 Todos os Pedidos")
    
    df = st.session_state.pedidos
    
    if not df.empty:
        try:
            df['Hora_Sort'] = df['Hora'].apply(lambda x: x if x is not None else time(0,0))
            df = df.sort_values(by=["Data", "Hora_Sort"], ascending=[True, True]).drop(columns=['Hora_Sort'])
        except:
            df = df.sort_values(by="Data", ascending=True)
        
        df_editado = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Valor": st.column_config.NumberColumn("Valor Total", format="R$ %.2f", disabled=True),
                "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "Hora": st.column_config.TimeColumn("Hora", format="HH:mm"),
                "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                "Pagamento": st.column_config.SelectboxColumn(options=OPCOES_PAGAMENTO, required=True),
                "Caruru": st.column_config.NumberColumn(format="%d", step=1),
                "Bobo": st.column_config.NumberColumn(format="%d", step=1),
                "Observacoes": st.column_config.TextColumn("Obs", width="large"),
            },
            hide_index=True
        )
        
        if not df_editado.equals(df):
            preco_base = 70.0
            df_editado['Valor'] = ((df_editado['Caruru'] * preco_base) + (df_editado['Bobo'] * preco_base)) * (1 - (df_editado['Desconto'] / 100))
            st.session_state.pedidos = df_editado
            salvar_pedidos(df_editado)
            st.toast("Salvo!", icon="💾")
            st.rerun()
            
        st.divider()
        st.subheader("💬 Enviar Mensagem")
        clientes_ordenados = sorted(df['Cliente'].unique())
        sel_cli = st.selectbox("Cliente:", clientes_ordenados)
        
        if sel_cli:
            dados = df[df['Cliente'] == sel_cli].iloc[-1]
            tel = str(dados['Contato']).replace(".0", "").replace(" ", "").replace("-", "")
            data_str = dados['Data'].strftime('%d/%m/%Y') if hasattr(dados['Data'], 'strftime') else str(dados['Data'])
            try:
                hora_str = dados['Hora'].strftime('%H:%M')
            except:
                hora_str = str(dados['Hora'])

            msg = f"Olá {sel_cli}, seu pedido no Cantinho do Caruru está confirmado!\n\n"
            msg += f"🗓 Data: {data_str} às {hora_str}\n"
            msg += f"📦 Pedido: {int(dados['Caruru'])} Caruru, {int(dados['Bobo'])} Bobó\n"
            msg += f"💰 Valor: R$ {dados['Valor']:.2f}\n"
            
            if dados['Pagamento'] == "NÃO PAGO" or dados['Pagamento'] == "METADE":
                msg += f"\n⚠️ Pagamento pendente. Segue chave PIX:\n🔑 {CHAVE_PIX}\n"
            
            link = f"https://wa.me/55{tel}?text={msg.replace(' ', '%20').replace(chr(10), '%0A')}"
            st.link_button(f"Enviar WhatsApp para {sel_cli}", link)
            
    st.divider()
    with st.expander("💾 Segurança (Backup & Restaurar)"):
        st.write("### 1. Fazer Backup Geral")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            zip_file.writestr("pedidos.csv", df.to_csv(index=False))
            zip_file.writestr("clientes.csv", st.session_state.clientes.to_csv(index=False))
        st.download_button("📥 Baixar Backup Geral (.zip)", data=zip_buffer.getvalue(), file_name=f"backup_caruru_geral_{date.today()}.zip", mime="application/zip")
        
        st.write("### 2. Restaurar Pedidos")
        arquivo_upload = st.file_uploader("Restaurar PEDIDOS (csv)", type=["csv"])
        if arquivo_upload is not None:
            if st.button("🚨 CONFIRMAR RESTAURAÇÃO DE PEDIDOS"):
                try:
                    df_novo = pd.read_csv(arquivo_upload)
                    salvar_pedidos(df_novo)
                    st.session_state.pedidos = carregar_pedidos()
                    st.success("Restaurado!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

# =================================================================================
# RELATÓRIOS E RECIBOS
# =================================================================================
elif menu == "🖨️ Relatórios & Recibos":
    st.title("🖨️ Central de Impressão")
    
    tab_recibo, tab_relatorio = st.tabs(["🧾 Emitir Recibo", "📊 Relatórios PDF"])
    
    df = st.session_state.pedidos
    
    with tab_recibo:
        st.subheader("Gerar Recibo Individual")
        if df.empty:
            st.warning("Sem pedidos.")
        else:
            clientes_disp = sorted(df['Cliente'].unique())
            cli_recibo = st.selectbox("Selecione o Cliente:", clientes_disp)
            
            pedidos_cli = df[df['Cliente'] == cli_recibo].sort_values(by="Data", ascending=False)
            
            if not pedidos_cli.empty:
                opcoes_pedidos = {
                    i: f"{p['Data'].strftime('%d/%m/%Y')} - R$ {p['Valor']:.2f} ({p['Status']})" 
                    for i, p in pedidos_cli.iterrows()
                }
                
                id_pedido = st.selectbox("Pedido:", options=opcoes_pedidos.keys(), format_func=lambda x: opcoes_pedidos[x])
                
                if st.button("📄 Gerar PDF do Recibo"):
                    dados_pedido = pedidos_cli.loc[id_pedido]
                    pdf_bytes = gerar_recibo_pdf(dados_pedido)
                    st.download_button(
                        label="📥 Baixar Recibo PDF",
                        data=pdf_bytes,
                        file_name=f"Recibo_{cli_recibo}.pdf",
                        mime="application/pdf"
                    )
            else:
                st.info("Este cliente não tem pedidos.")

    with tab_relatorio:
        st.subheader("Relatórios Gerenciais")
        tipo_relatorio = st.radio("Tipo:", ["Entregas do Dia", "Todos os Pedidos"])
        
        if tipo_relatorio == "Entregas do Dia":
            data_rel = st.date_input("Selecione o dia:", date.today(), format="DD/MM/YYYY")
            df_rel = df[df['Data'] == data_rel]
            titulo = f"Relatório de Entregas - {data_rel.strftime('%d/%m/%Y')}"
        else:
            df_rel = df
            titulo = "Relatório Geral de Vendas"
            
        st.write(f"Total: {len(df_rel)} registros")
        
        if not df_rel.empty:
            if st.button("📊 Gerar Relatório PDF"):
                pdf_rel = gerar_relatorio_pdf(df_rel, titulo)
                st.download_button(
                    label="📥 Baixar Relatório PDF",
                    data=pdf_rel,
                    file_name=f"Relatorio_{date.today()}.pdf",
                    mime="application/pdf"
                )

# =================================================================================
# CLIENTES
# =================================================================================
elif menu == "👥 Cadastrar Clientes":
    st.title("👥 Base de Clientes")
    
    tab1, tab2 = st.tabs(["➕ Novo / Editar", "🗑️ Excluir"])
    
    with tab1:
        with st.expander("➕ Adicionar Novo Cliente", expanded=True):
            with st.form("form_cliente", clear_on_submit=True):
                c_nome = st.text_input("Nome Completo")
                c_zap = st.text_input("WhatsApp (DDD+Número)")
                c_obs = st.text_area("Obs. Fixa")
                
                if st.form_submit_button("CADASTRAR"):
                    if c_nome:
                        novo_cli = {"Nome": c_nome, "Contato": c_zap, "Observacoes": c_obs}
                        st.session_state.clientes = pd.concat([st.session_state.clientes, pd.DataFrame([novo_cli])], ignore_index=True)
                        salvar_clientes(st.session_state.clientes)
                        st.success("Cadastrado!")
                        st.rerun()

        st.divider()
        if not st.session_state.clientes.empty:
            cli_editado = st.data_editor(st.session_state.clientes, num_rows="dynamic", use_container_width=True, hide_index=True)
            if not cli_editado.equals(st.session_state.clientes):
                st.session_state.clientes = cli_editado
                salvar_clientes(cli_editado)
                st.toast("Salvo!", icon="💾")
                
        st.divider()
        with st.expander("💾 Backup e Restauração (Apenas Clientes)"):
            st.write("### 1. Fazer Backup")
            csv_cli = st.session_state.clientes.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Baixar Lista de Clientes", data=csv_cli, file_name=f"clientes_caruru_{date.today()}.csv", mime="text/csv")

            st.write("### 2. Restaurar")
            arquivo_cli = st.file_uploader("Envie arquivo de clientes", type=["csv"], key="upload_cli")
            if arquivo_cli is not None:
                if st.button("🚨 CONFIRMAR RESTAURAÇÃO DE CLIENTES"):
                    try:
                        df_novo = pd.read_csv(arquivo_cli)
                        salvar_clientes(df_novo)
                        st.session_state.clientes = carregar_clientes()
                        st.success("Restaurado!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro: {e}")
    
    with tab2:
        lista_excluir = st.session_state.clientes['Nome'].unique()
        cliente_del = st.selectbox("Excluir:", lista_excluir)
        if st.button("CONFIRMAR EXCLUSÃO"):
            st.session_state.clientes = st.session_state.clientes[st.session_state.clientes['Nome'] != cliente_del]
            salvar_clientes(st.session_state.clientes)
            st.success("Excluído!")
            st.rerun()
