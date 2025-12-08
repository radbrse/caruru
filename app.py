import streamlit as st
import pandas as pd
from datetime import date, datetime, time
import os

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Cantinho do Caruru", page_icon="🦐", layout="wide")

# Arquivo de dados
ARQUIVO_DADOS = "banco_de_dados_caruru.csv"

# --- SUA CHAVE PIX AQUI ---
CHAVE_PIX = "seu-email-ou-cpf@pix.com"  # <--- EDITE AQUI DEPOIS

# --- FUNÇÕES ---
def carregar_dados():
    colunas_padrao = ["Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]
    
    if os.path.exists(ARQUIVO_DADOS):
        try:
            df = pd.read_csv(ARQUIVO_DADOS)
            # Garante colunas
            for col in colunas_padrao:
                if col not in df.columns:
                    df[col] = "" if col in ["Observacoes", "Hora"] else 0
            
            # Tipagem
            df['Caruru'] = df['Caruru'].fillna(0).astype(float)
            df['Bobo'] = df['Bobo'].fillna(0).astype(float)
            df['Desconto'] = df['Desconto'].fillna(0).astype(float)
            df['Valor'] = df['Valor'].fillna(0).astype(float)
            df['Data'] = pd.to_datetime(df['Data']).dt.date
            df['Observacoes'] = df['Observacoes'].fillna("").astype(str)
            df['Hora'] = df['Hora'].fillna("").astype(str) # Garante que Hora seja texto
            
            return df
        except:
            return pd.DataFrame(columns=colunas_padrao)
    else:
        return pd.DataFrame(columns=colunas_padrao)

def salvar_dados(df):
    df.to_csv(ARQUIVO_DADOS, index=False)

def calcular_total(caruru, bobo, desconto):
    preco_base = 70.0
    total = (caruru * preco_base) + (bobo * preco_base)
    if desconto > 0:
        total = total * (1 - (desconto/100))
    return total

# Inicializa Sessão
if 'pedidos' not in st.session_state:
    st.session_state.pedidos = carregar_dados()

# CSS
st.markdown("""
<style>
    .metric-card {background-color: #f9f9f9; border-left: 5px solid #ff4b4b; padding: 10px; border-radius: 5px;}
    .stButton>button {width: 100%; border-radius: 12px; font-weight: bold; height: 50px;}
    div[data-testid="stMetricValue"] {font-size: 20px;}
</style>
""", unsafe_allow_html=True)

# --- MENU LATERAL ---
with st.sidebar:
    st.title("🦐 Menu")
    menu = st.radio("Ir para:", ["Dashboard do Dia", "Novo Pedido", "Gerenciar Tudo"])
    st.divider()
    st.caption("Sistema Online v3.0")

# --- PÁGINA 1: DASHBOARD ---
if menu == "Dashboard do Dia":
    st.title("🚚 Expedição do Dia")
    
    df = st.session_state.pedidos
    
    if df.empty:
        st.info("Cadastre pedidos para começar.")
    else:
        data_analise = st.date_input("📅 Data de Entrega:", date.today(), format="DD/MM/YYYY")
        
        # Filtra e ORDENA por Hora
        df_dia = df[df['Data'] == data_analise].copy()
        df_dia = df_dia.sort_values(by="Hora")
        
        # Métricas
        col1, col2, col3, col4 = st.columns(4)
        pendentes = df_dia[df_dia['Status'] != 'Entregue']
        
        col1.metric("Caruru a Entregar", f"{int(pendentes['Caruru'].sum())} Unid")
        col2.metric("Bobó a Entregar", f"{int(pendentes['Bobo'].sum())} Unid")
        col3.metric("Faturamento Dia", f"R$ {df_dia['Valor'].sum():,.2f}")
        col4.metric("A Receber", f"R$ {df_dia[df_dia['Pagamento'] != 'PAGO']['Valor'].sum():,.2f}", delta_color="inverse")
        
        st.divider()
        st.subheader(f"📋 Entregas de {data_analise.strftime('%d/%m')} (Por Horário)")
        
        if df_dia.empty:
            st.warning("Nenhuma entrega para este dia.")
        else:
            # Editor Rápido
            df_baixa = st.data_editor(
                df_dia,
                column_order=["Hora", "Status", "Cliente", "Caruru", "Bobo", "Valor", "Pagamento", "Observacoes"],
                disabled=["Cliente", "Caruru", "Bobo", "Valor", "Hora"], 
                hide_index=True,
                use_container_width=True,
                key="editor_dashboard",
                column_config={
                    "Status": st.column_config.SelectboxColumn("Status", options=["Pendente", "Em Produção", "Entregue", "Cancelado"], required=True, width="medium"),
                    "Observacoes": st.column_config.TextColumn("Obs", width="large"),
                    "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Hora": st.column_config.TextColumn("Hora", width="small"),
                }
            )
            
            # Salvar alterações
            indices_dia = df_dia.index
            mudou = False
            for i in indices_dia:
                if (df.loc[i, 'Status'] != df_baixa.loc[i, 'Status']) or \
                   (df.loc[i, 'Pagamento'] != df_baixa.loc[i, 'Pagamento']) or \
                   (df.loc[i, 'Observacoes'] != df_baixa.loc[i, 'Observacoes']):
                    df.loc[i, 'Status'] = df_baixa.loc[i, 'Status']
                    df.loc[i, 'Pagamento'] = df_baixa.loc[i, 'Pagamento']
                    df.loc[i, 'Observacoes'] = df_baixa.loc[i, 'Observacoes']
                    mudou = True
            
            if mudou:
                st.session_state.pedidos = df
                salvar_dados(df)
                st.toast("Atualizado!", icon="✅")
                st.rerun()

# --- PÁGINA 2: NOVO PEDIDO ---
elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    
    with st.form("form_pedido", clear_on_submit=True):
        col_nome, col_hora = st.columns([3, 1])
        with col_nome:
            nome = st.text_input("Nome Cliente")
        with col_hora:
            # NOVO CAMPO DE HORA
            hora_entrega = st.time_input("Hora Retirada", value=time(12, 0))
        
        col_contato, col_data = st.columns(2)
        with col_contato:
            contato = st.text_input("WhatsApp")
        with col_data:
            data_entrega = st.date_input("Data Entrega", min_value=date.today(), format="DD/MM/YYYY")
            
        col_qtd1, col_qtd2, col_desc = st.columns(3)
        with col_qtd1:
            qtd_caruru = st.number_input("Caruru (Unid)", min_value=0, step=1)
        with col_qtd2:
            qtd_bobo = st.number_input("Bobó (Unid)", min_value=0, step=1)
        with col_desc:
            desconto = st.number_input("Desc %", 0, 100)
            
        obs = st.text_area("Observações")
            
        col_pag, col_st = st.columns(2)
        with col_pag:
            pagamento = st.selectbox("Pagamento", ["PAGO", "NÃO PAGO", "METADE"])
        with col_st:
            status = st.selectbox("Status", ["Pendente", "Em Produção", "Entregue"])
            
        submitted = st.form_submit_button("SALVAR PEDIDO")
        
        if submitted and nome:
            valor = calcular_total(qtd_caruru, qtd_bobo, desconto)
            novo = {
                "Cliente": nome, "Caruru": qtd_caruru, "Bobo": qtd_bobo,
                "Valor": valor, "Data": data_entrega, 
                "Hora": hora_entrega.strftime("%H:%M"), # Salva hora como texto bonitinho
                "Status": status, "Pagamento": pagamento, "Contato": contato, 
                "Desconto": desconto, "Observacoes": obs
            }
            st.session_state.pedidos = pd.concat([st.session_state.pedidos, pd.DataFrame([novo])], ignore_index=True)
            salvar_dados(st.session_state.pedidos)
            st.success("Pedido Salvo!")

# --- PÁGINA 3: GERENCIAR TUDO (COM ORDENAÇÃO) ---
elif menu == "Gerenciar Tudo":
    st.title("📦 Todos os Pedidos")
    st.caption("Organizado por Data de Entrega (Do mais próximo para o mais distante).")
    
    df = st.session_state.pedidos
    
    if not df.empty:
        # --- AQUI ESTÁ A ORDENAÇÃO AUTOMÁTICA ---
        # Ordena por Data e depois por Hora
        df = df.sort_values(by=["Data", "Hora"], ascending=[True, True])
        
        # Editor
        df_editado = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Valor": st.column_config.NumberColumn("Valor Total", format="R$ %.2f", disabled=True),
                "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "Hora": st.column_config.TimeColumn("Hora", format="HH:mm"), # Coluna de hora editável
                "Status": st.column_config.SelectboxColumn(options=["Pendente", "Em Produção", "Entregue", "Cancelado"], required=True),
                "Pagamento": st.column_config.SelectboxColumn(options=["PAGO", "NÃO PAGO", "METADE"], required=True),
                "Caruru": st.column_config.NumberColumn(format="%d", step=1),
                "Bobo": st.column_config.NumberColumn(format="%d", step=1),
                "Observacoes": st.column_config.TextColumn("Obs", width="large"),
            },
            hide_index=True
        )
        
        # Salvar Edições
        if not df_editado.equals(df):
            # Como reordenamos a visualização (df), precisamos ter cuidado ao salvar.
            # O st.data_editor retorna o dataframe já editado na ordem nova.
            # Podemos salvar direto, pois a ordem do CSV não importa tanto, o sistema reordena ao abrir.
            
            # Recalculo de valor (caso tenha mudado qtd)
            preco_base = 70.0
            df_editado['Valor'] = ((df_editado['Caruru'] * preco_base) + (df_editado['Bobo'] * preco_base)) * (1 - (df_editado['Desconto'] / 100))
            
            st.session_state.pedidos = df_editado
            salvar_dados(df_editado)
            st.toast("Salvo!", icon="💾")
            st.rerun()
            
        # --- WHATSAPP INTELIGENTE COM PIX ---
        st.divider()
        st.subheader("💬 Enviar Mensagem")
        clientes_ordenados = df['Cliente'].unique() # Pega da lista já ordenada
        sel_cli = st.selectbox("Cliente:", clientes_ordenados)
        
        if sel_cli:
            # Pega o último pedido deste cliente
            dados = df[df['Cliente'] == sel_cli].iloc[-1]
            tel = str(dados['Contato']).replace(".0", "").replace(" ", "").replace("-", "")
            
            # Monta a mensagem
            data_str = dados['Data'].strftime('%d/%m/%Y')
            msg = f"Olá {sel_cli}, seu pedido no Cantinho do Caruru está confirmado!\n\n"
            msg += f"🗓 Data: {data_str} às {dados['Hora']}\n"
            msg += f"📦 Pedido: {int(dados['Caruru'])} Caruru, {int(dados['Bobo'])} Bobó\n"
            msg += f"💰 Valor: R$ {dados['Valor']:.2f}\n"
            
            # Adiciona PIX se não tiver pago
            if dados['Pagamento'] == "NÃO PAGO" or dados['Pagamento'] == "METADE":
                msg += f"\n⚠️ Pagamento pendente. Segue chave PIX:\n🔑 {CHAVE_PIX}\n"
            
            msg += "\nObrigado pela preferência! 🦐"
            
            link = f"https://wa.me/55{tel}?text={msg.replace(' ', '%20').replace(chr(10), '%0A')}"
            st.link_button(f"Enviar WhatsApp para {sel_cli}", link)
