import streamlit as st
import pandas as pd
from datetime import date
import os

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Cantinho do Caruru", page_icon="🦐", layout="wide")

# Arquivo de dados
ARQUIVO_DADOS = "banco_de_dados_caruru.csv"

# --- FUNÇÕES ---
def carregar_dados():
    if os.path.exists(ARQUIVO_DADOS):
        try:
            df = pd.read_csv(ARQUIVO_DADOS)
            # Garante que as colunas numéricas sejam números reais (float) para evitar erro de cálculo
            df['Caruru'] = df['Caruru'].fillna(0).astype(float)
            df['Bobo'] = df['Bobo'].fillna(0).astype(float)
            df['Desconto'] = df['Desconto'].fillna(0).astype(float)
            df['Valor'] = df['Valor'].fillna(0).astype(float)
            
            # Converte data
            df['Data'] = pd.to_datetime(df['Data']).dt.date
            return df
        except:
            return pd.DataFrame(columns=["Cliente", "Caruru", "Bobo", "Valor", "Data", "Status", "Pagamento", "Contato", "Desconto"])
    else:
        return pd.DataFrame(columns=["Cliente", "Caruru", "Bobo", "Valor", "Data", "Status", "Pagamento", "Contato", "Desconto"])

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
</style>
""", unsafe_allow_html=True)

# --- MENU LATERAL ---
with st.sidebar:
    st.title("🦐 Menu")
    menu = st.radio("Ir para:", ["Dashboard", "Novo Pedido", "Gerenciar Pedidos"])
    st.divider()
    st.caption("Sistema Online v1.1")

# --- PÁGINA 1: DASHBOARD ---
if menu == "Dashboard":
    st.title("📊 Painel")
    
    df = st.session_state.pedidos
    
    if df.empty:
        st.info("Cadastre o primeiro pedido para ver os gráficos.")
    else:
        data_analise = st.date_input("Filtrar Data:", date.today(), format="DD/MM/YYYY")
        df_dia = df[df['Data'] == data_analise]
        
        col1, col2 = st.columns(2)
        col1.metric("Faturamento Geral", f"R$ {df['Valor'].sum():,.2f}")
        pendentes = df_dia[df_dia['Status'] != 'Entregue']
        col2.metric("A Receber", f"R$ {df[df['Pagamento'] != 'PAGO']['Valor'].sum():,.2f}")
        
        st.divider()
        c1, c2 = st.columns(2)
        # Mostra números inteiros no dashboard também
        c1.metric(f"Caruru ({data_analise.strftime('%d/%m')})", f"{int(pendentes['Caruru'].sum())} Unid")
        c2.metric(f"Bobó ({data_analise.strftime('%d/%m')})", f"{int(pendentes['Bobo'].sum())} Unid")

# --- PÁGINA 2: NOVO PEDIDO ---
elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    
    with st.form("form_pedido", clear_on_submit=True):
        nome = st.text_input("Nome Cliente")
        col_contato, col_data = st.columns(2)
        with col_contato:
            contato = st.text_input("WhatsApp (DDD+Número)")
        with col_data:
            data_entrega = st.date_input("Data Entrega", min_value=date.today(), format="DD/MM/YYYY")
            
        col_qtd1, col_qtd2, col_desc = st.columns(3)
        with col_qtd1:
            # step=1 garante que só digite inteiros
            qtd_caruru = st.number_input("Caruru (Unidades)", min_value=0, step=1)
        with col_qtd2:
            qtd_bobo = st.number_input("Bobó (Unidades)", min_value=0, step=1)
        with col_desc:
            desconto = st.number_input("Desc %", 0, 100)
            
        col_pag, col_st = st.columns(2)
        with col_pag:
            pagamento = st.selectbox("Pagamento", ["PAGO", "NÃO PAGO", "METADE"])
        with col_st:
            status = st.selectbox("Status", ["Pendente", "Em Produção", "Entregue"])
            
        submitted = st.form_submit_button("SALVAR")
        
        if submitted and nome:
            valor = calcular_total(qtd_caruru, qtd_bobo, desconto)
            novo = {
                "Cliente": nome, "Caruru": qtd_caruru, "Bobo": qtd_bobo,
                "Valor": valor, "Data": data_entrega, "Status": status,
                "Pagamento": pagamento, "Contato": contato, "Desconto": desconto
            }
            st.session_state.pedidos = pd.concat([st.session_state.pedidos, pd.DataFrame([novo])], ignore_index=True)
            salvar_dados(st.session_state.pedidos)
            st.success("Pedido Salvo!")

# --- PÁGINA 3: GERENCIAR (TABELA INTELIGENTE) ---
elif menu == "Gerenciar Pedidos":
    st.title("📦 Encomendas")
    st.caption("Edite as quantidades e o valor será recalculado automaticamente!")
    
    df = st.session_state.pedidos
    
    if not df.empty:
        # Configuração das Colunas
        df_editado = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Valor": st.column_config.NumberColumn(
                    "Valor Total",
                    format="R$ %.2f",
                    disabled=True # Bloqueia edição manual do valor para evitar erro, já que ele é calculado
                ),
                "Data": st.column_config.DateColumn("Data Entrega", format="DD/MM/YYYY"),
                "Status": st.column_config.SelectboxColumn(options=["Pendente", "Em Produção", "Entregue", "Cancelado"], required=True),
                "Pagamento": st.column_config.SelectboxColumn(options=["PAGO", "NÃO PAGO", "METADE"], required=True),
                # AQUI ESTÁ A MUDANÇA PARA INTEIROS:
                "Caruru": st.column_config.NumberColumn("Caruru", format="%d", step=1, min_value=0),
                "Bobo": st.column_config.NumberColumn("Bobó", format="%d", step=1, min_value=0),
                "Desconto": st.column_config.NumberColumn("Desc %", format="%d%%", step=1, min_value=0, max_value=100),
            },
            hide_index=True
        )
        
        # LÓGICA DE RECALCULO AUTOMÁTICO
        if not df_editado.equals(df):
            # Recalcula a coluna Valor linha por linha baseada nas novas quantidades
            # Preço Base R$ 70.00 fixo no código
            preco_base = 70.0
            
            # Fórmula: (Caruru * 70 + Bobo * 70) * (1 - Desconto/100)
            df_editado['Valor'] = (
                (df_editado['Caruru'] * preco_base) + (df_editado['Bobo'] * preco_base)
            ) * (1 - (df_editado['Desconto'] / 100))
            
            # Salva
            st.session_state.pedidos = df_editado
            salvar_dados(df_editado)
            st.rerun() # Atualiza a tela para mostrar o valor novo instantaneamente
            
        # Botão WhatsApp
        st.divider()
        clientes = df['Cliente'].unique()
        sel_cli = st.selectbox("Gerar WhatsApp para:", clientes)
        if sel_cli:
            dados = df[df['Cliente'] == sel_cli].iloc[-1]
            tel = str(dados['Contato']).replace(".0", "").replace(" ", "").replace("-", "")
            # Formata data
            data_str = dados['Data'].strftime('%d/%m/%Y') if hasattr(dados['Data'], 'strftime') else str(dados['Data'])
            
            msg = f"Olá {sel_cli}, pedido confirmado! Valor: R$ {dados['Valor']:.2f}. Data: {data_str}."
            link = f"https://wa.me/55{tel}?text={msg.replace(' ', '%20')}"
            st.link_button(f"Enviar Zap para {sel_cli}", link)
