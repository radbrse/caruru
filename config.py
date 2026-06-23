"""
Configurações globais do Cantinho do Caruru.
Constantes, logger, fuso horário e funções de configuração persistente.
"""

import os
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from zoneinfo import ZoneInfo

# --- FUSO HORÁRIO (BRASIL) ---
FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")

def agora_brasil():
    """Retorna datetime atual no fuso horário de Brasília."""
    return datetime.now(FUSO_BRASIL)

def hoje_brasil():
    """Retorna a data de hoje no fuso horário de Brasília."""
    return datetime.now(FUSO_BRASIL).date()

# --- CONSTANTES ---
ARQUIVO_LOG = "system_errors.log"
ARQUIVO_PEDIDOS = "banco_de_dados_caruru.csv"
ARQUIVO_CLIENTES = "banco_de_dados_clientes.csv"
ARQUIVO_HISTORICO = "historico_alteracoes.csv"
ARQUIVO_CONFIG = "config.json"
def _carregar_chave_pix():
    """Lê a chave PIX de st.secrets["chave_pix"], com fallback embutido.

    A chave PIX é de RECEBIMENTO — feita para ser compartilhada com clientes
    que vão pagar as encomendas —, então não é um segredo. Manter o fallback
    garante que o PIX apareça nos PDFs/mensagens mesmo sem o secret configurado.
    """
    _FALLBACK_PIX = "79999296722"
    try:
        import streamlit as st
        return str(st.secrets.get("chave_pix", _FALLBACK_PIX)).strip() or _FALLBACK_PIX
    except Exception:
        return _FALLBACK_PIX

CHAVE_PIX = _carregar_chave_pix()
OPCOES_STATUS = ["🔴 Pendente", "🟡 Em Produção", "✅ Entregue", "🚫 Cancelado"]
OPCOES_PAGAMENTO = ["PAGO", "NÃO PAGO", "METADE"]

# --- SCHEMA ÚNICO DE PEDIDOS (fonte de verdade) ---
# Usado em load/save (CSV e Sheets) e na validação de import/restauração.
# Centralizar evita que um caminho (ex.: restaurar backup) descarte colunas
# que outro caminho grava — causa real de perda de dados em round-trips.
COLUNAS_PEDIDOS = [
    "ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora",
    "Hora_Entrega", "Status", "Pagamento", "Contato", "Desconto", "Entrada",
    "Observacoes", "Extra", "Vegano", "Delivery",
]
# Colunas que DEVEM existir num CSV importado (mínimo aceito).
COLUNAS_PEDIDOS_OBRIGATORIAS = [
    "ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora",
    "Status", "Pagamento", "Contato", "Desconto", "Observacoes",
]
# Colunas opcionais (retrocompatibilidade) e seus defaults ao faltarem.
COLUNAS_PEDIDOS_OPCIONAIS_DEFAULTS = {
    "Hora_Entrega": "",
    "Entrada": 0.0,
    "Extra": "False",
    "Vegano": "False",
    "Delivery": "False",
}

PRECO_BASE = 70.0
VERSAO = "21.0"
MAX_BACKUP_FILES = 5
CACHE_TIMEOUT = 60

# --- LOGGER (Singleton) ---
logger = logging.getLogger("cantinho")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = RotatingFileHandler(ARQUIVO_LOG, maxBytes=5*1024*1024, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    logger.addHandler(handler)

# --- CONFIGURAÇÃO PERSISTENTE ---
def carregar_config():
    """Carrega configurações do arquivo JSON."""
    config_padrao = {'preco_base': 70.0}
    try:
        if os.path.exists(ARQUIVO_CONFIG):
            with open(ARQUIVO_CONFIG, 'r', encoding='utf-8') as f:
                config = json.load(f)
                logger.info("Configurações carregadas do arquivo")
                return config
        else:
            salvar_config(config_padrao)
            logger.info("Arquivo de configuração criado com valores padrão")
            return config_padrao
    except Exception as e:
        logger.error(f"Erro ao carregar config: {e}")
        return config_padrao

def salvar_config(config):
    """Salva configurações no arquivo JSON."""
    try:
        with open(ARQUIVO_CONFIG, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(f"Configurações salvas: {config}")
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar config: {e}")
        return False

def obter_preco_base():
    """Obtém o preço base atual das configurações."""
    import streamlit as st
    if 'config' not in st.session_state:
        st.session_state.config = carregar_config()
    return st.session_state.config.get('preco_base', 70.0)

def atualizar_preco_base(novo_preco):
    """Atualiza o preço base nas configurações."""
    import streamlit as st
    try:
        novo_preco = float(novo_preco)
        if novo_preco <= 0:
            return False, "❌ Preço deve ser maior que zero"

        if 'config' not in st.session_state:
            st.session_state.config = carregar_config()

        st.session_state.config['preco_base'] = novo_preco

        if salvar_config(st.session_state.config):
            logger.info(f"Preço base atualizado: R$ {novo_preco:.2f}")
            return True, f"✅ Preço base atualizado para R$ {novo_preco:.2f}"
        else:
            return False, "❌ Erro ao salvar configuração"

    except ValueError:
        return False, "❌ Valor inválido para preço"
    except Exception as e:
        logger.error(f"Erro ao atualizar preço base: {e}")
        return False, f"❌ Erro: {e}"
