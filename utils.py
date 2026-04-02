"""
Funções utilitárias: validação, formatação, badges HTML, cálculos.
"""

import re
import urllib.parse
import pandas as pd
from datetime import date, datetime, time
import time as time_module

from config import (
    logger, FUSO_BRASIL, agora_brasil, hoje_brasil,
    OPCOES_STATUS, OPCOES_PAGAMENTO, obter_preco_base
)

# ==============================================================================
# VALIDAÇÕES
# ==============================================================================
def limpar_telefone(telefone):
    """Extrai apenas dígitos do telefone."""
    if not telefone:
        return ""
    return re.sub(r'\D', '', str(telefone))

def validar_telefone(telefone):
    """Valida e formata telefone brasileiro."""
    limpo = limpar_telefone(telefone)

    if not limpo:
        return "", None

    if limpo.startswith("55") and len(limpo) > 11:
        limpo = limpo[2:]

    if len(limpo) == 10:
        return limpo, None
    elif len(limpo) == 11:
        return limpo, None
    elif len(limpo) == 8 or len(limpo) == 9:
        return limpo, "⚠️ Falta o DDD no telefone"
    elif len(limpo) > 0:
        return limpo, f"⚠️ Telefone com formato incomum ({len(limpo)} dígitos)"

    return "", None

def validar_quantidade(valor, nome_campo):
    """Valida quantidades com tratamento de erros específico."""
    try:
        if valor is None or valor == "":
            return 0.0, None

        v = float(str(valor).replace(",", "."))

        if v < 0:
            logger.warning(f"{nome_campo} negativo: {v}, ajustando para 0")
            return 0.0, f"⚠️ {nome_campo} não pode ser negativo. Ajustado para 0."

        if v > 999:
            logger.warning(f"{nome_campo} muito alto: {v}, limitando a 999")
            return 999.0, f"⚠️ {nome_campo} muito alto. Limitado a 999."

        return round(v, 1), None

    except (ValueError, TypeError) as e:
        logger.error(f"Erro ao validar {nome_campo}: {valor} - {e}")
        return 0.0, f"❌ Valor inválido em {nome_campo}. Ajustado para 0."
    except Exception as e:
        logger.error(f"Erro inesperado ao validar {nome_campo}: {e}", exc_info=True)
        return 0.0, f"❌ Erro ao processar {nome_campo}. Ajustado para 0."

def validar_desconto(valor):
    """Valida desconto entre 0 e 100."""
    try:
        if valor is None or valor == "":
            return 0.0, None

        v = float(str(valor).replace(",", "."))

        if v < 0:
            logger.warning(f"Desconto negativo: {v}, ajustando para 0")
            return 0.0, "⚠️ Desconto não pode ser negativo."

        if v > 100:
            logger.warning(f"Desconto muito alto: {v}, limitando a 100")
            return 100.0, "⚠️ Desconto limitado a 100%."

        return round(v, 2), None

    except (ValueError, TypeError) as e:
        logger.error(f"Erro ao validar desconto: {valor} - {e}")
        return 0.0, "❌ Desconto inválido."
    except Exception as e:
        logger.error(f"Erro inesperado ao validar desconto: {e}", exc_info=True)
        return 0.0, "❌ Erro ao processar desconto."

def validar_data_pedido(data, permitir_passado=False):
    """Valida data do pedido."""
    try:
        if data is None:
            logger.info("Data não informada, usando hoje")
            return hoje_brasil(), "⚠️ Data não informada. Usando hoje."

        if isinstance(data, str):
            data = pd.to_datetime(data, errors='coerce').date()
        elif isinstance(data, datetime):
            data = data.date()
        elif not isinstance(data, date):
            raise ValueError(f"Tipo de data inválido: {type(data)}")

        hoje = hoje_brasil()

        if not permitir_passado and data < hoje:
            logger.warning(f"Data no passado: {data}")
            return data, "⚠️ Data no passado (permitido para edição)."

        limite = hoje.replace(year=hoje.year + 1)
        if data > limite:
            logger.warning(f"Data muito distante: {data}, ajustando para {limite}")
            return limite, "⚠️ Data muito distante. Ajustada para 1 ano."

        return data, None

    except (ValueError, TypeError) as e:
        logger.error(f"Erro ao validar data: {data} - {e}")
        return hoje_brasil(), "❌ Data inválida. Usando hoje."
    except Exception as e:
        logger.error(f"Erro inesperado ao validar data: {e}", exc_info=True)
        return hoje_brasil(), "❌ Erro ao processar data. Usando hoje."

def validar_hora(hora):
    """Valida e normaliza hora."""
    try:
        if hora is None or hora == "" or str(hora).lower() in ["nan", "nat", "none"]:
            return time(12, 0), None

        if isinstance(hora, time):
            return hora, None

        hora_str = str(hora).strip()

        for fmt in ["%H:%M", "%H:%M:%S", "%I:%M %p"]:
            try:
                return datetime.strptime(hora_str, fmt).time(), None
            except:
                continue

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
# CÁLCULOS
# ==============================================================================
def gerar_id_sequencial(df):
    """Gera próximo ID sequencial."""
    try:
        if df is None or df.empty:
            logger.info("DataFrame vazio, iniciando ID com 1")
            return 1

        ids_numericos = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
        ids_validos = ids_numericos[ids_numericos > 0]

        if ids_validos.empty:
            logger.warning("Nenhum ID válido encontrado, iniciando com 1")
            return 1

        max_id = int(ids_validos.max())
        novo_id = max_id + 1

        logger.info(f"Novo ID gerado: {novo_id}")
        return novo_id

    except Exception as e:
        logger.error(f"Erro ao gerar ID sequencial: {e}", exc_info=True)
        fallback_id = int(time_module.time() * 1000) % 1000000
        logger.warning(f"Usando ID fallback baseado em timestamp: {fallback_id}")
        return fallback_id

def calcular_total(caruru, bobo, desconto):
    """Calcula total com validação."""
    try:
        c, msg_c = validar_quantidade(caruru, "Caruru")
        b, msg_b = validar_quantidade(bobo, "Bobó")
        d, msg_d = validar_desconto(desconto)

        if msg_c:
            logger.warning(f"Validação caruru: {msg_c}")
        if msg_b:
            logger.warning(f"Validação bobó: {msg_b}")
        if msg_d:
            logger.warning(f"Validação desconto: {msg_d}")

        preco_atual = obter_preco_base()
        subtotal = (c + b) * preco_atual
        total = subtotal * (1 - d / 100)

        resultado = round(total, 2)
        logger.info(f"Total calculado: R$ {resultado} (Caruru: {c}, Bobó: {b}, Desconto: {d}%, Preço: R$ {preco_atual})")
        return resultado

    except Exception as e:
        logger.error(f"Erro ao calcular total: {e}", exc_info=True)
        return 0.0

def gerar_link_whatsapp(telefone, mensagem):
    """Gera link do WhatsApp com validação."""
    tel_limpo = limpar_telefone(telefone)
    if len(tel_limpo) < 10:
        return None

    msg_encoded = urllib.parse.quote(mensagem)
    return f"https://wa.me/55{tel_limpo}?text={msg_encoded}"

# ==============================================================================
# BADGES E FORMATAÇÃO HTML
# ==============================================================================
def get_status_badge(status):
    """Retorna badge HTML colorido para status."""
    cores = {
        "✅ Entregue": ("#10b981", "#d1fae5"),
        "🔴 Pendente": ("#ef4444", "#fee2e2"),
        "🟡 Em Produção": ("#f59e0b", "#fef3c7"),
        "🚫 Cancelado": ("#6b7280", "#f3f4f6"),
    }
    cor_texto, cor_fundo = cores.get(status, ("#6b7280", "#f3f4f6"))
    return f'<span style="background-color: {cor_fundo}; color: {cor_texto}; padding: 4px 12px; border-radius: 12px; font-size: 0.875rem; font-weight: 600; display: inline-block; border: 1px solid {cor_texto}40;">{status}</span>'

def get_pagamento_badge(pagamento):
    """Retorna badge HTML colorido para pagamento."""
    cores = {
        "PAGO": ("#10b981", "#d1fae5"),
        "NÃO PAGO": ("#ef4444", "#fee2e2"),
        "METADE": ("#f59e0b", "#fef3c7"),
    }
    cor_texto, cor_fundo = cores.get(pagamento, ("#6b7280", "#f3f4f6"))
    return f'<span style="background-color: {cor_fundo}; color: {cor_texto}; padding: 4px 12px; border-radius: 12px; font-size: 0.875rem; font-weight: 600; display: inline-block; border: 1px solid {cor_texto}40;">{pagamento}</span>'

def get_obs_icon(observacoes):
    """Retorna ícone OBS se houver observações preenchidas."""
    if observacoes and str(observacoes).strip() and str(observacoes).strip() != "nan":
        return """
            <span style="
                background-color: #dbeafe;
                color: #1e40af;
                padding: 2px 8px;
                border-radius: 8px;
                font-size: 0.75rem;
                font-weight: 700;
                display: inline-block;
                border: 1px solid #3b82f6;
            ">📝 OBS</span>
        """
    return ""

def get_extra_badge(extra):
    """Retorna badge HTML para pedido extra."""
    if extra:
        return '<span style="background-color:#fff7ed;color:#c2410c;padding:2px 7px;border-radius:8px;font-size:0.75rem;font-weight:700;display:inline-block;border:1px solid #f97316;">⚡ Extra</span>'
    return ""

def formatar_valor_br(valor):
    """Formata valor para padrão brasileiro."""
    valor_formatado = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {valor_formatado}"

def get_valor_destaque(valor):
    """Retorna HTML com valor monetário em destaque."""
    return f"""
        <span style="
            color: #059669;
            font-weight: 700;
            font-size: 1.05rem;
        ">{formatar_valor_br(valor)}</span>
    """

def get_whatsapp_link(contato, texto=""):
    """Retorna link HTML clicável para WhatsApp."""
    if not contato or str(contato).strip() in ["", "nan", "None"]:
        return "Não informado"

    numero_limpo = ''.join(filter(str.isdigit, str(contato)))

    if len(numero_limpo) == 11:
        numero_limpo = f"55{numero_limpo}"
    elif len(numero_limpo) == 10:
        numero_limpo = f"55{numero_limpo}"

    if not texto:
        texto = contato

    return f'<a href="https://wa.me/{numero_limpo}" target="_blank" style="color: #25D366; text-decoration: none; font-weight: 600;">📱 {texto}</a>'
