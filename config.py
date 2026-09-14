"""
Configurações globais do Cantinho do Caruru.
Constantes, logger, fuso horário e funções de configuração persistente.
"""

import os
import json
import math
from pathlib import Path
from storage import transacional, escrever_json
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
VERSAO = "21.1"
MAX_BACKUP_FILES = 5
CACHE_TIMEOUT = 60

# --- LOGGER (Singleton) ---
logger = logging.getLogger("cantinho")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = RotatingFileHandler(ARQUIVO_LOG, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    logger.addHandler(handler)

# --- CONFIGURAÇÃO PERSISTENTE ---
class PrecoNaoConfigurado(ValueError):
    pass


def validar_config(dados):
    preco = float(dados['preco_base'])
    if not math.isfinite(preco) or preco <= 0:
        raise ValueError('Preço base deve ser um número finito maior que zero.')
    return {'preco_base': preco}


@transacional
def carregar_config():
    """Recupera preço persistido; nunca recria silenciosamente um default."""
    if os.path.exists(ARQUIVO_CONFIG) and not Path('.config-recuperar').exists():
        try:
            with open(ARQUIVO_CONFIG, encoding='utf-8') as handle:
                return validar_config(json.load(handle))
        except (ValueError, KeyError, TypeError):
            logger.warning('Configuração local inválida; tentando recuperar do Sheets.')
    from sheets import conectar_google_sheets, ler_config_negocio
    client = conectar_google_sheets()
    if not client:
        raise RuntimeError('Não foi possível recuperar o preço do Sheets. Verifique a conexão antes de cadastrar pedidos.')
    dados = ler_config_negocio(client)
    if dados is None:
        raise PrecoNaoConfigurado('Preço ainda não cadastrado no backup. Confirme o preço vigente para continuar.')
    dados = validar_config(dados)
    if not salvar_config(dados):
        raise RuntimeError('Preço recuperado, mas não foi possível persistir a configuração local.')
    Path('.config-recuperar').unlink(missing_ok=True)
    return dados


@transacional
def salvar_config(config):
    try:
        escrever_json(ARQUIVO_CONFIG, validar_config(config))
        return True
    except Exception as e:
        logger.error(f'Erro ao salvar configuração: {e}')
        return False


def obter_preco_base():
    # Lê a revisão local atual: uma sessão antiga não conserva preço anterior.
    return carregar_config()['preco_base']


@transacional
def atualizar_preco_base(novo_preco):
    import streamlit as st
    from sheets import conectar_google_sheets, salvar_config_negocio
    try:
        dados = validar_config({'preco_base': novo_preco})
        client = conectar_google_sheets()
        if not client:
            return False, 'Não foi possível conectar ao Sheets. Preço não alterado.'
        # Se a confirmação da rede/local falhar, próxima leitura consulta o Sheets.
        Path('.config-recuperar').touch()
        salvar_config_negocio(client, dados)
        if not salvar_config(dados):
            return False, 'Preço salvo no Sheets, mas a cópia local precisa ser recuperada. Recarregue a página.'
        Path('.config-recuperar').unlink(missing_ok=True)
        st.session_state.config = dados
        return True, f"Preço base salvo no Sheets: R$ {dados['preco_base']:.2f}"
    except Exception as e:
        logger.error(f'Erro ao atualizar preço: {e}')
        return False, f'Preço não confirmado. Verifique a conexão e recarregue: {e}'
