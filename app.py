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
import shutil

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

    # Se não houver senha nos secrets, libera acesso (modo local)
    if "password" not in st.secrets:
        return True

    st.title("🔒 Acesso Restrito")
    st.text_input("Digite a senha:", type="password", key="password", on_change=password_entered)
    if "password_correct" in st.session_state:
        st.error("Senha incorreta.")
    return False

# Comente a linha abaixo se for rodar localmente sem configuração de secrets
# if not check_password():
#     st.stop()

# ==============================================================================
# CONFIGURAÇÕES E CONSTANTES
# ==============================================================================
ARQUIVO_LOG = "system_errors.log"
ARQUIVO_PEDIDOS = "banco_de_dados_caruru.csv"
ARQUIVO_CLIENTES = "banco_de_dados_clientes.csv"
ARQUIVO_HISTORICO = "historico_alteracoes.csv"
CHAVE_PIX = "79999296722"
OPCOES_STATUS = ["🔴 Pendente", "🟡 Em Produção", "✅ Entregue", "🚫 Cancelado"]
OPCOES_PAGAMENTO = ["PAGO", "NÃO PAGO", "METADE"]
PRECO_BASE = 70.0
VERSAO = "17.1 (Corrigido)"

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
    if len(limpo) in [10, 11]: return limpo, None
    elif len(limpo) in [8, 9]: return limpo, "⚠️ Falta o DDD no telefone"
    elif len(limpo) > 0: return limpo, f"⚠️ Telefone incomum ({len(limpo)} díg.)"
    return "", None

def validar_quantidade(valor, nome_campo):
    try:
        if valor is None or valor == "": return 0.0, None
        v = float(str(valor).replace(",", "."))
        if v < 0: return 0.0, f"⚠️ {nome_campo} negativo. Ajustado para 0."
        if v > 999: return 999.0, f"⚠️ {nome_campo} alto demais. Limitado."
        return round(v, 1), None
    except:
        return 0.0, f"❌ Valor inválido em {nome_campo}."

def validar_desconto(valor):
    try:
        if valor is None or valor == "": return 0.0, None
        v = float(str(valor).replace(",", "."))
        if v < 0: return 0.0, "⚠️ Desconto negativo."
        if v > 100: return 100.0, "⚠️ Desconto max 100%."
        return round(v, 2), None
    except:
        return 0.0, "❌ Desconto inválido."

def validar_data_pedido(data, permitir_passado=False):
    try:
        if data is None: return date.today(), "⚠️ Data vazia. Usando hoje."
        if isinstance(data, str): data = pd.to_datetime(data).date()
        elif isinstance(data, datetime): data = data.date()
        
        hoje = date.today()
        if not permitir_passado and data < hoje: return data, "⚠️ Data no passado."
        return data, None
    except:
        return date.today(), "❌ Data inválida."

def validar_hora(hora):
    try:
        if not hora or str(hora).lower() in ["nan", "nat", "none"]: return time(12, 0), None
        if isinstance(hora, time): return hora, None
        hora_str = str(hora).strip()
        for fmt in ["%H:%M", "%H:%M:%S", "%I:%M %p"]:
            try: return datetime.strptime(hora_str, fmt).time(), None
            except: continue
        return time(12, 0), "⚠️ Hora inválida."
    except:
        return time(12, 0), "⚠️ Erro na hora."

# ==============================================================================
# FUNÇÕES DE CÁLCULO E DADOS
# ==============================================================================
def gerar_id_sequencial(df):
    try:
        if df.empty: return 1
        df['ID_Pedido'] = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
        return int(df['ID_Pedido'].max()) + 1
    except: return 1

def calcular_total(caruru, bobo, desconto):
    try:
        c, _ = validar_quantidade(caruru, "Caruru")
        b, _ = validar_quantidade(bobo, "Bobó")
        d, _ = validar_desconto(desconto)
        subtotal = (c + b) * PRECO_BASE
        total = subtotal * (1 - d / 100)
        return round(total, 2)
    except: return 0.0

def gerar_link_whatsapp(telefone, mensagem):
    tel_limpo = limpar_telefone(telefone)
    if len(tel_limpo) < 10: return None
    msg_encoded = urllib.parse.quote(mensagem)
    return f"https://wa.me/55{tel_limpo}?text={msg_encoded}"

# --- BANCO DE DADOS ---
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
        
        df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.date
        df["Hora"] = df["Hora"].apply(lambda x: validar_hora(x)[0])
        for col in ["Caruru", "Bobo", "Desconto", "Valor"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        
        df['ID_Pedido'] = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
        if df['ID_Pedido'].duplicated().any() or (not df.empty and df['ID_Pedido'].max() == 0):
            df['ID_Pedido'] = range(1, len(df) + 1)

        mapa = {"Pendente": "🔴 Pendente", "Em Produção": "🟡 Em Produção", "Entregue": "✅ Entregue", "Cancelado": "🚫 Cancelado"}
        df['Status'] = df['Status'].replace(mapa)
        df.loc[~df['Status'].isin(OPCOES_STATUS), 'Status'] = "🔴 Pendente"
        
        for c in ["Cliente", "Status", "Pagamento", "Contato", "Observacoes"]:
            df[c] = df[c].fillna("").astype(str)
            
        df.loc[~df['Pagamento'].isin(OPCOES_PAGAMENTO), 'Pagamento'] = "NÃO PAGO"
        return df[colunas_padrao]
    except Exception as e:
        logger.error(f"Erro carregar pedidos: {e}")
        return pd.DataFrame(columns=colunas_padrao)

def salvar_pedidos(df):
    try:
        if os.path.exists(ARQUIVO_PEDIDOS): shutil.copy(ARQUIVO_PEDIDOS, ARQUIVO_PEDIDOS + ".bak")
        salvar = df.copy()
        salvar['Data'] = salvar['Data'].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x)
        salvar['Hora'] = salvar['Hora'].apply(lambda x: x.strftime('%H:%M') if isinstance(x, time) else str(x) if x else "12:00")
        salvar.to_csv(ARQUIVO_PEDIDOS, index=False)
        return True
    except Exception as e:
        logger.error(f"Erro salvar pedidos: {e}")
        return False

def salvar_clientes(df):
    try:
        if os.path.exists(ARQUIVO_CLIENTES): shutil.copy(ARQUIVO_CLIENTES, ARQUIVO_CLIENTES + ".bak")
        df.to_csv(ARQUIVO_CLIENTES, index=False)
        return True
    except Exception as e:
        logger.error(f"Erro salvar clientes: {e}")
        return False

# --- HISTÓRICO ---
def registrar_alteracao(tipo, id_pedido, campo, valor_antigo, valor_novo):
    try:
        registro = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Tipo": tipo, "ID_Pedido": id_pedido, "Campo": campo,
            "Valor_Antigo": str(valor_antigo)[:100], "Valor_Novo": str(valor_novo)[:100]
        }
        if os.path.exists(ARQUIVO_HISTORICO): df = pd.read_csv(ARQUIVO_HISTORICO)
        else: df = pd.DataFrame()
        df = pd.concat([df, pd.DataFrame([registro])], ignore_index=True)
        if len(df) > 1000: df = df.tail(1000)
        df.to_csv(ARQUIVO_HISTORICO, index=False)
    except Exception as e: logger.error(f"Erro auditoria: {e}")

# ==============================================================================
# FUNÇÕES CRUD
# ==============================================================================
def criar_pedido(cliente, caruru, bobo, data, hora, status, pagamento, contato, desconto, observacoes):
    erros = []
    avisos = []
    if not cliente or not cliente.strip(): erros.append("❌ Cliente obrigatório.")
    qc, msg = validar_quantidade(caruru, "Caruru"); 
    if msg: avisos.append(msg)
    qb, msg = validar_quantidade(bobo, "Bobó"); 
    if msg: avisos.append(msg)
    if qc == 0 and qb == 0: erros.append("❌ Pedido vazio (0 itens).")
    dt, msg = validar_data_pedido(data); 
    if msg: avisos.append(msg)
    
    if erros: return None, erros, avisos
    
    df_p = st.session_state.pedidos
    nid = gerar_id_sequencial(df_p)
    val = calcular_total(qc, qb, desconto)
    
    novo = {
        "ID_Pedido": nid, "Cliente": cliente.strip(), "Caruru": qc, "Bobo": qb,
        "Valor": val, "Data": dt, "Hora": hora,
        "Status": status if status in OPCOES_STATUS else "🔴 Pendente",
        "Pagamento": pagamento if pagamento in OPCOES_PAGAMENTO else "NÃO PAGO",
        "Contato": contato, "Desconto": desconto, "Observacoes": observacoes
    }
    st.session_state.pedidos = pd.concat([df_p, pd.DataFrame([novo])], ignore_index=True)
    salvar_pedidos(st.session_state.pedidos)
    registrar_alteracao("CRIAR", nid, "completo", None, f"{cliente} - R${val}")
    return nid, [], avisos

def atualizar_pedido(id_pedido, campos):
    try:
        df = st.session_state.pedidos
        mask = df['ID_Pedido'] == id_pedido
        if not mask.any(): return False, "Pedido não encontrado."
        idx = df[mask].index[0]
        
        for k, v in campos.items():
            df.at[idx, k] = v
        
        if any(c in campos for c in ["Caruru", "Bobo", "Desconto"]):
            df.at[idx, 'Valor'] = calcular_total(df.at[idx, 'Caruru'], df.at[idx, 'Bobo'], df.at[idx, 'Desconto'])
        
        st.session_state.pedidos = df
        salvar_pedidos(df)
        return True, "Pedido atualizado."
    except Exception as e: return False, str(e)

def excluir_pedido(id_pedido, motivo):
    try:
        df = st.session_state.pedidos
        mask = df['ID_Pedido'] == id_pedido
        if not mask.any(): return False, "Pedido não encontrado."
        st.session_state.pedidos = df[~mask].reset_index(drop=True)
        salvar_pedidos(st.session_state.pedidos)
        registrar_alteracao("EXCLUIR", id_pedido, "completo", None, motivo)
        return True, "Pedido excluído."
    except Exception as e: return False, str(e)

def buscar_pedido(id_p):
    df = st.session_state.pedidos
    mask = df['ID_Pedido'] == id_p
    if mask.any(): return df[mask].iloc[0].to_dict()
    return None

# ==============================================================================
# PDF GENERATOR (SIMPLIFICADO)
# ==============================================================================
def desenhar_cabecalho(p, titulo):
    if os.path.exists("logo.png"):
        try: p.drawImage("logo.png", 30, 750, width=100, height=50, mask='auto', preserveAspectRatio=True)
        except: pass
    p.setFont("Helvetica-Bold", 16)
    p.drawString(150, 775, "Cantinho do Caruru")
    p.setFont("Helvetica-Bold", 14)
    p.drawRightString(565, 765, titulo)
    p.line(30, 740, 565, 740)

def gerar_recibo_pdf(dados):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        desenhar_cabecalho(p, f"Pedido #{dados.get('ID_Pedido')}")
        
        y = 700
        p.setFont("Helvetica", 12)
        p.drawString(30, y, f"Cliente: {dados.get('Cliente')} | Tel: {dados.get('Contato')}")
        y -= 20
        p.drawString(30, y, f"Data: {dados.get('Data')} | Hora: {dados.get('Hora')}")
        y -= 40
        
        p.drawString(30, y, "Itens:")
        y -= 20
        if float(dados.get('Caruru', 0)) > 0:
            p.drawString(40, y, f"{int(float(dados.get('Caruru')))}x Caruru Tradicional")
            y -= 20
        if float(dados.get('Bobo', 0)) > 0:
            p.drawString(40, y, f"{int(float(dados.get('Bobo')))}x Bobó de Camarão")
            y -= 20
            
        p.setFont("Helvetica-Bold", 14)
        y -= 20
        p.drawString(30, y, f"Total: R$ {float(dados.get('Valor', 0)):.2f}")
        
        pag = dados.get('Pagamento')
        status_txt = "PAGO ✅" if pag == "PAGO" else ("METADE PAGO ⚠️" if pag == "METADE" else "PENDENTE ❌")
        p.drawString(300, y, f"Status: {status_txt}")
        
        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except Exception as e: return None

def gerar_relatorio_pdf(df, titulo):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        desenhar_cabecalho(p, titulo)
        y = 700
        p.setFont("Helvetica", 10)
        for _, row in df.iterrows():
            if y < 50: p.showPage(); y = 750
            p.drawString(30, y, f"#{row['ID_Pedido']} {row['Cliente'][:20]} - R$ {row['Valor']:.2f} ({row['Status']})")
            y -= 15
        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except: return None

def gerar_lista_clientes_pdf(df):
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        desenhar_cabecalho(p, "Lista de Clientes")
        y = 700
        p.setFont("Helvetica", 10)
        for _, row in df.iterrows():
            if y < 50: p.showPage(); y = 750
            p.drawString(30, y, f"{row['Nome'][:30]} - {row['Contato']}")
            y -= 15
        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except: return None

# ==============================================================================
# INICIALIZAÇÃO DO ESTADO
# ==============================================================================
if 'pedidos' not in st.session_state: st.session_state.pedidos = carregar_pedidos()
if 'clientes' not in st.session_state: st.session_state.clientes = carregar_clientes()
if 'resetar_cliente_novo' not in st.session_state: st.session_state.resetar_cliente_novo = False
if 'cliente_novo_index' not in st.session_state: st.session_state.cliente_novo_index = 0

# ==============================================================================
# LÓGICA DE RESET SEGURO (CORREÇÃO DO CRASH)
# ==============================================================================
# Se a flag estiver ativa, resetamos o índice ANTES de renderizar o widget
if st.session_state.resetar_cliente_novo:
    st.session_state.cliente_novo_index = 0
    st.session_state.resetar_cliente_novo = False

# ==============================================================================
# INTERFACE
# ==============================================================================
with st.sidebar:
    st.title("🦐 Cantinho do Caruru")
    menu = st.radio("Menu", [
        "Dashboard do Dia", "Novo Pedido", "✏️ Editar Pedido", 
        "🗑️ Excluir Pedido", "Gerenciar Tudo", "🖨️ Relatórios", 
        "📢 Promoções", "👥 Clientes", "🛠️ Manutenção"
    ])
    st.divider()
    # Resumo Rápido
    hoje = st.session_state.pedidos[st.session_state.pedidos['Data'] == date.today()]
    st.caption(f"📅 Hoje: {len(hoje)} pedidos")

# --- DASHBOARD (COM CORREÇÃO DE CÁLCULO) ---
if menu == "Dashboard do Dia":
    st.title("🦐 Expedição do Dia")
    df = st.session_state.pedidos
    
    if df.empty:
        st.info("Sem dados.")
    else:
        dt_filter = st.date_input("Data:", date.today(), format="DD/MM/YYYY")
        df_dia = df[df['Data'] == dt_filter].copy()
        
        # --- CORREÇÃO DO CÁLCULO FINANCEIRO ---
        # Função para calcular o quanto falta receber de cada pedido
        def calcular_pendencia(row):
            if row['Pagamento'] == 'PAGO':
                return 0.0
            elif row['Pagamento'] == 'METADE':
                return row['Valor'] / 2  # Falta a outra metade
            else: # PENDENTE / NÃO PAGO
                return row['Valor']      # Falta tudo

        if not df_dia.empty:
            df_dia['Falta_Receber'] = df_dia.apply(calcular_pendencia, axis=1)
            total_falta = df_dia['Falta_Receber'].sum()
        else:
            total_falta = 0.0
            
        c1, c2, c3, c4 = st.columns(4)
        pend = df_dia[(~df_dia['Status'].str.contains("Entregue")) & (~df_dia['Status'].str.contains("Cancelado"))]
        
        c1.metric("🥘 Caruru (Falta)", int(pend['Caruru'].sum()) if not pend.empty else 0)
        c2.metric("🦐 Bobó (Falta)", int(pend['Bobo'].sum()) if not pend.empty else 0)
        c3.metric("💰 Faturamento Total", f"R$ {df_dia['Valor'].sum():,.2f}" if not df_dia.empty else "R$ 0,00")
        # Exibe o valor calculado corretamente (considerando 'Metade')
        c4.metric("📥 A Receber (Real)", f"R$ {total_falta:,.2f}", delta_color="inverse")
        
        st.divider()
        if not df_dia.empty:
            # Editor simplificado
            edited = st.data_editor(
                df_dia,
                column_order=["ID_Pedido", "Hora", "Cliente", "Valor", "Status", "Pagamento"],
                disabled=["ID_Pedido", "Hora", "Cliente", "Valor"],
                hide_index=True,
                key="dash_editor",
                column_config={
                    "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                    "Pagamento": st.column_config.SelectboxColumn(options=OPCOES_PAGAMENTO, required=True),
                }
            )
            # Salvar edições da dashboard
            if not edited.equals(df_dia):
                df_global = st.session_state.pedidos.copy()
                for i, row in edited.iterrows():
                    idx = df_global[df_global['ID_Pedido'] == row['ID_Pedido']].index
                    if not idx.empty:
                        df_global.at[idx[0], 'Status'] = row['Status']
                        df_global.at[idx[0], 'Pagamento'] = row['Pagamento']
                st.session_state.pedidos = df_global
                salvar_pedidos(df_global)
                st.rerun()

# --- NOVO PEDIDO (COM PROTEÇÃO CONTRA CRASH) ---
elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    
    # Carrega Clientes
    try: nomes_cli = sorted(st.session_state.clientes['Nome'].unique().tolist())
    except: nomes_cli = []
    lista_clientes = ["-- Selecione --"] + nomes_cli
    
    # Selectbox fora do form
    # O index é controlado pelo session_state seguro no início do arquivo
    c_sel = st.selectbox("Cliente", lista_clientes, index=st.session_state.cliente_novo_index, key="sel_cliente_novo")
    
    # Atualiza índice se usuário mudar manualmente
    if c_sel in lista_clientes:
        st.session_state.cliente_novo_index = lista_clientes.index(c_sel)

    # Busca contato automático
    contato_auto = ""
    if c_sel and c_sel != "-- Selecione --":
        res = st.session_state.clientes[st.session_state.clientes['Nome'] == c_sel]
        if not res.empty: contato_auto = str(res.iloc[0]['Contato'])

    with st.form("form_novo", clear_on_submit=True):
        c1, c2 = st.columns(2)
        cont = c1.text_input("WhatsApp", value=contato_auto)
        dt = c2.date_input("Data Entrega", date.today(), format="DD/MM/YYYY")
        
        c3, c4, c5 = st.columns(3)
        qc = c3.number_input("Caruru", 0, 999, 0)
        qb = c4.number_input("Bobó", 0, 999, 0)
        dc = c5.number_input("Desconto %", 0, 100, 0)
        
        obs = st.text_area("Observações")
        pg = st.selectbox("Pagamento", OPCOES_PAGAMENTO)
        
        # Botão de salvar
        if st.form_submit_button("💾 SALVAR PEDIDO", type="primary", use_container_width=True):
            nome_final = c_sel if c_sel != "-- Selecione --" else ""
            
            nid, erros, avisos = criar_pedido(
                nome_final, qc, qb, dt, time(12,0), "🔴 Pendente", pg, cont, dc, obs
            )
            
            if erros:
                for e in erros: st.error(e)
            else:
                st.success(f"Pedido #{nid} salvo!")
                for a in avisos: st.warning(a)
                # Ativa flag para limpar o selectbox na próxima rodada
                st.session_state.resetar_cliente_novo = True
                st.rerun()

# --- EDITAR PEDIDO ---
elif menu == "✏️ Editar Pedido":
    st.title("✏️ Editar")
    df = st.session_state.pedidos
    if df.empty: st.warning("Sem pedidos.")
    else:
        pid = st.selectbox("Escolha o Pedido (ID)", df['ID_Pedido'].unique(), format_func=lambda x: f"Pedido #{x}")
        dados = buscar_pedido(pid)
        if dados:
            with st.form("edit_form"):
                st.caption(f"Editando Pedido #{pid} - {dados['Cliente']}")
                st = dados.get('Status')
                nst = st.selectbox("Status", OPCOES_STATUS, index=OPCOES_STATUS.index(st) if st in OPCOES_STATUS else 0)
                npg = st.selectbox("Pagamento", OPCOES_PAGAMENTO, index=OPCOES_PAGAMENTO.index(dados.get('Pagamento')) if dados.get('Pagamento') in OPCOES_PAGAMENTO else 1)
                
                c1, c2 = st.columns(2)
                nc = c1.number_input("Caruru", value=int(dados.get('Caruru',0)))
                nb = c2.number_input("Bobó", value=int(dados.get('Bobo',0)))
                
                if st.form_submit_button("Salvar Alterações"):
                    atualizar_pedido(pid, {"Status": nst, "Pagamento": npg, "Caruru": nc, "Bobo": nb})
                    st.success("Atualizado!")
                    st.rerun()

# --- EXCLUIR PEDIDO ---
elif menu == "🗑️ Excluir Pedido":
    st.title("🗑️ Excluir")
    df = st.session_state.pedidos
    if df.empty: st.warning("Vazio.")
    else:
        pid = st.selectbox("Pedido a Excluir", df['ID_Pedido'].unique())
        if st.button("CONFIRMAR EXCLUSÃO", type="primary"):
            excluir_pedido(pid, "Exclusão manual")
            st.success("Excluído.")
            st.rerun()

# --- GERENCIAR TUDO ---
elif menu == "Gerenciar Tudo":
    st.title("📦 Todos os Pedidos")
    df = st.session_state.pedidos
    if not df.empty:
        # Filtros básicos
        filtro_st = st.multiselect("Filtrar Status", OPCOES_STATUS, default=OPCOES_STATUS)
        df_view = df[df['Status'].isin(filtro_st)]
        
        edited = st.data_editor(
            df_view, 
            column_config={
                "ID_Pedido": st.column_config.NumberColumn(disabled=True),
                "Valor": st.column_config.NumberColumn(disabled=True),
                "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                "Pagamento": st.column_config.SelectboxColumn(options=OPCOES_PAGAMENTO, required=True),
            },
            hide_index=True, use_container_width=True
        )
        if not edited.equals(df_view):
            # Salvar em massa
            df_global = st.session_state.pedidos.copy()
            for i, row in edited.iterrows():
                df_global.loc[df_global['ID_Pedido'] == row['ID_Pedido'], ['Status', 'Pagamento', 'Observacoes']] = [row['Status'], row['Pagamento'], row['Observacoes']]
            st.session_state.pedidos = df_global
            salvar_pedidos(df_global)
            st.rerun()

# --- RELATÓRIOS ---
elif menu == "🖨️ Relatórios":
    st.title("🖨️ Relatórios")
    if st.button("Gerar Relatório Geral (PDF)"):
        pdf = gerar_relatorio_pdf(st.session_state.pedidos, "Relatório Geral")
        if pdf: st.download_button("Baixar PDF", pdf, "relatorio.pdf", "application/pdf")

# --- PROMOÇÕES ---
elif menu == "📢 Promoções":
    st.title("📢 Promoções")
    msg = st.text_area("Texto", "Olá! Hoje tem Caruru!")
    st.info("Copie e cole no WhatsApp Web.")

# --- CLIENTES ---
elif menu == "👥 Clientes":
    st.title("👥 Clientes")
    tab1, tab2 = st.tabs(["Novo", "Lista"])
    with tab1:
        with st.form("novo_cli", clear_on_submit=True):
            n = st.text_input("Nome")
            t = st.text_input("Telefone")
            if st.form_submit_button("Cadastrar"):
                t_limpo, _ = validar_telefone(t)
                novo = pd.DataFrame([{"Nome": n, "Contato": t_limpo, "Observacoes": ""}])
                st.session_state.clientes = pd.concat([st.session_state.clientes, novo], ignore_index=True)
                salvar_clientes(st.session_state.clientes)
                st.success("Cadastrado!")
                st.rerun()
    with tab2:
        st.dataframe(st.session_state.clientes, use_container_width=True)

# --- MANUTENÇÃO ---
elif menu == "🛠️ Manutenção":
    st.title("🛠️ Manutenção")
    if st.button("Limpar Logs"):
        open(ARQUIVO_LOG, 'w').close()
        st.success("Logs limpos.")
    if st.button("Backup Completo"):
        # Cria zip simples
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("pedidos.csv", st.session_state.pedidos.to_csv(index=False))
            z.writestr("clientes.csv", st.session_state.clientes.to_csv(index=False))
        st.download_button("Baixar Backup", buf.getvalue(), "backup.zip", "application/zip")
