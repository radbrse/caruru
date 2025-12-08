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
    colunas_padrao = ["Cliente", "Caruru", "Bobo", "Valor", "Data", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]
    
    if os.path.exists(ARQUIVO_DADOS):
        try:
            df = pd.read_csv(ARQUIVO_DADOS)
            # Garante que todas as colunas existam (para compatibilidade com versões anteriores)
            for col in colunas_padrao:
                if col not in df.columns:
                    df[col] = "" if col == "Observacoes" else 0
            
            # Tipagem correta
            df['Caruru'] = df['Caruru'].fillna(0).astype(float)
            df['Bobo'] = df['Bobo'].fillna(0).astype(float)
            df['Desconto'] = df['Desconto'].fillna(0).astype(float)
            df['Valor'] = df['Valor'].fillna(0).astype(float)
            df['Data'] = pd.to_datetime(df['Data']).dt.date
            df['Observacoes'] = df['Observacoes'].fillna("").astype(str)
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

# CSS Personalizado
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
    st.caption("Sistema Online v2.0")

# --- PÁGINA 1: DASHBOARD (AGORA COM BAIXA RÁPIDA) ---
if menu == "Dashboard do Dia":
    st.title("🚚 Expedição e Controle")
    
    df = st.session_state.pedidos
    
    if df.empty:
        st.info("Cadastre pedidos para começar.")
    else:
        # Filtro de Data
        data_analise = st.date_input("📅 Selecione a Data de Entrega:", date.today(), format="DD/MM/YYYY")
        
        # Cria uma cópia filtrada para o dia
        # Resetamos o index para garantir que conseguimos salvar de volta corretamente depois
        df_dia = df[df['Data'] == data_analise].copy()
        
        # --- MÉTRICAS DO TOPO ---
        col1, col2, col3, col4 = st.columns(4)
        
        pendentes = df_dia[df_dia['Status'] != 'Entregue']
        total_pedidos_dia = len(df_dia)
        entregues_dia = len(df_dia) - len(pendentes)
        
        # Barra de Progresso do Dia
        if total_pedidos_dia > 0:
            progresso = entregues_dia / total_pedidos_dia
            st.progress(progresso, text=f"Progresso das Entregas: {int(progresso*100)}%")
        
        col1.metric("Caruru a Entregar", f"{int(pendentes['Caruru'].sum())} Unid")
        col2.metric("Bobó a Entregar", f"{int(pendentes['Bobo'].sum())} Unid")
        col3.metric("Faturamento do Dia", f"R$ {df_dia['Valor'].sum():,.2f}")
        col4.metric("A Receber (Dia)", f"R$ {df_dia[df_dia['Pagamento'] != 'PAGO']['Valor'].sum():,.2f}", delta_color="inverse")
        
        st.divider()
        st.subheader(f"📋 Lista de Entregas ({data_analise.strftime('%d/%m')})")
        
        if df_dia.empty:
            st.warning("Nenhuma entrega agendada para este dia.")
        else:
            st.caption("⚡ Dica: Mude o Status para 'Entregue' aqui mesmo para dar baixa.")
            
            # EDITOR DE BAIXA RÁPIDA
            # Mostramos apenas colunas essenciais. Bloqueamos edição de valores e nomes aqui para segurança.
            # Apenas Status, Pagamento e Obs ficam livres.
            df_baixa = st.data_editor(
                df_dia,
                column_order=["Status", "Cliente", "Caruru", "Bobo", "Valor", "Pagamento", "Observacoes", "Contato"],
                disabled=["Cliente", "Caruru", "Bobo", "Valor", "Contato"], # Bloqueia edição destes
                hide_index=True,
                use_container_width=True,
                key="editor_dashboard",
                column_config={
                    "Status": st.column_config.SelectboxColumn(
                        "Status Entrega", 
                        options=["Pendente", "Em Produção", "Entregue", "Cancelado"],
                        required=True,
                        width="medium"
                    ),
                    "Observacoes": st.column_config.TextColumn("Obs (Ex: Portaria)", width="large"),
                    "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                    "Pagamento": st.column_config.SelectboxColumn(options=["PAGO", "NÃO PAGO", "METADE"]),
                    "Caruru": st.column_config.NumberColumn(format="%d"),
                    "Bobo": st.column_config.NumberColumn(format="%d"),
                }
            )
            
            # --- LÓGICA DE SALVAMENTO AUTOMÁTICO DA BAIXA ---
            # Se houver diferença entre o original (df) e o editado no dia (df_baixa)
            # Precisamos atualizar o DataFrame principal (st.session_state.pedidos)
            
            # Identifica índices que mudaram
            indices_dia = df_dia.index
            
            # Verifica se houve mudança nos dados exibidos
            mudou = False
            for i in indices_dia:
                # Compara linha atual do banco geral com a linha editada
                # Se Status, Pagamento ou Obs mudou, salvamos
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
                st.toast("✅ Baixa realizada! Status atualizado.", icon="🛵")
                st.rerun()

# --- PÁGINA 2: NOVO PEDIDO ---
elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    
    with st.form("form_pedido", clear_on_submit=True):
        nome = st.text_input("Nome Cliente")
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
            
        col_obs = st.columns(1)[0]
        obs = st.text_area("Observações (Ex: Sem camarão, Entregar na portaria)")
            
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
                "Pagamento": pagamento, "Contato": contato, "Desconto": desconto,
                "Observacoes": obs # Campo novo
            }
            st.session_state.pedidos = pd.concat([st.session_state.pedidos, pd.DataFrame([novo])], ignore_index=True)
            salvar_dados(st.session_state.pedidos)
            st.success("Pedido Salvo!")

# --- PÁGINA 3: GERENCIAR TUDO ---
elif menu == "Gerenciar Tudo":
    st.title("📦 Banco de Dados Completo")
    st.caption("Edição livre de todos os campos e datas.")
    
    df = st.session_state.pedidos
    
    if not df.empty:
        df_editado = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Valor": st.column_config.NumberColumn("Valor Total", format="R$ %.2f", disabled=True),
                "Data": st.column_config.DateColumn("Data Entrega", format="DD/MM/YYYY"),
                "Status": st.column_config.SelectboxColumn(options=["Pendente", "Em Produção", "Entregue", "Cancelado"], required=True),
                "Pagamento": st.column_config.SelectboxColumn(options=["PAGO", "NÃO PAGO", "METADE"], required=True),
                "Caruru": st.column_config.NumberColumn(format="%d", step=1),
                "Bobo": st.column_config.NumberColumn(format="%d", step=1),
                "Observacoes": st.column_config.TextColumn("Obs", width="large"),
            },
            hide_index=True
        )
        
        if not df_editado.equals(df):
            # Recalculo automático de valor
            preco_base = 70.0
            df_editado['Valor'] = ((df_editado['Caruru'] * preco_base) + (df_editado['Bobo'] * preco_base)) * (1 - (df_editado['Desconto'] / 100))
            
            st.session_state.pedidos = df_editado
            salvar_dados(df_editado)
            st.toast("Banco de dados atualizado!", icon="💾")
            st.rerun()
