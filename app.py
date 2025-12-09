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
VERSAO = "17.0"

logging.basicConfig(filename=ARQUIVO_LOG, level=logging.ERROR, format='%(asctime)s | %(levelname)s | %(message)s', force=True)
logger = logging.getLogger("cantinho")

# ==============================================================================
# FUNÇÕES DE VALIDAÇÃO ROBUSTAS
# ==============================================================================
def limpar_telefone(telefone):
    """Extrai apenas dígitos do telefone."""
    if not telefone:
        return ""
    return re.sub(r'\D', '', str(telefone))

def validar_telefone(telefone):
    """
    Valida e formata telefone brasileiro.
    Retorna: (telefone_limpo, mensagem_erro)
    """
    limpo = limpar_telefone(telefone)
    
    if not limpo:
        return "", None  # Telefone opcional
    
    # Remove 55 inicial se presente
    if limpo.startswith("55") and len(limpo) > 11:
        limpo = limpo[2:]
    
    # Verifica comprimento (10 ou 11 dígitos)
    if len(limpo) == 10:  # Fixo ou celular antigo
        return limpo, None
    elif len(limpo) == 11:  # Celular com 9
        return limpo, None
    elif len(limpo) == 8 or len(limpo) == 9:
        return limpo, "⚠️ Falta o DDD no telefone"
    elif len(limpo) > 0:
        return limpo, f"⚠️ Telefone com formato incomum ({len(limpo)} dígitos)"
    
    return "", None

def validar_quantidade(valor, nome_campo):
    """Valida quantidades com tratamento de erros completo."""
    try:
        if valor is None or valor == "":
            return 0.0, None
        v = float(str(valor).replace(",", "."))
        if v < 0:
            return 0.0, f"⚠️ {nome_campo} não pode ser negativo. Ajustado para 0."
        if v > 999:  # Limite razoável
            return 999.0, f"⚠️ {nome_campo} muito alto. Limitado a 999."
        return round(v, 1), None
    except:
        return 0.0, f"❌ Valor inválido em {nome_campo}. Ajustado para 0."

def validar_desconto(valor):
    """Valida desconto entre 0 e 100."""
    try:
        if valor is None or valor == "":
            return 0.0, None
        v = float(str(valor).replace(",", "."))
        if v < 0:
            return 0.0, "⚠️ Desconto não pode ser negativo."
        if v > 100:
            return 100.0, "⚠️ Desconto limitado a 100%."
        return round(v, 2), None
    except:
        return 0.0, "❌ Desconto inválido."

def validar_data_pedido(data, permitir_passado=False):
    """Valida data do pedido."""
    try:
        if data is None:
            return date.today(), "⚠️ Data não informada. Usando hoje."
        
        if isinstance(data, str):
            data = pd.to_datetime(data).date()
        elif isinstance(data, datetime):
            data = data.date()
        
        hoje = date.today()
        
        if not permitir_passado and data < hoje:
            return data, "⚠️ Data no passado (permitido para edição)."
        
        # Limite de 1 ano no futuro
        limite = hoje.replace(year=hoje.year + 1)
        if data > limite:
            return limite, "⚠️ Data muito distante. Ajustada para 1 ano."
        
        return data, None
    except:
        return date.today(), "❌ Data inválida. Usando hoje."

def validar_hora(hora):
    """Valida e normaliza hora."""
    try:
        if hora is None or hora == "" or str(hora).lower() in ["nan", "nat", "none"]:
            return time(12, 0), None
        
        if isinstance(hora, time):
            return hora, None
        
        # Tenta diversos formatos
        hora_str = str(hora).strip()
        
        for fmt in ["%H:%M", "%H:%M:%S", "%I:%M %p"]:
            try:
                return datetime.strptime(hora_str, fmt).time(), None
            except:
                continue
        
        # Última tentativa com pandas
        parsed = pd.to_datetime(hora_str, errors='coerce')
        if not pd.isna(parsed):
            return parsed.time(), None
        
        return time(12, 0), f"⚠️ Hora '{hora}' inválida. Usando 12:00."
    except Exception as e:
        return time(12, 0), f"⚠️ Erro na hora: usando 12:00."

def limpar_hora_rigoroso(h):
    """Limpa hora de forma rigorosa (compatibilidade)."""
    hora, _ = validar_hora(h)
    return hora

# ==============================================================================
# FUNÇÕES DE CÁLCULO
# ==============================================================================
def gerar_id_sequencial(df):
    """Gera próximo ID sequencial."""
    try:
        if df.empty:
            return 1
        df = df.copy()
        df['ID_Pedido'] = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
        return int(df['ID_Pedido'].max()) + 1
    except:
        return 1

def calcular_total(caruru, bobo, desconto):
    """Calcula total com validação."""
    try:
        c, _ = validar_quantidade(caruru, "Caruru")
        b, _ = validar_quantidade(bobo, "Bobó")
        d, _ = validar_desconto(desconto)
        
        subtotal = (c + b) * PRECO_BASE
        total = subtotal * (1 - d / 100)
        return round(total, 2)
    except:
        return 0.0

def gerar_link_whatsapp(telefone, mensagem):
    """Gera link do WhatsApp com validação."""
    tel_limpo = limpar_telefone(telefone)
    if len(tel_limpo) < 10:
        return None
    
    msg_encoded = urllib.parse.quote(mensagem)
    return f"https://wa.me/55{tel_limpo}?text={msg_encoded}"

# ==============================================================================
# BANCO DE DADOS
# ==============================================================================
def carregar_clientes():
    """Carrega banco de clientes."""
    colunas = ["Nome", "Contato", "Observacoes"]
    if not os.path.exists(ARQUIVO_CLIENTES):
        return pd.DataFrame(columns=colunas)
    try:
        df = pd.read_csv(ARQUIVO_CLIENTES, dtype=str).fillna("")
        for c in colunas:
            if c not in df.columns:
                df[c] = ""
        return df[colunas]
    except Exception as e:
        logger.error(f"Erro carregar clientes: {e}")
        return pd.DataFrame(columns=colunas)

def carregar_pedidos():
    """Carrega banco de pedidos com validação completa."""
    colunas_padrao = ["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]
    if not os.path.exists(ARQUIVO_PEDIDOS):
        return pd.DataFrame(columns=colunas_padrao)
    try:
        df = pd.read_csv(ARQUIVO_PEDIDOS)
        for c in colunas_padrao:
            if c not in df.columns:
                df[c] = None
        
        # Conversões seguras
        df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.date
        df["Hora"] = df["Hora"].apply(lambda x: validar_hora(x)[0])
        
        for col in ["Caruru", "Bobo", "Desconto", "Valor"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        
        df['ID_Pedido'] = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
        if df['ID_Pedido'].duplicated().any() or (not df.empty and df['ID_Pedido'].max() == 0):
            df['ID_Pedido'] = range(1, len(df) + 1)
        
        # Normaliza status
        mapa = {"Pendente": "🔴 Pendente", "Em Produção": "🟡 Em Produção", "Entregue": "✅ Entregue", "Cancelado": "🚫 Cancelado"}
        df['Status'] = df['Status'].replace(mapa)
        
        # Garante status válido
        df.loc[~df['Status'].isin(OPCOES_STATUS), 'Status'] = "🔴 Pendente"
        
        for c in ["Cliente", "Status", "Pagamento", "Contato", "Observacoes"]:
            df[c] = df[c].fillna("").astype(str)
        
        # Garante pagamento válido
        df.loc[~df['Pagamento'].isin(OPCOES_PAGAMENTO), 'Pagamento'] = "NÃO PAGO"
            
        return df[colunas_padrao]
    except Exception as e:
        logger.error(f"Erro carregar pedidos: {e}")
        return pd.DataFrame(columns=colunas_padrao)

def salvar_pedidos(df):
    """Salva pedidos com backup automático."""
    try:
        # Backup antes de salvar
        if os.path.exists(ARQUIVO_PEDIDOS):
            backup = ARQUIVO_PEDIDOS + ".bak"
            import shutil
            shutil.copy(ARQUIVO_PEDIDOS, backup)
        
        salvar = df.copy()
        salvar['Data'] = salvar['Data'].apply(lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x)
        salvar['Hora'] = salvar['Hora'].apply(lambda x: x.strftime('%H:%M') if isinstance(x, time) else str(x) if x else "12:00")
        salvar.to_csv(ARQUIVO_PEDIDOS, index=False)
        return True
    except Exception as e:
        logger.error(f"Erro salvar pedidos: {e}")
        return False

def salvar_clientes(df):
    """Salva clientes com backup."""
    try:
        if os.path.exists(ARQUIVO_CLIENTES):
            backup = ARQUIVO_CLIENTES + ".bak"
            import shutil
            shutil.copy(ARQUIVO_CLIENTES, backup)
        df.to_csv(ARQUIVO_CLIENTES, index=False)
        return True
    except Exception as e:
        logger.error(f"Erro salvar clientes: {e}")
        return False

# ==============================================================================
# HISTÓRICO DE ALTERAÇÕES
# ==============================================================================
def registrar_alteracao(tipo, id_pedido, campo, valor_antigo, valor_novo):
    """Registra alterações para auditoria."""
    try:
        registro = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Tipo": tipo,
            "ID_Pedido": id_pedido,
            "Campo": campo,
            "Valor_Antigo": str(valor_antigo)[:100],
            "Valor_Novo": str(valor_novo)[:100]
        }
        
        if os.path.exists(ARQUIVO_HISTORICO):
            df = pd.read_csv(ARQUIVO_HISTORICO)
        else:
            df = pd.DataFrame()
        
        df = pd.concat([df, pd.DataFrame([registro])], ignore_index=True)
        
        # Mantém apenas últimos 1000 registros
        if len(df) > 1000:
            df = df.tail(1000)
        
        df.to_csv(ARQUIVO_HISTORICO, index=False)
    except Exception as e:
        logger.error(f"Erro registrar alteração: {e}")

# ==============================================================================
# FUNÇÕES DE PEDIDO (CRUD)
# ==============================================================================
def criar_pedido(cliente, caruru, bobo, data, hora, status, pagamento, contato, desconto, observacoes):
    """Cria novo pedido com validação completa."""
    erros = []
    avisos = []
    
    # Validações
    if not cliente or not cliente.strip():
        erros.append("❌ Cliente é obrigatório.")
    
    qc, msg = validar_quantidade(caruru, "Caruru")
    if msg: avisos.append(msg)
    
    qb, msg = validar_quantidade(bobo, "Bobó")
    if msg: avisos.append(msg)
    
    if qc == 0 and qb == 0:
        erros.append("❌ Pedido deve ter pelo menos 1 item (Caruru ou Bobó).")
    
    dc, msg = validar_desconto(desconto)
    if msg: avisos.append(msg)
    
    dt, msg = validar_data_pedido(data, permitir_passado=False)
    if msg: avisos.append(msg)
    
    hr, msg = validar_hora(hora)
    if msg: avisos.append(msg)
    
    tel, msg = validar_telefone(contato)
    if msg: avisos.append(msg)
    
    if erros:
        return None, erros, avisos
    
    # Cria pedido
    df_p = st.session_state.pedidos
    nid = gerar_id_sequencial(df_p)
    val = calcular_total(qc, qb, dc)
    
    novo = {
        "ID_Pedido": nid,
        "Cliente": cliente.strip(),
        "Caruru": qc,
        "Bobo": qb,
        "Valor": val,
        "Data": dt,
        "Hora": hr,
        "Status": status if status in OPCOES_STATUS else "🔴 Pendente",
        "Pagamento": pagamento if pagamento in OPCOES_PAGAMENTO else "NÃO PAGO",
        "Contato": tel,
        "Desconto": dc,
        "Observacoes": observacoes.strip() if observacoes else ""
    }
    
    df_novo = pd.DataFrame([novo])
    st.session_state.pedidos = pd.concat([df_p, df_novo], ignore_index=True)
    salvar_pedidos(st.session_state.pedidos)
    registrar_alteracao("CRIAR", nid, "pedido_completo", None, f"{cliente} - R${val}")
    
    return nid, [], avisos

def atualizar_pedido(id_pedido, campos_atualizar):
    """Atualiza pedido existente."""
    try:
        df = st.session_state.pedidos
        mask = df['ID_Pedido'] == id_pedido
        
        if not mask.any():
            return False, f"❌ Pedido #{id_pedido} não encontrado."
        
        idx = df[mask].index[0]
        
        for campo, valor in campos_atualizar.items():
            valor_antigo = df.at[idx, campo]
            
            # Validações específicas por campo
            if campo == "Caruru":
                valor, _ = validar_quantidade(valor, "Caruru")
            elif campo == "Bobo":
                valor, _ = validar_quantidade(valor, "Bobó")
            elif campo == "Desconto":
                valor, _ = validar_desconto(valor)
            elif campo == "Data":
                valor, _ = validar_data_pedido(valor, permitir_passado=True)
            elif campo == "Hora":
                valor, _ = validar_hora(valor)
            elif campo == "Contato":
                valor, _ = validar_telefone(valor)
            elif campo == "Status":
                if valor not in OPCOES_STATUS:
                    valor = "🔴 Pendente"
            elif campo == "Pagamento":
                if valor not in OPCOES_PAGAMENTO:
                    valor = "NÃO PAGO"
            
            df.at[idx, campo] = valor
            registrar_alteracao("EDITAR", id_pedido, campo, valor_antigo, valor)
        
        # Recalcula valor se necessário
        if any(c in campos_atualizar for c in ["Caruru", "Bobo", "Desconto"]):
            df.at[idx, 'Valor'] = calcular_total(
                df.at[idx, 'Caruru'],
                df.at[idx, 'Bobo'],
                df.at[idx, 'Desconto']
            )
        
        st.session_state.pedidos = df
        salvar_pedidos(df)
        return True, f"✅ Pedido #{id_pedido} atualizado."
    
    except Exception as e:
        logger.error(f"Erro atualizar pedido: {e}")
        return False, f"❌ Erro ao atualizar: {e}"

def excluir_pedido(id_pedido, motivo=""):
    """Exclui pedido com registro."""
    try:
        df = st.session_state.pedidos
        mask = df['ID_Pedido'] == id_pedido
        
        if not mask.any():
            return False, f"❌ Pedido #{id_pedido} não encontrado."
        
        pedido = df[mask].iloc[0]
        cliente = pedido.get('Cliente', 'Desconhecido')
        
        # Remove do DataFrame
        st.session_state.pedidos = df[~mask].reset_index(drop=True)
        salvar_pedidos(st.session_state.pedidos)
        
        registrar_alteracao("EXCLUIR", id_pedido, "pedido_completo", f"{cliente}", motivo or "Sem motivo")
        
        return True, f"✅ Pedido #{id_pedido} ({cliente}) excluído."
    
    except Exception as e:
        logger.error(f"Erro excluir pedido: {e}")
        return False, f"❌ Erro ao excluir: {e}"

def buscar_pedido(id_pedido):
    """Busca pedido por ID."""
    df = st.session_state.pedidos
    mask = df['ID_Pedido'] == id_pedido
    if mask.any():
        return df[mask].iloc[0].to_dict()
    return None

# ==============================================================================
# PDF GENERATOR
# ==============================================================================
def desenhar_cabecalho(p, titulo):
    """Desenha cabeçalho padrão no PDF."""
    if os.path.exists("logo.png"):
        try:
            p.drawImage("logo.png", 30, 750, width=100, height=50, mask='auto', preserveAspectRatio=True)
        except:
            pass
    p.setFont("Helvetica-Bold", 16)
    p.drawString(150, 775, "Cantinho do Caruru")
    p.setFont("Helvetica", 10)
    p.drawString(150, 760, "Comprovante / Relatório")
    p.setFont("Helvetica-Bold", 14)
    p.drawRightString(565, 765, titulo)
    p.setLineWidth(1)
    p.line(30, 740, 565, 740)

def gerar_recibo_pdf(dados):
    """Gera recibo individual em PDF."""
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        id_p = dados.get('ID_Pedido', 'NOVO')
        desenhar_cabecalho(p, f"Pedido #{id_p}")

        y = 700
        p.setFont("Helvetica-Bold", 12)
        p.drawString(30, y, "DADOS DO CLIENTE")
        y -= 20
        p.setFont("Helvetica", 12)
        p.drawString(30, y, f"Nome: {dados.get('Cliente', '')}")
        p.drawString(300, y, f"WhatsApp: {dados.get('Contato', '')}")
        y -= 20
        
        dt = dados.get('Data')
        dt_s = dt.strftime('%d/%m/%Y') if hasattr(dt, 'strftime') else str(dt)
        hr = dados.get('Hora')
        hr_s = hr.strftime('%H:%M') if isinstance(hr, time) else str(hr)[:5] if hr else "12:00"
        p.drawString(30, y, f"Data: {dt_s}")
        p.drawString(300, y, f"Hora: {hr_s}")
        
        y -= 40
        p.setFillColor(colors.lightgrey)
        p.rect(30, y - 5, 535, 20, fill=1, stroke=0)
        p.setFillColor(colors.black)
        p.setFont("Helvetica-Bold", 10)
        p.drawString(40, y, "ITEM")
        p.drawString(350, y, "QTD")
        p.drawString(450, y, "UNIT")
        y -= 25
        p.setFont("Helvetica", 10)
        
        if float(dados.get('Caruru', 0)) > 0:
            p.drawString(40, y, "Caruru Tradicional")
            p.drawString(350, y, f"{int(float(dados.get('Caruru')))}")
            p.drawString(450, y, f"R$ {PRECO_BASE:.2f}")
            y -= 15
        if float(dados.get('Bobo', 0)) > 0:
            p.drawString(40, y, "Bobó de Camarão")
            p.drawString(350, y, f"{int(float(dados.get('Bobo')))}")
            p.drawString(450, y, f"R$ {PRECO_BASE:.2f}")
            y -= 15
        
        if float(dados.get('Desconto', 0)) > 0:
            y -= 10
            p.setFont("Helvetica-Oblique", 10)
            p.drawString(40, y, f"Desconto aplicado: {float(dados.get('Desconto')):.0f}%")
            y -= 15
        
        p.line(30, y - 5, 565, y - 5)
        
        y -= 40
        p.setFont("Helvetica-Bold", 14)
        lbl = "TOTAL PAGO" if dados.get('Pagamento') == "PAGO" else "VALOR A PAGAR"
        p.drawString(350, y, f"{lbl}: R$ {float(dados.get('Valor', 0)):.2f}")
        
        y -= 25
        p.setFont("Helvetica-Bold", 12)
        sit = dados.get('Pagamento')
        if sit == "PAGO":
            p.setFillColor(colors.green)
            p.drawString(30, y + 25, "SITUAÇÃO: PAGO ✅")
        elif sit == "METADE":
            p.setFillColor(colors.orange)
            p.drawString(30, y + 25, "SITUAÇÃO: METADE PAGO ⚠️")
            p.setFillColor(colors.black)
            p.setFont("Helvetica", 10)
            p.drawString(30, y, f"Pix para pagamento restante: {CHAVE_PIX}")
        else:
            p.setFillColor(colors.red)
            p.drawString(30, y + 25, "SITUAÇÃO: PENDENTE ❌")
            p.setFillColor(colors.black)
            p.setFont("Helvetica", 10)
            p.drawString(30, y, f"Pix: {CHAVE_PIX}")
        
        p.setFillColor(colors.black)
        if dados.get('Observacoes'):
            y -= 30
            p.setFont("Helvetica-Oblique", 10)
            p.drawString(30, y, f"Obs: {dados.get('Observacoes')[:80]}")
            
        y_ass = 150
        p.setLineWidth(1)
        p.line(150, y_ass, 450, y_ass)
        p.setFont("Helvetica", 10)
        p.drawCentredString(300, y_ass - 15, "Cantinho do Caruru")
        p.setFont("Helvetica-Oblique", 8)
        p.drawCentredString(300, y_ass - 30, f"Emitido em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        
        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.error(f"Erro gerar recibo PDF: {e}")
        return None

def gerar_relatorio_pdf(df_filtrado, titulo_relatorio):
    """Gera relatório geral em PDF."""
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        y = 700
        desenhar_cabecalho(p, titulo_relatorio)
        
        p.setFont("Helvetica-Bold", 9)
        cols = [30, 55, 100, 200, 240, 280, 330, 400, 480]
        hdrs = ["ID", "Data", "Cliente", "Car", "Bob", "Valor", "Status", "Pagto", "Hora"]
        for x, h in zip(cols, hdrs):
            p.drawString(x, y, h)
        y -= 20
        p.setFont("Helvetica", 8)
        total = 0
        
        for _, row in df_filtrado.iterrows():
            if y < 60:
                p.showPage()
                desenhar_cabecalho(p, titulo_relatorio)
                y = 700
                p.setFont("Helvetica-Bold", 9)
                for x, h in zip(cols, hdrs):
                    p.drawString(x, y, h)
                y -= 20
                p.setFont("Helvetica", 8)
            
            d_s = row['Data'].strftime('%d/%m') if hasattr(row['Data'], 'strftime') else ""
            h_s = row['Hora'].strftime('%H:%M') if isinstance(row['Hora'], time) else str(row['Hora'])[:5] if row['Hora'] else ""
            st_cl = str(row['Status']).replace("🔴", "").replace("✅", "").replace("🟡", "").replace("🚫", "").strip()[:12]
            
            p.drawString(30, y, str(row.get('ID_Pedido', '')))
            p.drawString(55, y, d_s)
            p.drawString(100, y, str(row.get('Cliente', ''))[:15])
            p.drawString(200, y, str(int(row.get('Caruru', 0))))
            p.drawString(240, y, str(int(row.get('Bobo', 0))))
            p.drawString(280, y, f"{row.get('Valor', 0):.2f}")
            p.drawString(330, y, st_cl)
            p.drawString(400, y, str(row.get('Pagamento', ''))[:10])
            p.drawString(480, y, h_s)
            
            total += row.get('Valor', 0)
            y -= 12
        
        p.line(30, y, 565, y)
        p.setFont("Helvetica-Bold", 11)
        p.drawString(280, y - 20, f"TOTAL GERAL: R$ {total:,.2f}")
        p.setFont("Helvetica", 9)
        p.drawString(30, y - 20, f"Total de pedidos: {len(df_filtrado)}")
        
        p.setFont("Helvetica-Oblique", 8)
        p.drawString(30, 30, f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        
        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.error(f"Erro gerar relatório PDF: {e}")
        return None

def gerar_lista_clientes_pdf(df_clientes):
    """Gera PDF com lista de clientes."""
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        desenhar_cabecalho(p, "Lista de Clientes")
        
        y = 700
        p.setFont("Helvetica-Bold", 10)
        p.drawString(30, y, "NOME")
        p.drawString(220, y, "CONTATO")
        p.drawString(350, y, "OBSERVAÇÕES")
        y -= 5
        p.line(30, y, 565, y)
        y -= 15
        
        p.setFont("Helvetica", 9)
        for _, row in df_clientes.iterrows():
            if y < 50:
                p.showPage()
                desenhar_cabecalho(p, "Lista de Clientes")
                y = 700
                p.setFont("Helvetica-Bold", 10)
                p.drawString(30, y, "NOME")
                p.drawString(220, y, "CONTATO")
                p.drawString(350, y, "OBSERVAÇÕES")
                y -= 5
                p.line(30, y, 565, y)
                y -= 15
                p.setFont("Helvetica", 9)
            
            p.drawString(30, y, str(row.get('Nome', ''))[:28])
            p.drawString(220, y, str(row.get('Contato', ''))[:18])
            p.drawString(350, y, str(row.get('Observacoes', ''))[:30])
            y -= 12
        
        p.line(30, y, 565, y)
        p.setFont("Helvetica-Oblique", 8)
        p.drawString(30, 30, f"Total: {len(df_clientes)} clientes | Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        
        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.error(f"Erro gerar PDF clientes: {e}")
        return None

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
        
        # Ordenar por hora
        try:
            df_dia['h_sort'] = df_dia['Hora'].apply(lambda x: x if isinstance(x, time) else time(23, 59))
            df_dia = df_dia.sort_values('h_sort').drop(columns=['h_sort'])
        except:
            pass
        
        # Métricas
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
            # Editor de dados
            edited = st.data_editor(
                df_dia,
                column_order=["ID_Pedido", "Hora", "Status", "Cliente", "Caruru", "Bobo", "Valor", "Pagamento", "Observacoes"],
                disabled=["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Hora"],
                hide_index=True,
                use_container_width=True,
                key="dash_editor",
                column_config={
                    "ID_Pedido": st.column_config.NumberColumn("#", width="small"),
                    "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                    "Pagamento": st.column_config.SelectboxColumn(options=OPCOES_PAGAMENTO, required=True),
                    "Hora": st.column_config.TimeColumn(format="HH:mm"),
                    "Valor": st.column_config.NumberColumn(format="R$ %.2f")
                }
            )
            
            # Detecta mudanças
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
    
    try:
        clis = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
    except:
        clis = []
    
    def update_cont():
        sel = st.session_state.get("sel_cli")
        if sel:
            res = st.session_state.clientes[st.session_state.clientes['Nome'] == sel]
            st.session_state["auto_contato"] = res.iloc[0]['Contato'] if not res.empty else ""
        else:
            st.session_state["auto_contato"] = ""

    st.markdown("### 1️⃣ Cliente")
    c1, c2 = st.columns([3, 1])
    with c1:
        c_sel = st.selectbox("Nome do Cliente", [""] + clis, key="sel_cli", on_change=update_cont)
    with c2:
        h_ent = st.time_input("⏰ Hora Entrega", value=time(12, 0))
    
    if not c_sel:
        st.info("💡 Selecione um cliente cadastrado ou cadastre um novo em '👥 Cadastrar Clientes'")
    
    st.markdown("### 2️⃣ Dados do Pedido")
    with st.form("form_novo", clear_on_submit=True):
        c1, c2 = st.columns(2)
        with c1:
            cont = st.text_input("📱 WhatsApp", key="auto_contato", placeholder="79999999999")
        with c2:
            dt = st.date_input("📅 Data Entrega", min_value=date.today(), format="DD/MM/YYYY")
        
        c3, c4, c5 = st.columns(3)
        with c3:
            qc = st.number_input("🥘 Caruru (qtd)", min_value=0.0, max_value=999.0, step=1.0, value=0.0)
        with c4:
            qb = st.number_input("🦐 Bobó (qtd)", min_value=0.0, max_value=999.0, step=1.0, value=0.0)
        with c5:
            dc = st.number_input("💸 Desconto %", min_value=0, max_value=100, step=5, value=0)
        
        # Preview do valor
        valor_preview = calcular_total(qc, qb, dc)
        st.info(f"💵 **Valor estimado: R$ {valor_preview:.2f}**")
        
        obs = st.text_area("📝 Observações", placeholder="Ex: Sem pimenta, entregar na portaria...")
        
        c6, c7 = st.columns(2)
        with c6:
            pg = st.selectbox("💳 Pagamento", OPCOES_PAGAMENTO)
        with c7:
            stt = st.selectbox("📊 Status", OPCOES_STATUS)
        
        submitted = st.form_submit_button("💾 SALVAR PEDIDO", use_container_width=True, type="primary")
        
        if submitted:
            id_criado, erros, avisos = criar_pedido(
                cliente=c_sel,
                caruru=qc,
                bobo=qb,
                data=dt,
                hora=h_ent,
                status=stt,
                pagamento=pg,
                contato=cont,
                desconto=dc,
                observacoes=obs
            )
            
            for aviso in avisos:
                st.warning(aviso)
            
            if erros:
                for erro in erros:
                    st.error(erro)
            else:
                st.success(f"✅ Pedido #{id_criado} criado com sucesso!")
                st.balloons()
                st.rerun()

# --- EDITAR PEDIDO ---
elif menu == "✏️ Editar Pedido":
    st.title("✏️ Editar Pedido")
    
    df = st.session_state.pedidos
    
    if df.empty:
        st.warning("Nenhum pedido cadastrado.")
    else:
        # Filtros de busca
        st.markdown("### 🔍 Localizar Pedido")
        c1, c2, c3 = st.columns([1, 2, 2])
        
        with c1:
            busca_id = st.number_input("Buscar por ID", min_value=0, value=0, step=1)
        with c2:
            clientes_unicos = ["Todos"] + sorted(df['Cliente'].unique().tolist())
            filtro_cliente = st.selectbox("Filtrar por Cliente", clientes_unicos)
        with c3:
            filtro_data = st.date_input("Filtrar por Data", value=None, format="DD/MM/YYYY")
        
        # Aplica filtros
        df_filtrado = df.copy()
        if busca_id > 0:
            df_filtrado = df_filtrado[df_filtrado['ID_Pedido'] == busca_id]
        if filtro_cliente != "Todos":
            df_filtrado = df_filtrado[df_filtrado['Cliente'] == filtro_cliente]
        if filtro_data:
            df_filtrado = df_filtrado[df_filtrado['Data'] == filtro_data]
        
        if df_filtrado.empty:
            st.info("Nenhum pedido encontrado com os filtros aplicados.")
        else:
            # Lista de pedidos para selecionar
            df_filtrado = df_filtrado.sort_values(['Data', 'ID_Pedido'], ascending=[False, False])
            
            opcoes_pedido = {
                row['ID_Pedido']: f"#{row['ID_Pedido']} | {row['Cliente']} | {row['Data'].strftime('%d/%m/%Y') if hasattr(row['Data'], 'strftime') else row['Data']} | R$ {row['Valor']:.2f} | {row['Status']}"
                for _, row in df_filtrado.iterrows()
            }
            
            pedido_selecionado = st.selectbox(
                "Selecione o pedido para editar:",
                options=list(opcoes_pedido.keys()),
                format_func=lambda x: opcoes_pedido[x]
            )
            
            if pedido_selecionado:
                pedido = buscar_pedido(pedido_selecionado)
                
                if pedido:
                    st.divider()
                    st.markdown(f"### 📝 Editando Pedido #{pedido_selecionado}")
                    
                    with st.form("form_editar"):
                        c1, c2 = st.columns(2)
                        
                        with c1:
                            # Lista de clientes para seleção
                            try:
                                clis = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
                            except:
                                clis = []
                            
                            cliente_atual = pedido.get('Cliente', '')
                            if cliente_atual and cliente_atual not in clis:
                                clis = [cliente_atual] + clis
                            
                            idx_cliente = clis.index(cliente_atual) if cliente_atual in clis else 0
                            novo_cliente = st.selectbox("👤 Cliente", clis, index=idx_cliente)
                            
                            nova_data = st.date_input(
                                "📅 Data",
                                value=pedido.get('Data') or date.today(),
                                format="DD/MM/YYYY"
                            )
                            
                            hora_atual = pedido.get('Hora')
                            if not isinstance(hora_atual, time):
                                hora_atual = time(12, 0)
                            nova_hora = st.time_input("⏰ Hora", value=hora_atual)
                        
                        with c2:
                            novo_contato = st.text_input("📱 Contato", value=str(pedido.get('Contato', '')))
                            
                            novo_status = st.selectbox(
                                "📊 Status",
                                OPCOES_STATUS,
                                index=OPCOES_STATUS.index(pedido.get('Status', '🔴 Pendente')) if pedido.get('Status') in OPCOES_STATUS else 0
                            )
                            
                            novo_pagamento = st.selectbox(
                                "💳 Pagamento",
                                OPCOES_PAGAMENTO,
                                index=OPCOES_PAGAMENTO.index(pedido.get('Pagamento', 'NÃO PAGO')) if pedido.get('Pagamento') in OPCOES_PAGAMENTO else 1
                            )
                        
                        st.markdown("#### 🍽️ Itens")
                        c3, c4, c5 = st.columns(3)
                        
                        with c3:
                            novo_caruru = st.number_input(
                                "🥘 Caruru",
                                min_value=0.0, max_value=999.0, step=1.0,
                                value=float(pedido.get('Caruru', 0))
                            )
                        with c4:
                            novo_bobo = st.number_input(
                                "🦐 Bobó",
                                min_value=0.0, max_value=999.0, step=1.0,
                                value=float(pedido.get('Bobo', 0))
                            )
                        with c5:
                            novo_desconto = st.number_input(
                                "💸 Desconto %",
                                min_value=0, max_value=100, step=5,
                                value=int(pedido.get('Desconto', 0))
                            )
                        
                        # Preview do novo valor
                        novo_valor = calcular_total(novo_caruru, novo_bobo, novo_desconto)
                        valor_anterior = pedido.get('Valor', 0)
                        
                        if novo_valor != valor_anterior:
                            st.warning(f"💵 Valor anterior: R$ {valor_anterior:.2f} → **Novo: R$ {novo_valor:.2f}**")
                        else:
                            st.info(f"💵 Valor: R$ {novo_valor:.2f}")
                        
                        nova_obs = st.text_area("📝 Observações", value=str(pedido.get('Observacoes', '')))
                        
                        col_btn1, col_btn2 = st.columns(2)
                        with col_btn1:
                            btn_salvar = st.form_submit_button("💾 SALVAR ALTERAÇÕES", use_container_width=True, type="primary")
                        with col_btn2:
                            btn_cancelar = st.form_submit_button("❌ Cancelar", use_container_width=True)
                        
                        if btn_salvar:
                            # Validação básica
                            if novo_caruru == 0 and novo_bobo == 0:
                                st.error("❌ Pedido deve ter pelo menos 1 item.")
                            else:
                                campos = {
                                    "Cliente": novo_cliente,
                                    "Data": nova_data,
                                    "Hora": nova_hora,
                                    "Contato": novo_contato,
                                    "Status": novo_status,
                                    "Pagamento": novo_pagamento,
                                    "Caruru": novo_caruru,
                                    "Bobo": novo_bobo,
                                    "Desconto": novo_desconto,
                                    "Observacoes": nova_obs
                                }
                                
                                sucesso, msg = atualizar_pedido(pedido_selecionado, campos)
                                
                                if sucesso:
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)
                        
                        if btn_cancelar:
                            st.rerun()

# --- EXCLUIR PEDIDO ---
elif menu == "🗑️ Excluir Pedido":
    st.title("🗑️ Excluir Pedido")
    
    df = st.session_state.pedidos
    
    if df.empty:
        st.warning("Nenhum pedido cadastrado.")
    else:
        st.warning("⚠️ **Atenção:** A exclusão é permanente! Use com cuidado.")
        
        st.markdown("### 🔍 Localizar Pedido")
        c1, c2 = st.columns(2)
        
        with c1:
            busca_id_del = st.number_input("Buscar por ID", min_value=0, value=0, step=1, key="del_id")
        with c2:
            clientes_del = ["Todos"] + sorted(df['Cliente'].unique().tolist())
            filtro_cliente_del = st.selectbox("Filtrar por Cliente", clientes_del, key="del_cli")
        
        # Aplica filtros
        df_del = df.copy()
        if busca_id_del > 0:
            df_del = df_del[df_del['ID_Pedido'] == busca_id_del]
        if filtro_cliente_del != "Todos":
            df_del = df_del[df_del['Cliente'] == filtro_cliente_del]
        
        if df_del.empty:
            st.info("Nenhum pedido encontrado.")
        else:
            df_del = df_del.sort_values(['Data', 'ID_Pedido'], ascending=[False, False])
            
            opcoes_del = {
                row['ID_Pedido']: f"#{row['ID_Pedido']} | {row['Cliente']} | {row['Data'].strftime('%d/%m/%Y') if hasattr(row['Data'], 'strftime') else row['Data']} | R$ {row['Valor']:.2f}"
                for _, row in df_del.iterrows()
            }
            
            pedido_excluir = st.selectbox(
                "Selecione o pedido para EXCLUIR:",
                options=list(opcoes_del.keys()),
                format_func=lambda x: opcoes_del[x],
                key="sel_del"
            )
            
            if pedido_excluir:
                pedido_info = buscar_pedido(pedido_excluir)
                
                if pedido_info:
                    st.divider()
                    
                    # Mostra detalhes do pedido
                    st.markdown(f"### 📋 Detalhes do Pedido #{pedido_excluir}")
                    
                    c1, c2, c3 = st.columns(3)
                    c1.write(f"**Cliente:** {pedido_info.get('Cliente')}")
                    c2.write(f"**Data:** {pedido_info.get('Data')}")
                    c3.write(f"**Valor:** R$ {pedido_info.get('Valor', 0):.2f}")
                    
                    c4, c5, c6 = st.columns(3)
                    c4.write(f"**Caruru:** {int(pedido_info.get('Caruru', 0))}")
                    c5.write(f"**Bobó:** {int(pedido_info.get('Bobo', 0))}")
                    c6.write(f"**Status:** {pedido_info.get('Status')}")
                    
                    st.divider()
                    
                    # Confirmação de exclusão
                    motivo = st.text_input("📝 Motivo da exclusão (opcional):", placeholder="Ex: Pedido duplicado, cliente cancelou...")
                    
                    st.markdown("---")
                    
                    # Checkbox de confirmação
                    confirma = st.checkbox(f"✅ Confirmo que desejo excluir o pedido #{pedido_excluir} permanentemente")
                    
                    if st.button("🗑️ EXCLUIR PEDIDO", type="primary", disabled=not confirma, use_container_width=True):
                        sucesso, msg = excluir_pedido(pedido_excluir, motivo)
                        
                        if sucesso:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

# --- GERENCIAR TUDO ---
elif menu == "Gerenciar Tudo":
    st.title("📦 Todos os Pedidos")
    
    df = st.session_state.pedidos
    
    if not df.empty:
        # Ordenação
        try:
            df['sort_hora'] = df['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
            df = df.sort_values(['Data', 'sort_hora'], ascending=[False, True]).drop(columns=['sort_hora'])
        except:
            pass
        
        # Filtros
        with st.expander("🔍 Filtros", expanded=False):
            c1, c2, c3 = st.columns(3)
            with c1:
                f_status = st.multiselect("Status", OPCOES_STATUS, default=OPCOES_STATUS)
            with c2:
                f_pagto = st.multiselect("Pagamento", OPCOES_PAGAMENTO, default=OPCOES_PAGAMENTO)
            with c3:
                f_periodo = st.selectbox("Período", ["Todos", "Hoje", "Esta Semana", "Este Mês"])
        
        df_view = df.copy()
        df_view = df_view[df_view['Status'].isin(f_status)]
        df_view = df_view[df_view['Pagamento'].isin(f_pagto)]
        
        if f_periodo == "Hoje":
            df_view = df_view[df_view['Data'] == date.today()]
        elif f_periodo == "Esta Semana":
            inicio_semana = date.today() - timedelta(days=date.today().weekday())
            df_view = df_view[df_view['Data'] >= inicio_semana]
        elif f_periodo == "Este Mês":
            inicio_mes = date.today().replace(day=1)
            df_view = df_view[df_view['Data'] >= inicio_mes]
        
        # Métricas
        st.markdown(f"**{len(df_view)}** pedidos encontrados | **Total:** R$ {df_view['Valor'].sum():,.2f}")
        
        # Editor
        edited = st.data_editor(
            df_view,
            num_rows="fixed",
            use_container_width=True,
            hide_index=True,
            column_config={
                "ID_Pedido": st.column_config.NumberColumn("#", disabled=True, width="small"),
                "Valor": st.column_config.NumberColumn("Total", format="R$ %.2f", disabled=True),
                "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "Hora": st.column_config.TimeColumn("Hora", format="HH:mm"),
                "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                "Pagamento": st.column_config.SelectboxColumn(options=OPCOES_PAGAMENTO, required=True),
                "Caruru": st.column_config.NumberColumn("Caruru", min_value=0, max_value=999),
                "Bobo": st.column_config.NumberColumn("Bobó", min_value=0, max_value=999),
                "Desconto": st.column_config.NumberColumn("Desc %", min_value=0, max_value=100),
            }
        )
        
        # Salva alterações
        if not edited.equals(df_view):
            try:
                # Recalcula valores
                edited['Valor'] = edited.apply(
                    lambda row: calcular_total(row['Caruru'], row['Bobo'], row['Desconto']),
                    axis=1
                )
                
                # Atualiza no DataFrame principal
                df_master = st.session_state.pedidos.copy()
                for idx in edited.index:
                    id_ped = edited.at[idx, 'ID_Pedido']
                    mask = df_master['ID_Pedido'] == id_ped
                    if mask.any():
                        for col in edited.columns:
                            if col != 'ID_Pedido':
                                df_master.loc[mask, col] = edited.at[idx, col]
                
                st.session_state.pedidos = df_master
                salvar_pedidos(df_master)
                st.toast("💾 Salvo!", icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")
        
        st.divider()
        
        # WhatsApp rápido
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("💬 WhatsApp Rápido")
            if not df_view.empty:
                sel_cli = st.selectbox("Cliente:", sorted(df_view['Cliente'].unique()), key="zap_cli")
                if sel_cli:
                    d = df_view[df_view['Cliente'] == sel_cli].iloc[-1]
                    msg = f"Olá {sel_cli}! 🦐\n\nSeu pedido:\n"
                    if d['Caruru'] > 0:
                        msg += f"• {int(d['Caruru'])}x Caruru\n"
                    if d['Bobo'] > 0:
                        msg += f"• {int(d['Bobo'])}x Bobó\n"
                    msg += f"\n💵 Total: R$ {d['Valor']:.2f}"
                    if d['Pagamento'] in ["NÃO PAGO", "METADE"]:
                        msg += f"\n\n📲 Pix: {CHAVE_PIX}"
                    
                    link = gerar_link_whatsapp(d['Contato'], msg)
                    if link:
                        st.link_button("📱 Enviar WhatsApp", link, use_container_width=True)
                    else:
                        st.warning("Contato inválido ou não cadastrado.")
    else:
        st.info("Nenhum pedido cadastrado.")
    
    st.divider()
    
    # Backup
    with st.expander("💾 Backup & Restauração"):
        st.write("### 📥 Fazer Backup")
        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED, False) as z:
                z.writestr("pedidos.csv", st.session_state.pedidos.to_csv(index=False))
                z.writestr("clientes.csv", st.session_state.clientes.to_csv(index=False))
                if os.path.exists(ARQUIVO_HISTORICO):
                    with open(ARQUIVO_HISTORICO, 'r') as f:
                        z.writestr("historico.csv", f.read())
            st.download_button(
                "📥 Baixar Backup Completo (ZIP)",
                buf.getvalue(),
                f"backup_caruru_{date.today()}.zip",
                "application/zip"
            )
        except Exception as e:
            st.error(f"Erro backup: {e}")
        
        st.write("### 📤 Restaurar Pedidos")
        up = st.file_uploader("Arquivo Pedidos (CSV)", type="csv", key="rest_ped")
        if up and st.button("⚠️ Restaurar Pedidos"):
            try:
                df_n = pd.read_csv(up)
                salvar_pedidos(df_n)
                st.session_state.pedidos = carregar_pedidos()
                st.success("✅ Restaurado!")
                st.rerun()
            except Exception as e:
                st.error(f"Erro: {e}")

# --- RELATÓRIOS ---
elif menu == "🖨️ Relatórios & Recibos":
    st.title("🖨️ Impressão de Documentos")
    
    t1, t2 = st.tabs(["📄 Recibo Individual", "📊 Relatório Geral"])
    df = st.session_state.pedidos
    
    with t1:
        if df.empty:
            st.info("Sem pedidos cadastrados.")
        else:
            cli = st.selectbox("👤 Cliente:", sorted(df['Cliente'].unique()))
            peds = df[df['Cliente'] == cli].sort_values("Data", ascending=False)
            
            if not peds.empty:
                opc = {
                    i: f"#{p['ID_Pedido']} | {p['Data'].strftime('%d/%m/%Y') if hasattr(p['Data'], 'strftime') else p['Data']} | R$ {p['Valor']:.2f} | {p['Status']}"
                    for i, p in peds.iterrows()
                }
                sid = st.selectbox("📋 Selecione o pedido:", options=opc.keys(), format_func=lambda x: opc[x])
                
                if st.button("📄 Gerar Recibo PDF", use_container_width=True, type="primary"):
                    pdf = gerar_recibo_pdf(peds.loc[sid].to_dict())
                    if pdf:
                        st.download_button(
                            "⬇️ Baixar Recibo",
                            pdf,
                            f"Recibo_{cli}_{peds.loc[sid]['ID_Pedido']}.pdf",
                            "application/pdf"
                        )
                    else:
                        st.error("Erro ao gerar PDF.")
    
    with t2:
        tipo = st.radio("📅 Filtro:", ["Dia Específico", "Período", "Tudo"], horizontal=True)
        
        if tipo == "Dia Específico":
            dt = st.date_input("Data:", date.today(), format="DD/MM/YYYY", key="rel_data")
            df_rel = df[df['Data'] == dt]
            nome = f"Relatorio_{dt.strftime('%d-%m-%Y')}.pdf"
        elif tipo == "Período":
            c1, c2 = st.columns(2)
            with c1:
                dt_ini = st.date_input("De:", date.today() - timedelta(days=7), format="DD/MM/YYYY")
            with c2:
                dt_fim = st.date_input("Até:", date.today(), format="DD/MM/YYYY")
            df_rel = df[(df['Data'] >= dt_ini) & (df['Data'] <= dt_fim)]
            nome = f"Relatorio_{dt_ini.strftime('%d-%m')}_{dt_fim.strftime('%d-%m-%Y')}.pdf"
        else:
            df_rel = df
            nome = "Relatorio_Geral.pdf"
        
        st.write(f"📊 **{len(df_rel)}** pedidos | **Total:** R$ {df_rel['Valor'].sum():,.2f}")
        
        if not df_rel.empty:
            if st.button("📊 Gerar Relatório PDF", use_container_width=True, type="primary"):
                pdf = gerar_relatorio_pdf(df_rel, nome.replace(".pdf", ""))
                if pdf:
                    st.download_button("⬇️ Baixar Relatório", pdf, nome, "application/pdf")
                else:
                    st.error("Erro ao gerar PDF.")

# --- PROMOÇÕES ---
elif menu == "📢 Promoções":
    st.title("📢 Marketing & Promoções")
    
    st.subheader("1️⃣ Configurar Mensagem")
    c_img, c_txt = st.columns([1, 2])
    
    with c_img:
        up_img = st.file_uploader("🖼️ Banner (Visualização)", type=["jpg", "png", "jpeg"])
        if up_img:
            st.image(up_img, caption="Preview do Banner", use_column_width=True)
            st.info("💡 Anexe a imagem manualmente no WhatsApp.")
    
    with c_txt:
        txt_padrao = """Olá! 🦐

Hoje tem *Caruru Fresquinho* no Cantinho!

🥘 Caruru Tradicional - R$ 70,00
🦐 Bobó de Camarão - R$ 70,00

Peça já o seu! 😋
📲 Faça seu pedido!"""
        msg = st.text_area("✏️ Texto da Promoção", value=txt_padrao, height=200)
    
    st.divider()
    st.subheader("2️⃣ Enviar para Clientes")
    
    df_c = st.session_state.clientes
    if df_c.empty:
        st.warning("Nenhum cliente cadastrado.")
    else:
        filtro = st.text_input("🔍 Buscar cliente:")
        if filtro:
            df_c = df_c[
                df_c['Nome'].str.contains(filtro, case=False, na=False) |
                df_c['Contato'].str.contains(filtro, na=False)
            ]
        
        msg_enc = urllib.parse.quote(msg)
        df_show = df_c[['Nome', 'Contato']].copy()
        
        def link_zap(tel):
            t = limpar_telefone(tel)
            return f"https://wa.me/55{t}?text={msg_enc}" if len(t) >= 10 else None
        
        df_show['Link'] = df_show['Contato'].apply(link_zap)
        
        st.data_editor(
            df_show,
            column_config={
                "Link": st.column_config.LinkColumn("Ação", display_text="📱 Enviar"),
                "Nome": st.column_config.TextColumn(disabled=True),
                "Contato": st.column_config.TextColumn(disabled=True)
            },
            hide_index=True,
            use_container_width=True
        )

# --- CLIENTES ---
elif menu == "👥 Cadastrar Clientes":
    st.title("👥 Gestão de Clientes")
    
    t1, t2, t3 = st.tabs(["➕ Cadastrar", "📋 Lista", "🗑️ Excluir"])
    
    with t1:
        st.subheader("Novo Cliente")
        with st.form("cli_form", clear_on_submit=True):
            n = st.text_input("👤 Nome*", placeholder="Ex: João Silva")
            z = st.text_input("📱 WhatsApp", placeholder="79999999999")
            o = st.text_area("📝 Observações", placeholder="Ex: Cliente VIP, prefere entrega à tarde...")
            
            if st.form_submit_button("💾 Cadastrar", use_container_width=True, type="primary"):
                if not n.strip():
                    st.error("❌ Nome é obrigatório!")
                else:
                    # Verifica duplicado
                    nomes = st.session_state.clientes['Nome'].str.lower().str.strip().tolist()
                    if n.lower().strip() in nomes:
                        st.warning(f"⚠️ Cliente '{n}' já cadastrado!")
                    else:
                        tel_limpo, msg_tel = validar_telefone(z)
                        if msg_tel:
                            st.warning(msg_tel)
                        
                        novo = pd.DataFrame([{
                            "Nome": n.strip(),
                            "Contato": tel_limpo,
                            "Observacoes": o.strip()
                        }])
                        st.session_state.clientes = pd.concat([st.session_state.clientes, novo], ignore_index=True)
                        salvar_clientes(st.session_state.clientes)
                        st.success(f"✅ Cliente '{n}' cadastrado!")
                        st.rerun()
    
    with t2:
        st.subheader("Lista de Clientes")
        if not st.session_state.clientes.empty:
            edited = st.data_editor(
                st.session_state.clientes,
                num_rows="fixed",
                use_container_width=True,
                hide_index=True
            )
            if not edited.equals(st.session_state.clientes):
                st.session_state.clientes = edited
                salvar_clientes(edited)
                st.toast("💾 Salvo!")
            
            st.divider()
            c1, c2 = st.columns(2)
            with c1:
                if st.button("📄 Exportar Lista PDF", use_container_width=True):
                    pdf = gerar_lista_clientes_pdf(st.session_state.clientes)
                    if pdf:
                        st.download_button("⬇️ Baixar PDF", pdf, "Clientes.pdf", "application/pdf")
            with c2:
                csv = st.session_state.clientes.to_csv(index=False).encode('utf-8')
                st.download_button("📊 Exportar CSV", csv, "clientes.csv", "text/csv", use_container_width=True)
        else:
            st.info("Nenhum cliente cadastrado.")
        
        with st.expander("📤 Importar Clientes"):
            up_c = st.file_uploader("Arquivo CSV", type="csv", key="rest_cli")
            if up_c and st.button("⚠️ Importar"):
                try:
                    df_c = pd.read_csv(up_c)
                    salvar_clientes(df_c)
                    st.session_state.clientes = carregar_clientes()
                    st.success("✅ Importado!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")
    
    with t3:
        st.subheader("Excluir Cliente")
        if not st.session_state.clientes.empty:
            lista_cli = st.session_state.clientes['Nome'].unique().tolist()
            d = st.selectbox("👤 Selecione o cliente:", lista_cli)
            
            # Verifica se tem pedidos
            pedidos_cliente = st.session_state.pedidos[st.session_state.pedidos['Cliente'] == d]
            if not pedidos_cliente.empty:
                st.warning(f"⚠️ Este cliente tem {len(pedidos_cliente)} pedido(s) registrado(s).")
            
            confirma = st.checkbox(f"✅ Confirmo a exclusão de '{d}'")
            
            if st.button("🗑️ Excluir Cliente", type="primary", disabled=not confirma, use_container_width=True):
                st.session_state.clientes = st.session_state.clientes[st.session_state.clientes['Nome'] != d]
                salvar_clientes(st.session_state.clientes)
                st.success(f"✅ Cliente '{d}' excluído!")
                st.rerun()
        else:
            st.info("Nenhum cliente cadastrado.")

# --- ADMIN ---
elif menu == "🛠️ Manutenção":
    st.title("🛠️ Manutenção do Sistema")
    
    t1, t2, t3 = st.tabs(["📋 Logs", "📜 Histórico", "⚙️ Config"])
    
    with t1:
        st.subheader("📋 Logs de Erro")
        if os.path.exists(ARQUIVO_LOG):
            with open(ARQUIVO_LOG, "r") as f:
                log = f.read()
            if log.strip():
                st.text_area("", log, height=300)
                if st.button("🗑️ Limpar Logs"):
                    open(ARQUIVO_LOG, 'w').close()
                    st.success("✅ Logs limpos!")
                    st.rerun()
            else:
                st.success("✅ Sem erros registrados!")
        else:
            st.success("✅ Sem erros registrados!")
    
    with t2:
        st.subheader("📜 Histórico de Alterações")
        if os.path.exists(ARQUIVO_HISTORICO):
            try:
                df_hist = pd.read_csv(ARQUIVO_HISTORICO)
                df_hist = df_hist.sort_values('Timestamp', ascending=False)
                st.dataframe(df_hist, use_container_width=True, hide_index=True)
                
                csv_hist = df_hist.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Exportar Histórico", csv_hist, "historico.csv", "text/csv")
                
                if st.button("🗑️ Limpar Histórico"):
                    os.remove(ARQUIVO_HISTORICO)
                    st.success("✅ Histórico limpo!")
                    st.rerun()
            except:
                st.info("Histórico vazio ou corrompido.")
        else:
            st.info("Nenhuma alteração registrada ainda.")
    
    with t3:
        st.subheader("⚙️ Configurações")
        
        st.write("**Informações do Sistema:**")
        st.write(f"- Versão: {VERSAO}")
        st.write(f"- Pedidos cadastrados: {len(st.session_state.pedidos)}")
        st.write(f"- Clientes cadastrados: {len(st.session_state.clientes)}")
        st.write(f"- Preço base: R$ {PRECO_BASE:.2f}")
        st.write(f"- Chave PIX: {CHAVE_PIX}")
        
        st.divider()
        
        st.write("**Arquivos:**")
        arquivos = [ARQUIVO_PEDIDOS, ARQUIVO_CLIENTES, ARQUIVO_HISTORICO, ARQUIVO_LOG]
        for arq in arquivos:
            if os.path.exists(arq):
                tamanho = os.path.getsize(arq) / 1024
                st.write(f"- ✅ {arq} ({tamanho:.1f} KB)")
            else:
                st.write(f"- ❌ {arq} (não existe)")
        
        st.divider()
        
        if st.button("🔄 Recarregar Dados", use_container_width=True):
            st.session_state.pedidos = carregar_pedidos()
            st.session_state.clientes = carregar_clientes()
            st.success("✅ Dados recarregados!")
            st.rerun()
