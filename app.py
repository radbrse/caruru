import streamlit as st
import pandas as pd
from datetime import date, datetime, time
import os
import io
import zipfile

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Cantinho do Caruru", page_icon="🦐", layout="wide")

# Arquivos de dados
ARQUIVO_PEDIDOS = "banco_de_dados_caruru.csv"
ARQUIVO_CLIENTES = "banco_de_dados_clientes.csv"
CHAVE_PIX = "seu-pix-aqui"

# --- OPÇÕES ---
OPCOES_STATUS = ["🔴 Pendente", "🟡 Em Produção", "✅ Entregue", "🚫 Cancelado"]
OPCOES_PAGAMENTO = ["PAGO", "NÃO PAGO", "METADE"]

# --- FUNÇÕES DE CARREGAMENTO ---
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

            # Migração Status
            mapa_status = {"Pendente": "🔴 Pendente", "Em Produção": "🟡 Em Produção", "Entregue": "✅ Entregue", "Cancelado": "🚫 Cancelado"}
            df['Status'] = df['Status'].replace(mapa_status)
            
            # Data e Hora
            df['Data'] = pd.to_datetime(df['Data'], errors='coerce').dt.date

            def limpar_hora(h):
                if pd.isna(h) or str(h).strip() == "" or str(h).lower() == "nan": return None
                try:
                    if isinstance(h, time): return h
                    return pd.to_datetime(str(h), format='%H:%M').time()
                except:
                    return None

            df['Hora'] = df['Hora'].apply(limpar_hora)
            return df
        except:
            return pd.DataFrame(columns=colunas_padrao)
    else:
        return pd.DataFrame(columns=colunas_padrao)

# --- FUNÇÕES DE SALVAMENTO ---
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
    st.title("🦐 Menu")
    menu = st.radio("Ir para:", ["Dashboard do Dia", "Novo Pedido", "👥 Cadastrar Clientes", "Gerenciar Tudo"])
    st.divider()
    st.caption("Sistema Online v4.0 (Clientes)")

# =================================================================================
# PÁGINA: CADASTRAR CLIENTES (NOVA)
# =================================================================================
if menu == "👥 Cadastrar Clientes":
    st.title("👥 Base de Clientes")
    
    with st.expander("➕ Adicionar Novo Cliente", expanded=True):
        with st.form("form_cliente", clear_on_submit=True):
            c_nome = st.text_input("Nome Completo")
            c_zap = st.text_input("WhatsApp (DDD+Número)")
            c_obs = st.text_area("Obs. Fixa (Ex: Não gosta de coentro)")
            
            sub_cli = st.form_submit_button("CADASTRAR CLIENTE")
            
            if sub_cli and c_nome:
                # Verifica se já existe
                if c_nome in st.session_state.clientes['Nome'].values:
                    st.warning("Este nome já existe no cadastro!")
                else:
                    novo_cli = {"Nome": c_nome, "Contato": c_zap, "Observacoes": c_obs}
                    st.session_state.clientes = pd.concat([st.session_state.clientes, pd.DataFrame([novo_cli])], ignore_index=True)
                    salvar_clientes(st.session_state.clientes)
                    st.success(f"Cliente {c_nome} cadastrado!")
                    st.rerun()

    st.divider()
    st.subheader("Lista de Clientes")
    
    if not st.session_state.clientes.empty:
        # Tabela editável de clientes
        cli_editado = st.data_editor(
            st.session_state.clientes,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Nome": st.column_config.TextColumn("Nome", disabled=False),
                "Contato": st.column_config.TextColumn("WhatsApp"),
            },
            hide_index=True
        )
        
        if not cli_editado.equals(st.session_state.clientes):
            st.session_state.clientes = cli_editado
            salvar_clientes(cli_editado)
            st.toast("Lista de clientes atualizada!", icon="💾")

# =================================================================================
# PÁGINA: DASHBOARD
# =================================================================================
elif menu == "Dashboard do Dia":
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
                
    # --- ÁREA DE SEGURANÇA (ZIP) ---
    st.divider()
    with st.expander("💾 Área de Segurança (Backup Completo)"):
        st.write("Baixe todos os dados (Pedidos + Clientes).")
        
        # Cria ZIP na memória
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False) as zip_file:
            zip_file.writestr("pedidos.csv", df.to_csv(index=False))
            zip_file.writestr("clientes.csv", st.session_state.clientes.to_csv(index=False))
        
        st.download_button(
            label="📥 Baixar Backup Geral (.zip)",
            data=zip_buffer.getvalue(),
            file_name=f"backup_caruru_geral_{date.today()}.zip",
            mime="application/zip",
        )

# =================================================================================
# PÁGINA: NOVO PEDIDO (INTEGRADO COM CLIENTES)
# =================================================================================
elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    
    # Lista de clientes cadastrados
    lista_clientes = st.session_state.clientes['Nome'].tolist()
    lista_clientes.sort()
    # Adiciona opção vazia no início
    lista_clientes.insert(0, "")
    
    with st.form("form_pedido", clear_on_submit=False): # False para manter o contato preenchido visualmente
        col_nome, col_hora = st.columns([3, 1])
        
        with col_nome:
            # SELECTBOX DE CLIENTES
            nome_selecionado = st.selectbox("Selecione o Cliente", lista_clientes)
        
        with col_hora:
            hora_entrega = st.time_input("Hora Retirada", value=time(12, 0))
        
        # Busca o contato automático se tiver cliente selecionado
        contato_auto = ""
        if nome_selecionado:
            filtro = st.session_state.clientes[st.session_state.clientes['Nome'] == nome_selecionado]
            if not filtro.empty:
                contato_auto = filtro.iloc[0]['Contato']
        
        col_contato, col_data = st.columns(2)
        with col_contato:
            # Preenche automático, mas permite editar
            contato = st.text_input("WhatsApp", value=contato_auto)
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
            
        submitted = st.form_submit_button("SALVAR PEDIDO")
        
        if submitted:
            if not nome_selecionado:
                st.error("Por favor, selecione um cliente (ou cadastre um novo na aba Clientes).")
            else:
                valor = calcular_total(qtd_caruru, qtd_bobo, desconto)
                hora_str = hora_entrega.strftime("%H:%M")
                
                novo = {
                    "Cliente": nome_selecionado, "Caruru": qtd_caruru, "Bobo": qtd_bobo,
                    "Valor": valor, "Data": data_entrega, "Hora": hora_str, 
                    "Status": status, "Pagamento": pagamento, "Contato": contato, 
                    "Desconto": desconto, "Observacoes": obs
                }
                novo_df = pd.DataFrame([novo])
                st.session_state.pedidos = pd.concat([st.session_state.pedidos, novo_df], ignore_index=True)
                salvar_pedidos(st.session_state.pedidos)
                
                # Recarrega para limpar
                st.success(f"Pedido de {nome_selecionado} Salvo!")
                # Reset manual visual (opcional) ou apenas avisar

# =================================================================================
# PÁGINA: GERENCIAR TUDO
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
            
            msg += "\nObrigado pela preferência! 🦐"
            
            link = f"https://wa.me/55{tel}?text={msg.replace(' ', '%20').replace(chr(10), '%0A')}"
            st.link_button(f"Enviar WhatsApp para {sel_cli}", link)
