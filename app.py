"""
Sistema de Gestão de Pedidos - Cantinho do Caruru
Versão 19.0 - Com Google Sheets

MELHORIAS IMPLEMENTADAS:
========================
1. File Locking: Previne race conditions em operações de leitura/escrita com fcntl
2. Logging Robusto: RotatingFileHandler com 5MB por arquivo, 3 backups, níveis INFO/WARNING/ERROR
3. Backup Inteligente: Backups com timestamp, limpeza automática mantendo últimos 5
4. Transações Atômicas: Escrita em arquivo temporário + move atômico + rollback em caso de erro
5. Validações Específicas: Exceções específicas (ValueError, TypeError) com logging detalhado
6. ID Generation Segura: Geração robusta de IDs com fallback baseado em timestamp
7. Tratamento de Erros: Logging com exc_info=True para stack traces completos
8. Operações Otimizadas: Menos I/O desnecessário, validações consolidadas

SEGURANÇA:
==========
- File locking com timeout (10s) previne deadlocks
- Atomic writes previnem corrupção de dados
- Backups automáticos antes de cada escrita
- Rollback automático em caso de falha
- Validação robusta de entradas

PERFORMANCE:
============
- Logs com rotation automática (não crescem indefinidamente)
- Backups limitados (mantém apenas últimos 5)
- Operações de arquivo otimizadas
- Menos reruns desnecessários do Streamlit
"""

import streamlit as st
import pandas as pd
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
import os
import io
import zipfile
import logging
from logging.handlers import RotatingFileHandler
import urllib.parse
import re
import fcntl
import time as time_module
from contextlib import contextmanager
import shutil
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
import json

# Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

# --- CONFIGURAÇÃO DE FUSO HORÁRIO (BRASIL) ---
FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")

def agora_brasil():
    """Retorna datetime atual no fuso horário de Brasília."""
    return datetime.now(FUSO_BRASIL)

def hoje_brasil():
    """Retorna a data de hoje no fuso horário de Brasília."""
    return datetime.now(FUSO_BRASIL).date()

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
VERSAO = "19.0"
MAX_BACKUP_FILES = 5  # Número máximo de arquivos .bak a manter
CACHE_TIMEOUT = 60  # Tempo de cache em segundos

# Configuração de logging com rotation (5MB por arquivo, mantém 3 backups)
logger = logging.getLogger("cantinho")
logger.setLevel(logging.INFO)
handler = RotatingFileHandler(ARQUIVO_LOG, maxBytes=5*1024*1024, backupCount=3)
handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
logger.addHandler(handler)

# ==============================================================================
# FUNÇÕES DE UTILITÁRIOS E FILE LOCKING
# ==============================================================================
@contextmanager
def file_lock(filepath, timeout=10):
    """
    Context manager para file locking com timeout.
    Previne race conditions em operações de leitura/escrita.
    """
    lock_file = f"{filepath}.lock"
    lock_fd = None
    start_time = time_module.time()

    try:
        # Cria arquivo de lock se não existir
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)

        # Tenta adquirir lock com timeout
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                logger.info(f"Lock adquirido: {filepath}")
                break
            except IOError:
                if time_module.time() - start_time >= timeout:
                    raise TimeoutError(f"Timeout ao tentar adquirir lock para {filepath}")
                time_module.sleep(0.1)

        yield lock_fd

    finally:
        # Libera lock e remove arquivo
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
                if os.path.exists(lock_file):
                    os.remove(lock_file)
                logger.info(f"Lock liberado: {filepath}")
            except Exception as e:
                logger.error(f"Erro ao liberar lock: {e}")

def limpar_backups_antigos(arquivo_base):
    """
    Remove backups antigos mantendo apenas os MAX_BACKUP_FILES mais recentes.
    """
    try:
        # Busca todos os arquivos .bak
        pasta = os.path.dirname(arquivo_base) or "."
        nome_base = os.path.basename(arquivo_base)
        backups = [
            os.path.join(pasta, f) for f in os.listdir(pasta)
            if f.startswith(nome_base) and f.endswith(".bak")
        ]

        if len(backups) > MAX_BACKUP_FILES:
            # Ordena por data de modificação (mais antigos primeiro)
            backups.sort(key=lambda x: os.path.getmtime(x))

            # Remove os mais antigos
            for backup in backups[:-MAX_BACKUP_FILES]:
                os.remove(backup)
                logger.info(f"Backup antigo removido: {backup}")

    except Exception as e:
        logger.error(f"Erro ao limpar backups: {e}")

def criar_backup_com_timestamp(arquivo):
    """
    Cria backup com timestamp para melhor rastreamento.
    """
    if os.path.exists(arquivo):
        timestamp = agora_brasil().strftime("%Y%m%d_%H%M%S")
        backup = f"{arquivo}.{timestamp}.bak"
        shutil.copy(arquivo, backup)
        logger.info(f"Backup criado: {backup}")
        limpar_backups_antigos(arquivo)
        return backup
    return None

def listar_backups():
    """
    Lista todos os backups disponíveis com informações detalhadas.
    Retorna DataFrame com: arquivo, data/hora, tamanho, arquivo_origem
    """
    try:
        backups = []
        pasta = "."

        for arquivo in os.listdir(pasta):
            if ".bak" in arquivo:
                caminho = os.path.join(pasta, arquivo)
                stats = os.stat(caminho)

                # Extrai nome do arquivo original
                if arquivo.count('.') >= 2:
                    partes = arquivo.split('.')
                    origem = '.'.join(partes[:-2])  # Remove timestamp e .bak
                else:
                    origem = arquivo.replace('.bak', '')

                backups.append({
                    'Arquivo': arquivo,
                    'Origem': origem,
                    'Data/Hora': datetime.fromtimestamp(stats.st_mtime, FUSO_BRASIL),
                    'Tamanho_KB': stats.st_size / 1024,
                    'Caminho': caminho
                })

        if backups:
            df = pd.DataFrame(backups)
            df = df.sort_values('Data/Hora', ascending=False)
            return df
        else:
            return pd.DataFrame(columns=['Arquivo', 'Origem', 'Data/Hora', 'Tamanho_KB', 'Caminho'])

    except Exception as e:
        logger.error(f"Erro ao listar backups: {e}", exc_info=True)
        return pd.DataFrame(columns=['Arquivo', 'Origem', 'Data/Hora', 'Tamanho_KB', 'Caminho'])

def restaurar_backup(arquivo_backup, arquivo_destino):
    """
    Restaura um backup específico.
    Cria backup de segurança do arquivo atual antes de restaurar.
    """
    try:
        # Valida se o backup existe
        if not os.path.exists(arquivo_backup):
            logger.error(f"Backup não encontrado: {arquivo_backup}")
            return False, f"❌ Backup não encontrado: {arquivo_backup}"

        # Cria backup de segurança do arquivo atual
        if os.path.exists(arquivo_destino):
            backup_seguranca = criar_backup_com_timestamp(arquivo_destino)
            logger.info(f"Backup de segurança criado: {backup_seguranca}")

        # Restaura o backup
        with file_lock(arquivo_destino):
            shutil.copy(arquivo_backup, arquivo_destino)
            logger.info(f"Backup restaurado: {arquivo_backup} -> {arquivo_destino}")

        return True, f"✅ Backup restaurado com sucesso!"

    except Exception as e:
        logger.error(f"Erro ao restaurar backup: {e}", exc_info=True)
        return False, f"❌ Erro ao restaurar backup: {e}"

def limpar_backups_por_data(dias):
    """
    Remove backups com mais de X dias.
    """
    try:
        pasta = "."
        removidos = 0
        agora = time_module.time()
        limite_segundos = dias * 24 * 60 * 60

        for arquivo in os.listdir(pasta):
            if ".bak" in arquivo:
                caminho = os.path.join(pasta, arquivo)
                idade = agora - os.path.getmtime(caminho)

                if idade > limite_segundos:
                    os.remove(caminho)
                    removidos += 1
                    logger.info(f"Backup antigo removido: {arquivo}")

        return True, f"✅ {removidos} backup(s) removido(s)"

    except Exception as e:
        logger.error(f"Erro ao limpar backups por data: {e}", exc_info=True)
        return False, f"❌ Erro: {e}"

def importar_csv_externo(arquivo_upload, destino):
    """
    Importa CSV externo para um dos arquivos do sistema.
    """
    try:
        # Valida destino
        destinos_validos = {
            'Pedidos': ARQUIVO_PEDIDOS,
            'Clientes': ARQUIVO_CLIENTES,
            'Histórico': ARQUIVO_HISTORICO
        }

        if destino not in destinos_validos:
            return False, f"❌ Destino inválido: {destino}", None

        arquivo_destino = destinos_validos[destino]

        # Lê o CSV enviado
        df_novo = pd.read_csv(arquivo_upload)

        # Cria backup do arquivo atual
        if os.path.exists(arquivo_destino):
            backup = criar_backup_com_timestamp(arquivo_destino)
            logger.info(f"Backup criado antes da importação: {backup}")

        # Salva o novo CSV com file locking
        with file_lock(arquivo_destino):
            temp_file = f"{arquivo_destino}.tmp"
            df_novo.to_csv(temp_file, index=False)
            shutil.move(temp_file, arquivo_destino)

        logger.info(f"CSV importado: {destino} ({len(df_novo)} registros)")

        # Registra no histórico
        registrar_alteracao(
            "IMPORTAR",
            0,
            destino,
            f"Importação externa",
            f"{len(df_novo)} registros"
        )

        return True, f"✅ {len(df_novo)} registros importados com sucesso!", df_novo

    except Exception as e:
        logger.error(f"Erro ao importar CSV: {e}", exc_info=True)
        return False, f"❌ Erro ao importar: {e}", None

# ==============================================================================
# INTEGRAÇÃO GOOGLE SHEETS
# ==============================================================================
def conectar_google_sheets():
    """
    Conecta ao Google Sheets usando credenciais do Streamlit Secrets.
    Retorna o cliente gspread conectado ou None se falhar.
    """
    if not GSPREAD_AVAILABLE:
        logger.error("gspread não disponível")
        return None

    try:
        # Tenta carregar credenciais do secrets
        if "gcp_service_account" not in st.secrets:
            logger.warning("Credenciais Google Sheets não configuradas")
            return None

        # Prepara credenciais
        creds_dict = dict(st.secrets["gcp_service_account"])

        # Define escopos necessários
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

        # Cria credenciais
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)

        # Conecta ao gspread
        client = gspread.authorize(creds)

        logger.info("Conectado ao Google Sheets com sucesso")
        return client

    except Exception as e:
        logger.error(f"Erro ao conectar ao Google Sheets: {e}", exc_info=True)
        return None

def obter_ou_criar_planilha(client, nome_planilha="Cantinho do Caruru - Dados"):
    """
    Obtém a planilha ou cria se não existir.
    Retorna o objeto Spreadsheet.
    """
    try:
        # Tenta abrir a planilha existente
        try:
            spreadsheet = client.open(nome_planilha)
            logger.info(f"Planilha '{nome_planilha}' encontrada")
            return spreadsheet
        except gspread.exceptions.SpreadsheetNotFound:
            # Cria nova planilha
            spreadsheet = client.create(nome_planilha)
            logger.info(f"Planilha '{nome_planilha}' criada")

            # Cria abas padrão
            worksheet_pedidos = spreadsheet.sheet1
            worksheet_pedidos.update_title("Pedidos")

            spreadsheet.add_worksheet("Clientes", rows=1000, cols=10)
            spreadsheet.add_worksheet("Histórico", rows=5000, cols=10)
            spreadsheet.add_worksheet("Backups_Log", rows=1000, cols=10)

            logger.info("Abas padrão criadas na planilha")
            return spreadsheet

    except Exception as e:
        logger.error(f"Erro ao obter/criar planilha: {e}", exc_info=True)
        return None

def salvar_no_sheets(client, nome_aba, df):
    """
    Salva DataFrame no Google Sheets.
    """
    try:
        # Obtém a planilha
        spreadsheet = obter_ou_criar_planilha(client)
        if not spreadsheet:
            return False, "❌ Erro ao acessar planilha"

        # Obtém ou cria a aba
        try:
            worksheet = spreadsheet.worksheet(nome_aba)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(nome_aba, rows=len(df)+100, cols=len(df.columns))

        # Limpa conteúdo anterior
        worksheet.clear()

        # Prepara dados (converte tudo para string para evitar problemas)
        df_str = df.copy()
        for col in df_str.columns:
            df_str[col] = df_str[col].astype(str)

        # Atualiza planilha
        worksheet.update([df_str.columns.values.tolist()] + df_str.values.tolist())

        logger.info(f"Dados salvos no Sheets: {nome_aba} ({len(df)} linhas)")
        return True, f"✅ {len(df)} registros salvos no Google Sheets"

    except Exception as e:
        logger.error(f"Erro ao salvar no Sheets: {e}", exc_info=True)
        return False, f"❌ Erro ao salvar: {e}"

def carregar_do_sheets(client, nome_aba):
    """
    Carrega DataFrame do Google Sheets.
    """
    try:
        # Obtém a planilha
        spreadsheet = obter_ou_criar_planilha(client)
        if not spreadsheet:
            return None, "❌ Erro ao acessar planilha"

        # Obtém a aba
        try:
            worksheet = spreadsheet.worksheet(nome_aba)
        except gspread.exceptions.WorksheetNotFound:
            logger.warning(f"Aba '{nome_aba}' não encontrada")
            return pd.DataFrame(), f"⚠️ Aba '{nome_aba}' não existe (vazia)"

        # Carrega dados
        dados = worksheet.get_all_values()

        if not dados or len(dados) < 2:  # Apenas cabeçalho ou vazio
            return pd.DataFrame(), f"⚠️ Aba '{nome_aba}' está vazia"

        # Cria DataFrame
        df = pd.DataFrame(dados[1:], columns=dados[0])

        logger.info(f"Dados carregados do Sheets: {nome_aba} ({len(df)} linhas)")
        return df, f"✅ {len(df)} registros carregados"

    except Exception as e:
        logger.error(f"Erro ao carregar do Sheets: {e}", exc_info=True)
        return None, f"❌ Erro ao carregar: {e}"

def sincronizar_com_sheets(modo="enviar"):
    """
    Sincroniza dados entre CSV local e Google Sheets.

    Modos:
    - 'enviar': Envia CSV local para Sheets (backup)
    - 'receber': Baixa do Sheets para CSV local (restauração)
    - 'ambos': Sincronização bidirecional (usa o mais recente)
    """
    try:
        client = conectar_google_sheets()
        if not client:
            return False, "❌ Não foi possível conectar ao Google Sheets"

        resultados = []

        if modo in ["enviar", "ambos"]:
            # Envia Pedidos
            df_pedidos = st.session_state.pedidos
            sucesso, msg = salvar_no_sheets(client, "Pedidos", df_pedidos)
            resultados.append(f"Pedidos: {msg}")

            # Envia Clientes
            df_clientes = st.session_state.clientes
            sucesso, msg = salvar_no_sheets(client, "Clientes", df_clientes)
            resultados.append(f"Clientes: {msg}")

            # Registra no log de backups
            log_backup = pd.DataFrame([{
                'Timestamp': agora_brasil().strftime("%Y-%m-%d %H:%M:%S"),
                'Ação': 'Backup Automático',
                'Pedidos': len(df_pedidos),
                'Clientes': len(df_clientes)
            }])
            salvar_no_sheets(client, "Backups_Log", log_backup)

        if modo in ["receber", "ambos"]:
            # Recebe Pedidos
            df_pedidos, msg = carregar_do_sheets(client, "Pedidos")
            if df_pedidos is not None and not df_pedidos.empty:
                salvar_pedidos(df_pedidos)
                st.session_state.pedidos = carregar_pedidos()
                resultados.append(f"Pedidos: {msg}")

            # Recebe Clientes
            df_clientes, msg = carregar_do_sheets(client, "Clientes")
            if df_clientes is not None and not df_clientes.empty:
                salvar_clientes(df_clientes)
                st.session_state.clientes = carregar_clientes()
                resultados.append(f"Clientes: {msg}")

        return True, "\n".join(resultados)

    except Exception as e:
        logger.error(f"Erro na sincronização: {e}", exc_info=True)
        return False, f"❌ Erro na sincronização: {e}"

def verificar_status_sheets():
    """
    Verifica se Google Sheets está configurado e acessível.
    """
    if not GSPREAD_AVAILABLE:
        return False, "❌ Biblioteca gspread não instalada"

    if "gcp_service_account" not in st.secrets:
        return False, "⚠️ Credenciais não configuradas em Streamlit Secrets"

    try:
        client = conectar_google_sheets()
        if client:
            spreadsheet = obter_ou_criar_planilha(client)
            if spreadsheet:
                return True, f"✅ Conectado: {spreadsheet.title}"
        return False, "❌ Erro ao conectar"
    except Exception as e:
        return False, f"❌ Erro: {str(e)[:100]}"

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
    """Valida desconto entre 0 e 100 com tratamento específico."""
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
    """Valida data do pedido com tratamento específico."""
    try:
        if data is None:
            logger.info("Data não informada, usando hoje")
            return hoje_brasil(), "⚠️ Data não informada. Usando hoje."

        # Converte para date se necessário
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

        # Limite de 1 ano no futuro
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
    """
    Gera próximo ID sequencial de forma mais robusta.
    Usa timestamp como fallback para evitar duplicatas.
    """
    try:
        if df is None or df.empty:
            logger.info("DataFrame vazio, iniciando ID com 1")
            return 1

        # Converte IDs para numérico
        ids_numericos = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)

        # Filtra IDs válidos (maiores que 0)
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
        # Fallback: usa timestamp como ID único
        fallback_id = int(time_module.time() * 1000) % 1000000
        logger.warning(f"Usando ID fallback baseado em timestamp: {fallback_id}")
        return fallback_id

def calcular_total(caruru, bobo, desconto):
    """Calcula total com validação e tratamento de erros."""
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

        subtotal = (c + b) * PRECO_BASE
        total = subtotal * (1 - d / 100)

        resultado = round(total, 2)
        logger.info(f"Total calculado: R$ {resultado} (Caruru: {c}, Bobó: {b}, Desconto: {d}%)")
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
# BANCO DE DADOS COM LOCKING E CACHE
# ==============================================================================
def carregar_clientes():
    """Carrega banco de clientes com file locking."""
    colunas = ["Nome", "Contato", "Observacoes"]

    if not os.path.exists(ARQUIVO_CLIENTES):
        logger.info("Arquivo de clientes não existe, criando novo DataFrame")
        return pd.DataFrame(columns=colunas)

    try:
        with file_lock(ARQUIVO_CLIENTES):
            df = pd.read_csv(ARQUIVO_CLIENTES, dtype=str)
            df = df.fillna("")

            # Garante colunas obrigatórias
            for c in colunas:
                if c not in df.columns:
                    df[c] = ""
                    logger.warning(f"Coluna {c} não encontrada, adicionando")

            logger.info(f"Clientes carregados: {len(df)} registros")
            return df[colunas]

    except Exception as e:
        logger.error(f"Erro ao carregar clientes: {e}", exc_info=True)
        return pd.DataFrame(columns=colunas)

def carregar_pedidos():
    """Carrega banco de pedidos com validação completa e file locking."""
    colunas_padrao = ["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]

    if not os.path.exists(ARQUIVO_PEDIDOS):
        logger.info("Arquivo de pedidos não existe, criando novo DataFrame")
        return pd.DataFrame(columns=colunas_padrao)

    try:
        with file_lock(ARQUIVO_PEDIDOS):
            df = pd.read_csv(ARQUIVO_PEDIDOS)

            # Garante colunas obrigatórias
            for c in colunas_padrao:
                if c not in df.columns:
                    df[c] = None
                    logger.warning(f"Coluna {c} não encontrada, adicionando")

            # Conversões seguras com tratamento de erros
            df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.date
            df["Hora"] = df["Hora"].apply(lambda x: validar_hora(x)[0])

            for col in ["Caruru", "Bobo", "Desconto", "Valor"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

            # Tratamento de IDs duplicados ou inválidos
            df['ID_Pedido'] = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
            if df['ID_Pedido'].duplicated().any():
                logger.warning("IDs duplicados detectados, reindexando")
                df['ID_Pedido'] = range(1, len(df) + 1)
            elif not df.empty and df['ID_Pedido'].max() == 0:
                logger.warning("IDs inválidos detectados, reindexando")
                df['ID_Pedido'] = range(1, len(df) + 1)

            # Normaliza status antigos
            mapa = {
                "Pendente": "🔴 Pendente",
                "Em Produção": "🟡 Em Produção",
                "Entregue": "✅ Entregue",
                "Cancelado": "🚫 Cancelado"
            }
            df['Status'] = df['Status'].replace(mapa)

            # Garante status válido
            invalid_status = ~df['Status'].isin(OPCOES_STATUS)
            if invalid_status.any():
                logger.warning(f"{invalid_status.sum()} pedidos com status inválido, ajustando")
                df.loc[invalid_status, 'Status'] = "🔴 Pendente"

            # Garante tipos de string
            for c in ["Cliente", "Status", "Pagamento", "Contato", "Observacoes"]:
                df[c] = df[c].fillna("").astype(str)

            # Garante pagamento válido
            invalid_payment = ~df['Pagamento'].isin(OPCOES_PAGAMENTO)
            if invalid_payment.any():
                logger.warning(f"{invalid_payment.sum()} pedidos com pagamento inválido, ajustando")
                df.loc[invalid_payment, 'Pagamento'] = "NÃO PAGO"

            logger.info(f"Pedidos carregados: {len(df)} registros")
            return df[colunas_padrao]

    except Exception as e:
        logger.error(f"Erro ao carregar pedidos: {e}", exc_info=True)
        return pd.DataFrame(columns=colunas_padrao)

def salvar_pedidos(df):
    """Salva pedidos com backup automático, file locking e transação."""
    if df is None or not isinstance(df, pd.DataFrame):
        logger.error("DataFrame inválido para salvar")
        return False

    backup_path = None
    try:
        with file_lock(ARQUIVO_PEDIDOS):
            # Cria backup com timestamp antes de salvar
            backup_path = criar_backup_com_timestamp(ARQUIVO_PEDIDOS)

            # Prepara dados para salvar
            salvar = df.copy()
            salvar['Data'] = salvar['Data'].apply(
                lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x
            )
            salvar['Hora'] = salvar['Hora'].apply(
                lambda x: x.strftime('%H:%M') if isinstance(x, time) else str(x) if x else "12:00"
            )

            # Salva em arquivo temporário primeiro (atomic write)
            temp_file = f"{ARQUIVO_PEDIDOS}.tmp"
            salvar.to_csv(temp_file, index=False)

            # Move arquivo temporário para o definitivo (operação atômica)
            shutil.move(temp_file, ARQUIVO_PEDIDOS)

            logger.info(f"Pedidos salvos com sucesso: {len(df)} registros")
            return True

    except Exception as e:
        logger.error(f"Erro ao salvar pedidos: {e}", exc_info=True)

        # Tenta restaurar do backup se houve erro
        if backup_path and os.path.exists(backup_path):
            try:
                shutil.copy(backup_path, ARQUIVO_PEDIDOS)
                logger.info(f"Backup restaurado: {backup_path}")
            except Exception as restore_error:
                logger.error(f"Erro ao restaurar backup: {restore_error}", exc_info=True)

        return False

def salvar_clientes(df):
    """Salva clientes com backup automático, file locking e transação."""
    if df is None or not isinstance(df, pd.DataFrame):
        logger.error("DataFrame inválido para salvar")
        return False

    backup_path = None
    try:
        with file_lock(ARQUIVO_CLIENTES):
            # Cria backup com timestamp antes de salvar
            backup_path = criar_backup_com_timestamp(ARQUIVO_CLIENTES)

            # Salva em arquivo temporário primeiro (atomic write)
            temp_file = f"{ARQUIVO_CLIENTES}.tmp"
            df.to_csv(temp_file, index=False)

            # Move arquivo temporário para o definitivo (operação atômica)
            shutil.move(temp_file, ARQUIVO_CLIENTES)

            logger.info(f"Clientes salvos com sucesso: {len(df)} registros")
            return True

    except Exception as e:
        logger.error(f"Erro ao salvar clientes: {e}", exc_info=True)

        # Tenta restaurar do backup se houve erro
        if backup_path and os.path.exists(backup_path):
            try:
                shutil.copy(backup_path, ARQUIVO_CLIENTES)
                logger.info(f"Backup restaurado: {backup_path}")
            except Exception as restore_error:
                logger.error(f"Erro ao restaurar backup: {restore_error}", exc_info=True)

        return False

# ==============================================================================
# HISTÓRICO DE ALTERAÇÕES
# ==============================================================================
def registrar_alteracao(tipo, id_pedido, campo, valor_antigo, valor_novo):
    """Registra alterações para auditoria."""
    try:
        registro = {
            "Timestamp": agora_brasil().strftime("%Y-%m-%d %H:%M:%S"),
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
        p.drawCentredString(300, y_ass - 30, f"Emitido em: {agora_brasil().strftime('%d/%m/%Y %H:%M')}")
        
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
        p.drawString(30, 30, f"Gerado em: {agora_brasil().strftime('%d/%m/%Y %H:%M')}")
        
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
        p.drawString(30, 30, f"Total: {len(df_clientes)} clientes | Gerado em: {agora_brasil().strftime('%d/%m/%Y %H:%M')}")
        
        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.error(f"Erro gerar PDF clientes: {e}")
        return None

# ==============================================================================
# FUNÇÕES AUXILIARES DE UI
# ==============================================================================

def get_status_badge(status):
    """Retorna badge HTML colorido para status"""
    cores = {
        "✅ Entregue": ("#10b981", "#d1fae5"),  # Verde
        "🔴 Pendente": ("#ef4444", "#fee2e2"),  # Vermelho
        "🟡 Em Produção": ("#f59e0b", "#fef3c7"),  # Amarelo
        "🚫 Cancelado": ("#6b7280", "#f3f4f6"),  # Cinza
    }

    cor_texto, cor_fundo = cores.get(status, ("#6b7280", "#f3f4f6"))

    return f"""
        <span style="
            background-color: {cor_fundo};
            color: {cor_texto};
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.875rem;
            font-weight: 600;
            display: inline-block;
            border: 1px solid {cor_texto}40;
        ">{status}</span>
    """

def get_pagamento_badge(pagamento):
    """Retorna badge HTML colorido para pagamento"""
    cores = {
        "PAGO": ("#10b981", "#d1fae5"),  # Verde
        "NÃO PAGO": ("#ef4444", "#fee2e2"),  # Vermelho
        "METADE": ("#f59e0b", "#fef3c7"),  # Amarelo
    }

    cor_texto, cor_fundo = cores.get(pagamento, ("#6b7280", "#f3f4f6"))

    return f"""
        <span style="
            background-color: {cor_fundo};
            color: {cor_texto};
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.875rem;
            font-weight: 600;
            display: inline-block;
            border: 1px solid {cor_texto}40;
        ">{pagamento}</span>
    """

def get_valor_destaque(valor):
    """Retorna HTML com valor monetário em destaque"""
    return f"""
        <span style="
            color: #059669;
            font-weight: 700;
            font-size: 1.05rem;
        ">R$ {valor:.2f}</span>
    """

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
            "📅 Pedidos do Dia",
            "Novo Pedido",
            "Gerenciar Tudo",
            "📜 Histórico",
            "🖨️ Relatórios & Recibos",
            "📢 Promoções",
            "👥 Cadastrar Clientes",
            "🛠️ Manutenção"
        ]
    )
    st.divider()
    
    # Mini resumo
    df_hoje = st.session_state.pedidos[st.session_state.pedidos['Data'] == hoje_brasil()]
    if not df_hoje.empty:
        pend = df_hoje[~df_hoje['Status'].str.contains("Entregue|Cancelado", na=False)]
        st.caption(f"📅 Hoje: {len(df_hoje)} pedidos")
        st.caption(f"⏳ Pendentes: {len(pend)}")
    
    st.divider()
    st.caption(f"Versão {VERSAO}")

# ==============================================================================
# PÁGINAS
# ==============================================================================

# --- PEDIDOS DO DIA ---
if menu == "📅 Pedidos do Dia":
    st.title("📅 Pedidos do Dia")
    df = st.session_state.pedidos
    
    if df.empty:
        st.info("Sem dados cadastrados.")
    else:
        dt_filter = st.date_input("📅 Data:", hoje_brasil(), format="DD/MM/YYYY")
        df_dia = df[df['Data'] == dt_filter].copy()
        # Excluir pedidos entregues (aparecem apenas no Histórico)
        df_dia = df_dia[df_dia['Status'] != "✅ Entregue"]

        # Filtro de Ordenação
        col_ord1, col_ord2 = st.columns([3, 1])
        with col_ord2:
            ordem_dia = st.selectbox("Ordenar por", [
                "⏰ Hora (crescente)",
                "⏰ Hora (decrescente)",
                "💵 Valor (maior)",
                "💵 Valor (menor)",
                "👤 Cliente (A-Z)",
                "👤 Cliente (Z-A)",
                "📊 Status",
                "🆔 ID (maior)",
                "🆔 ID (menor)"
            ], index=0, key="ordem_pedidos_dia")

        # Aplica ordenação escolhida
        try:
            if ordem_dia == "⏰ Hora (crescente)":
                df_dia['h_sort'] = df_dia['Hora'].apply(lambda x: x if isinstance(x, time) else time(23, 59))
                df_dia = df_dia.sort_values('h_sort').drop(columns=['h_sort'])
            elif ordem_dia == "⏰ Hora (decrescente)":
                df_dia['h_sort'] = df_dia['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
                df_dia = df_dia.sort_values('h_sort', ascending=False).drop(columns=['h_sort'])
            elif ordem_dia == "💵 Valor (maior)":
                df_dia = df_dia.sort_values('Valor', ascending=False)
            elif ordem_dia == "💵 Valor (menor)":
                df_dia = df_dia.sort_values('Valor', ascending=True)
            elif ordem_dia == "👤 Cliente (A-Z)":
                df_dia = df_dia.sort_values('Cliente', ascending=True)
            elif ordem_dia == "👤 Cliente (Z-A)":
                df_dia = df_dia.sort_values('Cliente', ascending=False)
            elif ordem_dia == "📊 Status":
                df_dia = df_dia.sort_values('Status', ascending=True)
            elif ordem_dia == "🆔 ID (maior)":
                df_dia = df_dia.sort_values('ID_Pedido', ascending=False)
            elif ordem_dia == "🆔 ID (menor)":
                df_dia = df_dia.sort_values('ID_Pedido', ascending=True)
        except Exception as e:
            logger.warning(f"Erro ao ordenar pedidos do dia: {e}")
            pass
        
        # Métricas
        c1, c2, c3, c4 = st.columns(4)
        
        # Pedidos pendentes (não entregues e não cancelados)
        pend = df_dia[
            (~df_dia['Status'].str.contains("Entregue", na=False)) & 
            (~df_dia['Status'].str.contains("Cancelado", na=False))
        ]
        
        # Faturamento: soma de todos EXCETO cancelados
        df_nao_cancelados = df_dia[~df_dia['Status'].str.contains("Cancelado", na=False)]
        faturamento = df_nao_cancelados['Valor'].sum()
        
        # A Receber: 
        # - NÃO PAGO = 100% do valor
        # - METADE = 50% do valor (a outra metade já foi paga)
        # - PAGO = 0
        # - Cancelados não entram
        valor_nao_pago = df_nao_cancelados[df_nao_cancelados['Pagamento'] == 'NÃO PAGO']['Valor'].sum()
        valor_metade = df_nao_cancelados[df_nao_cancelados['Pagamento'] == 'METADE']['Valor'].sum() * 0.5
        a_receber = valor_nao_pago + valor_metade
        
        c1.metric("🥘 Caruru (Pend)", int(pend['Caruru'].sum()))
        c2.metric("🦐 Bobó (Pend)", int(pend['Bobo'].sum()))
        c3.metric("💰 Faturamento", f"R$ {faturamento:,.2f}")
        c4.metric("📥 A Receber", f"R$ {a_receber:,.2f}", delta_color="inverse")
        
        st.divider()
        st.subheader("📋 Entregas do Dia")

        if not df_dia.empty:
            # Lista de pedidos compacta com bordas sutis
            linha_num = 0
            for idx, pedido in df_dia.iterrows():
                with st.container():
                    st.markdown(f"""
                        <style>
                        div[data-testid="stVerticalBlock"] > div:nth-child({linha_num + 1}) {{
                            padding: 0px;
                            margin: 0px;
                            line-height: 1.2;
                        }}
                        </style>
                    """, unsafe_allow_html=True)

                    col1, col2, col3, col4, col5, col6, col7, col8, col9 = st.columns([0.4, 1.5, 0.7, 0.7, 0.7, 0.9, 0.9, 0.3, 0.3])

                    with col1:
                        st.markdown(f"<div style='font-size:1.05rem; font-weight:700; color:#1f2937;'>#{int(pedido['ID_Pedido'])}</div>", unsafe_allow_html=True)
                    with col2:
                        st.markdown(f"<div style='font-size:0.9rem; font-weight:500; color:#374151;'>👤 {pedido['Cliente']}</div>", unsafe_allow_html=True)
                    with col3:
                        hora_str = pedido['Hora'].strftime('%H:%M') if isinstance(pedido['Hora'], time) else str(pedido['Hora'])[:5]
                        st.markdown(f"<div style='font-size:0.85rem; color:#6b7280;'>⏰ {hora_str}</div>", unsafe_allow_html=True)
                    with col4:
                        st.markdown(f"<div style='font-size:0.8rem; color:#6b7280;'>🥘 {int(pedido['Caruru'])} 🦐 {int(pedido['Bobo'])}</div>", unsafe_allow_html=True)
                    with col5:
                        st.markdown(get_valor_destaque(pedido['Valor']), unsafe_allow_html=True)
                    with col6:
                        st.markdown(get_status_badge(pedido['Status']), unsafe_allow_html=True)
                    with col7:
                        st.markdown(get_pagamento_badge(pedido['Pagamento']), unsafe_allow_html=True)
                    with col8:
                        if st.button("👁️", key=f"ver_{pedido['ID_Pedido']}", help="Visualizar", use_container_width=True):
                            st.session_state[f"visualizar_{pedido['ID_Pedido']}"] = not st.session_state.get(f"visualizar_{pedido['ID_Pedido']}", False)
                            st.rerun()
                    with col9:
                        if st.button("✏️", key=f"edit_{pedido['ID_Pedido']}", help="Editar", use_container_width=True):
                            st.session_state[f"editando_{pedido['ID_Pedido']}"] = not st.session_state.get(f"editando_{pedido['ID_Pedido']}", False)
                            st.rerun()

                    # Visualização detalhada
                    if st.session_state.get(f"visualizar_{pedido['ID_Pedido']}", False):
                        with st.expander("📋 Detalhes Completos", expanded=True):
                            col_det1, col_det2 = st.columns(2)
                            with col_det1:
                                st.markdown(f"""
                                **🆔 ID:** {int(pedido['ID_Pedido'])}
                                **👤 Cliente:** {pedido['Cliente']}
                                **📱 Contato:** {pedido['Contato']}
                                **📅 Data:** {pedido['Data'].strftime('%d/%m/%Y') if hasattr(pedido['Data'], 'strftime') else pedido['Data']}
                                **⏰ Hora:** {hora_str}
                                """)
                            with col_det2:
                                st.markdown(f"""
                                **🥘 Caruru:** {int(pedido['Caruru'])}
                                **🦐 Bobó:** {int(pedido['Bobo'])}
                                **💸 Desconto:** {pedido['Desconto']:.0f}%
                                **💰 Valor Total:** R$ {pedido['Valor']:.2f}
                                **📊 Status:** {pedido['Status']}
                                **💳 Pagamento:** {pedido['Pagamento']}
                                """)
                            if pedido['Observacoes']:
                                st.markdown(f"**📝 Observações:**")
                                st.info(pedido['Observacoes'])

                            if st.button("✖️ Fechar", key=f"fechar_vis_{pedido['ID_Pedido']}", use_container_width=True):
                                st.session_state[f"visualizar_{pedido['ID_Pedido']}"] = False
                                st.rerun()

                    # Modo de edição
                    if st.session_state.get(f"editando_{pedido['ID_Pedido']}", False):
                        with st.expander("✏️ Editar Pedido", expanded=True):
                            with st.form(f"form_edit_{pedido['ID_Pedido']}"):
                                # Linha 1: Status, Pagamento, Desconto
                                edit_col1, edit_col2, edit_col3 = st.columns(3)
                                with edit_col1:
                                    novo_status = st.selectbox("📊 Status", OPCOES_STATUS,
                                                              index=OPCOES_STATUS.index(pedido['Status']) if pedido['Status'] in OPCOES_STATUS else 0,
                                                              key=f"status_{pedido['ID_Pedido']}")
                                with edit_col2:
                                    novo_pagamento = st.selectbox("💳 Pagamento", OPCOES_PAGAMENTO,
                                                                 index=OPCOES_PAGAMENTO.index(pedido['Pagamento']) if pedido['Pagamento'] in OPCOES_PAGAMENTO else 1,
                                                                 key=f"pag_{pedido['ID_Pedido']}")
                                with edit_col3:
                                    novo_desconto = st.number_input("💸 Desconto %", min_value=0, max_value=100, value=int(pedido['Desconto']),
                                                                   key=f"desc_{pedido['ID_Pedido']}")

                                # Linha 2: Caruru, Bobó
                                edit_col4, edit_col5 = st.columns(2)
                                with edit_col4:
                                    novo_caruru = st.number_input("🥘 Caruru", min_value=0, max_value=999, value=int(pedido['Caruru']),
                                                                 key=f"car_{pedido['ID_Pedido']}")
                                with edit_col5:
                                    novo_bobo = st.number_input("🦐 Bobó", min_value=0, max_value=999, value=int(pedido['Bobo']),
                                                               key=f"bob_{pedido['ID_Pedido']}")

                                # Linha 3: Observações (largura total)
                                novas_obs = st.text_area("📝 Observações", value=pedido['Observacoes'], height=150,
                                                        key=f"obs_{pedido['ID_Pedido']}")

                                col_save, col_cancel, col_delete = st.columns([2, 2, 1])
                                with col_save:
                                    salvar = st.form_submit_button("💾 Salvar", use_container_width=True, type="primary")
                                with col_cancel:
                                    cancelar = st.form_submit_button("❌ Cancelar", use_container_width=True)
                                with col_delete:
                                    excluir = st.form_submit_button("🗑️", use_container_width=True)

                                if salvar:
                                    if novo_caruru == 0 and novo_bobo == 0:
                                        st.error("❌ Pedido deve ter pelo menos 1 item")
                                    else:
                                        campos = {
                                            "Status": novo_status,
                                            "Pagamento": novo_pagamento,
                                            "Caruru": novo_caruru,
                                            "Bobo": novo_bobo,
                                            "Desconto": novo_desconto,
                                            "Observacoes": novas_obs
                                        }
                                        sucesso, msg = atualizar_pedido(int(pedido['ID_Pedido']), campos)
                                        if sucesso:
                                            st.toast(f"✅ Pedido #{int(pedido['ID_Pedido'])} atualizado!", icon="✅")
                                            st.session_state[f"editando_{pedido['ID_Pedido']}"] = False
                                            st.rerun()
                                        else:
                                            st.error(msg)

                                if cancelar:
                                    st.session_state[f"editando_{pedido['ID_Pedido']}"] = False
                                    st.rerun()

                                if excluir:
                                    st.warning("⚠️ Para excluir, confirme abaixo:")
                                    if st.checkbox(f"Confirmo exclusão do pedido #{int(pedido['ID_Pedido'])}", key=f"conf_del_{pedido['ID_Pedido']}"):
                                        sucesso, msg = excluir_pedido(int(pedido['ID_Pedido']), "Excluído via interface")
                                        if sucesso:
                                            st.toast(f"🗑️ Pedido #{int(pedido['ID_Pedido'])} excluído!", icon="🗑️")
                                            st.session_state[f"editando_{pedido['ID_Pedido']}"] = False
                                            st.rerun()
                                        else:
                                            st.error(msg)

                # Incrementa contador para zebra stripes
                linha_num += 1
        else:
            st.info(f"Nenhum pedido para {dt_filter.strftime('%d/%m/%Y')}")

# --- NOVO PEDIDO ---
elif menu == "Novo Pedido":
    st.title("📝 Novo Pedido")
    
    # Botão para limpar o formulário
    col_titulo, col_limpar = st.columns([4, 1])
    with col_limpar:
        if st.button("🔄 Limpar", help="Limpar todos os campos do formulário"):
            # Remove todas as keys relacionadas ao formulário
            keys_to_delete = ['cliente_novo_index', 'sel_cliente_novo', 'resetar_cliente_novo']
            for key in keys_to_delete:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

    # Verifica se deve resetar o cliente (após salvar pedido)
    if st.session_state.get('resetar_cliente_novo', False):
        # Deleta as keys do selectbox para forçar reset
        if 'sel_cliente_novo' in st.session_state:
            del st.session_state['sel_cliente_novo']
        if 'cliente_novo_index' in st.session_state:
            del st.session_state['cliente_novo_index']
        st.session_state.resetar_cliente_novo = False
        logger.info("Formulário de novo pedido resetado com sucesso")

    # Inicializa índice do cliente (sempre volta para 0 = "-- Selecione --")
    if 'cliente_novo_index' not in st.session_state:
        st.session_state.cliente_novo_index = 0

    # Carrega lista de clientes
    try:
        clis = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
    except:
        clis = []

    lista_clientes = ["-- Selecione --"] + clis

    st.markdown("### 1️⃣ Cliente")

    # Selectbox do cliente FORA do form para poder buscar o contato
    c_sel = st.selectbox(
        "👤 Nome do Cliente",
        lista_clientes,
        index=st.session_state.cliente_novo_index,
        key="sel_cliente_novo"
    )
    
    # Busca o contato do cliente selecionado
    contato_cliente = ""
    if c_sel and c_sel != "-- Selecione --":
        try:
            res = st.session_state.clientes[st.session_state.clientes['Nome'] == c_sel]
            if not res.empty:
                contato_cliente = str(res.iloc[0]['Contato']) if pd.notna(res.iloc[0]['Contato']) else ""
        except:
            contato_cliente = ""
    else:
        c_sel = ""  # Reseta para vazio se for "-- Selecione --"
    
    if not c_sel:
        st.info("💡 Selecione um cliente cadastrado ou cadastre um novo em '👥 Cadastrar Clientes'")
    else:
        st.success(f"📱 Contato encontrado: **{contato_cliente}**" if contato_cliente else "⚠️ Cliente sem telefone cadastrado")
    
    st.markdown("### 2️⃣ Dados do Pedido")
    
    # Usar form com clear_on_submit para limpar automaticamente
    with st.form("form_novo_pedido", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            cont = st.text_input("📱 WhatsApp", value=contato_cliente, placeholder="79999999999")
        with c2:
            dt = st.date_input("📅 Data Entrega", min_value=hoje_brasil(), format="DD/MM/YYYY")
        with c3:
            h_ent = st.time_input("⏰ Hora Retirada", value=time(12, 0), help="Horário que o cliente vai retirar o pedido")
        
        st.markdown("### 3️⃣ Itens do Pedido")
        c3, c4, c5 = st.columns(3)
        with c3:
            qc = st.number_input("🥘 Caruru (qtd)", min_value=0, max_value=999, step=1, value=0)
        with c4:
            qb = st.number_input("🦐 Bobó (qtd)", min_value=0, max_value=999, step=1, value=0)
        with c5:
            dc = st.number_input("💸 Desconto %", min_value=0, max_value=100, step=5, value=0)
        
        # Preview do valor (dentro do form não atualiza em tempo real, mas mostra o cálculo)
        st.caption(f"💵 Preço unitário: R$ {PRECO_BASE:.2f} | Cálculo: (Caruru + Bobó) × R$ {PRECO_BASE:.2f} - Desconto%")
        
        obs = st.text_area("📝 Observações", placeholder="Ex: Sem pimenta, entregar na portaria...")
        
        c6, c7 = st.columns(2)
        with c6:
            pg = st.selectbox("💳 Pagamento", OPCOES_PAGAMENTO)
        with c7:
            stt = st.selectbox("📊 Status", OPCOES_STATUS)
        
        # Botão de salvar
        submitted = st.form_submit_button("💾 SALVAR PEDIDO", use_container_width=True, type="primary")
        
        if submitted:
            # Usa o cliente selecionado FORA do form
            cliente_final = c_sel if c_sel and c_sel != "-- Selecione --" else ""
            
            id_criado, erros, avisos = criar_pedido(
                cliente=cliente_final,
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
                st.toast(f"✅ Pedido #{id_criado} criado com sucesso!", icon="✅")
                st.balloons()
                # Seta flag para resetar o cliente na próxima execução
                st.session_state.resetar_cliente_novo = True
                st.rerun()
    
    # Mostrar valor estimado fora do form (para referência)
    st.divider()
    st.markdown("### 💰 Calculadora de Valor")
    calc_c1, calc_c2, calc_c3, calc_c4 = st.columns(4)
    with calc_c1:
        calc_car = st.number_input("Caruru", min_value=0, max_value=999, step=1, value=0, key="calc_car")
    with calc_c2:
        calc_bob = st.number_input("Bobó", min_value=0, max_value=999, step=1, value=0, key="calc_bob")
    with calc_c3:
        calc_desc = st.number_input("Desc %", min_value=0, max_value=100, step=5, value=0, key="calc_desc")
    with calc_c4:
        valor_calc = calcular_total(calc_car, calc_bob, calc_desc)
        st.metric("Total", f"R$ {valor_calc:.2f}")

# --- GERENCIAR TUDO ---
elif menu == "Gerenciar Tudo":
    st.title("📦 Todos os Pedidos")
    
    df = st.session_state.pedidos

    if not df.empty:
        # Busca rápida por cliente
        st.markdown("### 🔍 Busca Rápida")
        busca_cliente = st.text_input(
            "Digite o nome do cliente para filtrar:",
            placeholder="Ex: João, Maria, etc...",
            help="A lista será filtrada conforme você digita",
            key="busca_cliente_todos"
        )

        st.divider()

        # Filtros e Ordenação
        with st.expander("🔍 Filtros e Ordenação", expanded=False):
            col_f1, col_f2, col_f3, col_f4 = st.columns(4)
            with col_f1:
                f_status = st.multiselect("Status", OPCOES_STATUS, default=OPCOES_STATUS)
            with col_f2:
                f_pagto = st.multiselect("Pagamento", OPCOES_PAGAMENTO, default=OPCOES_PAGAMENTO)
            with col_f3:
                f_periodo = st.selectbox("Período", ["Todos", "Hoje", "Esta Semana", "Este Mês"])
            with col_f4:
                f_ordem = st.selectbox("Ordenar por", [
                    "📅 Data (mais recente)",
                    "📅 Data (mais antiga)",
                    "💵 Valor (maior)",
                    "💵 Valor (menor)",
                    "👤 Cliente (A-Z)",
                    "👤 Cliente (Z-A)",
                    "📊 Status",
                    "🆔 ID (maior)",
                    "🆔 ID (menor)"
                ], index=1)

        # Aplica filtros
        df_view = df.copy()
        # Excluir pedidos entregues (aparecem apenas no Histórico)
        df_view = df_view[df_view['Status'] != "✅ Entregue"]
        df_view = df_view[df_view['Status'].isin(f_status)]
        df_view = df_view[df_view['Pagamento'].isin(f_pagto)]

        # Filtro de busca por cliente (case insensitive)
        if busca_cliente:
            df_view = df_view[df_view['Cliente'].str.contains(busca_cliente, case=False, na=False)]

        if f_periodo == "Hoje":
            df_view = df_view[df_view['Data'] == hoje_brasil()]
        elif f_periodo == "Esta Semana":
            inicio_semana = hoje_brasil() - timedelta(days=hoje_brasil().weekday())
            df_view = df_view[df_view['Data'] >= inicio_semana]
        elif f_periodo == "Este Mês":
            inicio_mes = hoje_brasil().replace(day=1)
            df_view = df_view[df_view['Data'] >= inicio_mes]

        # Aplica ordenação escolhida
        try:
            if f_ordem == "📅 Data (mais recente)":
                df_view['sort_hora'] = df_view['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
                df_view = df_view.sort_values(['Data', 'sort_hora'], ascending=[False, True]).drop(columns=['sort_hora'])
            elif f_ordem == "📅 Data (mais antiga)":
                df_view['sort_hora'] = df_view['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
                df_view = df_view.sort_values(['Data', 'sort_hora'], ascending=[True, True]).drop(columns=['sort_hora'])
            elif f_ordem == "💵 Valor (maior)":
                df_view = df_view.sort_values('Valor', ascending=False)
            elif f_ordem == "💵 Valor (menor)":
                df_view = df_view.sort_values('Valor', ascending=True)
            elif f_ordem == "👤 Cliente (A-Z)":
                df_view = df_view.sort_values('Cliente', ascending=True)
            elif f_ordem == "👤 Cliente (Z-A)":
                df_view = df_view.sort_values('Cliente', ascending=False)
            elif f_ordem == "📊 Status":
                df_view = df_view.sort_values('Status', ascending=True)
            elif f_ordem == "🆔 ID (maior)":
                df_view = df_view.sort_values('ID_Pedido', ascending=False)
            elif f_ordem == "🆔 ID (menor)":
                df_view = df_view.sort_values('ID_Pedido', ascending=True)
        except Exception as e:
            logger.warning(f"Erro ao ordenar: {e}")
            pass
        
        # Métricas com totais de caruru e bobó
        total_caruru = df_view['Caruru'].sum()
        total_bobo = df_view['Bobo'].sum()
        st.markdown(f"**{len(df_view)}** pedidos encontrados | **Total:** R$ {df_view['Valor'].sum():,.2f} | **🥘 Caruru:** {int(total_caruru)} | **🦐 Bobó:** {int(total_bobo)}")

        # Lista de pedidos com visualização e edição inline
        if df_view.empty:
            st.info("Nenhum pedido encontrado com os filtros aplicados.")
        else:
            # Lista de pedidos compacta com bordas sutis
            linha_num = 0
            for idx, pedido in df_view.iterrows():
                with st.container():
                    st.markdown(f"""
                        <style>
                        div[data-testid="stVerticalBlock"] > div:nth-child({linha_num + 1}) {{
                            padding: 0px;
                            margin: 0px;
                            line-height: 1.2;
                        }}
                        </style>
                    """, unsafe_allow_html=True)

                    col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([0.4, 1.5, 0.8, 0.7, 0.9, 0.9, 0.3, 0.3])

                    with col1:
                        st.markdown(f"<div style='font-size:1.05rem; font-weight:700; color:#1f2937;'>#{int(pedido['ID_Pedido'])}</div>", unsafe_allow_html=True)
                    with col2:
                        st.markdown(f"<div style='font-size:0.9rem; font-weight:500; color:#374151;'>👤 {pedido['Cliente']}</div>", unsafe_allow_html=True)
                    with col3:
                        data_str = pedido['Data'].strftime('%d/%m/%Y') if hasattr(pedido['Data'], 'strftime') else str(pedido['Data'])
                        hora_str = pedido['Hora'].strftime('%H:%M') if hasattr(pedido['Hora'], 'strftime') else str(pedido['Hora'])
                        st.markdown(f"<div style='font-size:0.8rem; color:#6b7280;'>📅 {data_str}<br>⏰ {hora_str}</div>", unsafe_allow_html=True)
                    with col4:
                        st.markdown(get_valor_destaque(pedido['Valor']), unsafe_allow_html=True)
                    with col5:
                        st.markdown(get_status_badge(pedido['Status']), unsafe_allow_html=True)
                    with col6:
                        st.markdown(get_pagamento_badge(pedido['Pagamento']), unsafe_allow_html=True)
                    with col7:
                        if st.button("👁️", key=f"ver_all_{pedido['ID_Pedido']}", help="Visualizar", use_container_width=True):
                            st.session_state[f"visualizar_all_{pedido['ID_Pedido']}"] = not st.session_state.get(f"visualizar_all_{pedido['ID_Pedido']}", False)
                            st.rerun()
                    with col8:
                        if st.button("✏️", key=f"edit_all_{pedido['ID_Pedido']}", help="Editar", use_container_width=True):
                            st.session_state[f"editando_all_{pedido['ID_Pedido']}"] = not st.session_state.get(f"editando_all_{pedido['ID_Pedido']}", False)
                            st.rerun()

                # Expander para visualização
                if st.session_state.get(f"visualizar_all_{pedido['ID_Pedido']}", False):
                    with st.expander("📋 Detalhes Completos", expanded=True):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown(f"**👤 Cliente:** {pedido['Cliente']}")
                            st.markdown(f"**📱 Contato:** {pedido['Contato']}")
                            st.markdown(f"**📅 Data Entrega:** {pedido['Data'].strftime('%d/%m/%Y') if hasattr(pedido['Data'], 'strftime') else pedido['Data']}")
                            st.markdown(f"**⏰ Hora Retirada:** {pedido['Hora'].strftime('%H:%M') if hasattr(pedido['Hora'], 'strftime') else pedido['Hora']}")
                        with col_b:
                            st.markdown(f"**🥘 Caruru:** {int(pedido['Caruru'])} un.")
                            st.markdown(f"**🦐 Bobó:** {int(pedido['Bobo'])} un.")
                            st.markdown(f"**💸 Desconto:** {int(pedido['Desconto'])}%")
                            st.markdown(f"**💵 Valor Total:** R$ {pedido['Valor']:.2f}")

                        st.markdown("---")
                        col_c, col_d = st.columns(2)
                        with col_c:
                            st.markdown(f"**💳 Pagamento:** {pedido['Pagamento']}")
                        with col_d:
                            st.markdown(f"**📊 Status:** {pedido['Status']}")

                        if pedido['Observacoes']:
                            st.markdown("**📝 Observações:**")
                            st.info(pedido['Observacoes'])

                        if st.button("✖️ Fechar", key=f"fechar_vis_all_{pedido['ID_Pedido']}"):
                            st.session_state[f"visualizar_all_{pedido['ID_Pedido']}"] = False
                            st.rerun()

                # Expander para edição
                if st.session_state.get(f"editando_all_{pedido['ID_Pedido']}", False):
                    with st.expander("✏️ Editar Pedido", expanded=True):
                        with st.form(f"form_edit_all_{pedido['ID_Pedido']}"):
                            st.markdown("### 📝 Dados do Pedido")

                            # Cliente e contato
                            col_e1, col_e2 = st.columns(2)
                            with col_e1:
                                clientes_lista = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
                                try:
                                    idx_cliente = clientes_lista.index(pedido['Cliente']) if pedido['Cliente'] in clientes_lista else 0
                                except:
                                    idx_cliente = 0
                                novo_cliente = st.selectbox("👤 Cliente", clientes_lista, index=idx_cliente)
                            with col_e2:
                                novo_contato = st.text_input("📱 Contato", value=str(pedido['Contato']))

                            # Data e hora
                            col_e3, col_e4 = st.columns(2)
                            with col_e3:
                                nova_data = st.date_input("📅 Data Entrega", value=pedido['Data'], format="DD/MM/YYYY")
                            with col_e4:
                                nova_hora = st.time_input("⏰ Hora Retirada", value=pedido['Hora'])

                            # Quantidades
                            col_e5, col_e6, col_e7 = st.columns(3)
                            with col_e5:
                                novo_caruru = st.number_input("🥘 Caruru", min_value=0, max_value=999, value=int(pedido['Caruru']))
                            with col_e6:
                                novo_bobo = st.number_input("🦐 Bobó", min_value=0, max_value=999, value=int(pedido['Bobo']))
                            with col_e7:
                                novo_desconto = st.number_input("💸 Desconto %", min_value=0, max_value=100, value=int(pedido['Desconto']))

                            # Pagamento e status
                            col_e8, col_e9 = st.columns(2)
                            with col_e8:
                                novo_pagamento = st.selectbox("💳 Pagamento", OPCOES_PAGAMENTO, index=OPCOES_PAGAMENTO.index(pedido['Pagamento']) if pedido['Pagamento'] in OPCOES_PAGAMENTO else 0)
                            with col_e9:
                                novo_status = st.selectbox("📊 Status", OPCOES_STATUS, index=OPCOES_STATUS.index(pedido['Status']) if pedido['Status'] in OPCOES_STATUS else 0)

                            # Observações com mais espaço
                            novas_obs = st.text_area("📝 Observações", value=str(pedido['Observacoes']) if pd.notna(pedido['Observacoes']) else "", height=150)

                            # Botões
                            col_e10, col_e11, col_e12 = st.columns([2, 2, 1])
                            with col_e10:
                                salvar = st.form_submit_button("💾 Salvar Alterações", use_container_width=True, type="primary")
                            with col_e11:
                                cancelar = st.form_submit_button("↩️ Cancelar", use_container_width=True)
                            with col_e12:
                                st.markdown("")  # Espaço

                            # Checkbox de confirmação para excluir
                            confirmar_exclusao = st.checkbox("⚠️ Confirmar exclusão do pedido", key=f"confirm_del_all_{pedido['ID_Pedido']}")
                            excluir = st.form_submit_button("🗑️ Excluir Pedido", use_container_width=True, type="secondary", disabled=not confirmar_exclusao)

                            if salvar:
                                # Atualiza o pedido
                                novo_valor = calcular_total(novo_caruru, novo_bobo, novo_desconto)
                                df_atualizado = st.session_state.pedidos.copy()
                                mask = df_atualizado['ID_Pedido'] == pedido['ID_Pedido']

                                df_atualizado.loc[mask, 'Cliente'] = novo_cliente
                                df_atualizado.loc[mask, 'Contato'] = novo_contato
                                df_atualizado.loc[mask, 'Data'] = nova_data
                                df_atualizado.loc[mask, 'Hora'] = nova_hora
                                df_atualizado.loc[mask, 'Caruru'] = novo_caruru
                                df_atualizado.loc[mask, 'Bobo'] = novo_bobo
                                df_atualizado.loc[mask, 'Desconto'] = novo_desconto
                                df_atualizado.loc[mask, 'Valor'] = novo_valor
                                df_atualizado.loc[mask, 'Pagamento'] = novo_pagamento
                                df_atualizado.loc[mask, 'Status'] = novo_status
                                df_atualizado.loc[mask, 'Observacoes'] = novas_obs

                                if salvar_pedidos(df_atualizado):
                                    st.session_state.pedidos = df_atualizado
                                    st.session_state[f"editando_all_{pedido['ID_Pedido']}"] = False
                                    st.toast(f"✅ Pedido #{int(pedido['ID_Pedido'])} atualizado!", icon="✅")
                                    logger.info(f"Pedido {pedido['ID_Pedido']} editado via Gerenciar Tudo")
                                    time_module.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error("❌ Erro ao salvar as alterações.")

                            if cancelar:
                                st.session_state[f"editando_all_{pedido['ID_Pedido']}"] = False
                                st.rerun()

                            if excluir and confirmar_exclusao:
                                df_atualizado = st.session_state.pedidos[st.session_state.pedidos['ID_Pedido'] != pedido['ID_Pedido']]
                                if salvar_pedidos(df_atualizado):
                                    st.session_state.pedidos = df_atualizado
                                    st.session_state[f"editando_all_{pedido['ID_Pedido']}"] = False
                                    st.toast(f"🗑️ Pedido #{int(pedido['ID_Pedido'])} excluído!", icon="🗑️")
                                    logger.info(f"Pedido {pedido['ID_Pedido']} excluído via Gerenciar Tudo")
                                    time_module.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error("❌ Erro ao excluir o pedido.")

                # Incrementa contador para zebra stripes
                linha_num += 1
        
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
                f"backup_caruru_{hoje_brasil()}.zip",
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
                st.toast("Backup restaurado!", icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"Erro: {e}")

# --- HISTÓRICO ---
elif menu == "📜 Histórico":
    st.title("📜 Histórico de Pedidos Entregues")

    df = st.session_state.pedidos

    # Filtrar apenas pedidos entregues
    df_entregues = df[df['Status'] == "✅ Entregue"].copy()

    if df_entregues.empty:
        st.info("📭 Nenhum pedido entregue ainda.")
    else:
        # Ordenação
        col_ord1, col_ord2 = st.columns([3, 1])
        with col_ord2:
            ordem_hist = st.selectbox("Ordenar por", [
                "📅 Data (mais recente)",
                "📅 Data (mais antiga)",
                "💵 Valor (maior)",
                "💵 Valor (menor)",
                "👤 Cliente (A-Z)",
                "👤 Cliente (Z-A)",
                "🆔 ID (maior)",
                "🆔 ID (menor)"
            ], index=0, key="ordem_historico")

        # Aplica ordenação
        try:
            if ordem_hist == "📅 Data (mais recente)":
                df_entregues['sort_hora'] = df_entregues['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
                df_entregues = df_entregues.sort_values(['Data', 'sort_hora'], ascending=[False, True]).drop(columns=['sort_hora'])
            elif ordem_hist == "📅 Data (mais antiga)":
                df_entregues['sort_hora'] = df_entregues['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
                df_entregues = df_entregues.sort_values(['Data', 'sort_hora'], ascending=[True, True]).drop(columns=['sort_hora'])
            elif ordem_hist == "💵 Valor (maior)":
                df_entregues = df_entregues.sort_values('Valor', ascending=False)
            elif ordem_hist == "💵 Valor (menor)":
                df_entregues = df_entregues.sort_values('Valor', ascending=True)
            elif ordem_hist == "👤 Cliente (A-Z)":
                df_entregues = df_entregues.sort_values('Cliente', ascending=True)
            elif ordem_hist == "👤 Cliente (Z-A)":
                df_entregues = df_entregues.sort_values('Cliente', ascending=False)
            elif ordem_hist == "🆔 ID (maior)":
                df_entregues = df_entregues.sort_values('ID_Pedido', ascending=False)
            elif ordem_hist == "🆔 ID (menor)":
                df_entregues = df_entregues.sort_values('ID_Pedido', ascending=True)
        except Exception as e:
            logger.warning(f"Erro ao ordenar histórico: {e}")

        # Métricas
        st.markdown("### 📊 Resumo")
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.metric("📦 Total de Entregas", len(df_entregues))
        with col_m2:
            valor_total = df_entregues['Valor'].sum()
            st.metric("💰 Valor Total", f"R$ {valor_total:.2f}")
        with col_m3:
            df_pagos = df_entregues[df_entregues['Pagamento'] == "PAGO"]
            st.metric("✅ Totalmente Pagos", len(df_pagos))

        st.divider()
        st.subheader("📋 Pedidos Entregues")

        # Lista de pedidos entregues
        linha_num = 0
        for idx, pedido in df_entregues.iterrows():
            with st.container():
                st.markdown(f"""
                    <style>
                    div[data-testid="stVerticalBlock"] > div:nth-child({linha_num + 1}) {{
                        padding: 0px;
                        margin: 0px;
                        line-height: 1.2;
                    }}
                    </style>
                """, unsafe_allow_html=True)

                col1, col2, col3, col4, col5, col6, col7, col8 = st.columns([0.4, 1.5, 0.8, 0.7, 0.9, 0.9, 0.4, 0.4])

                with col1:
                    st.markdown(f"<div style='font-size:1.05rem; font-weight:700; color:#1f2937;'>#{int(pedido['ID_Pedido'])}</div>", unsafe_allow_html=True)
                with col2:
                    st.markdown(f"<div style='font-size:0.9rem; font-weight:500; color:#374151;'>👤 {pedido['Cliente']}</div>", unsafe_allow_html=True)
                with col3:
                    data_str = pedido['Data'].strftime('%d/%m/%Y') if hasattr(pedido['Data'], 'strftime') else str(pedido['Data'])
                    hora_str = pedido['Hora'].strftime('%H:%M') if hasattr(pedido['Hora'], 'strftime') else str(pedido['Hora'])
                    st.markdown(f"<div style='font-size:0.8rem; color:#6b7280;'>📅 {data_str}<br>⏰ {hora_str}</div>", unsafe_allow_html=True)
                with col4:
                    st.markdown(get_valor_destaque(pedido['Valor']), unsafe_allow_html=True)
                with col5:
                    st.markdown(get_status_badge(pedido['Status']), unsafe_allow_html=True)
                with col6:
                    st.markdown(get_pagamento_badge(pedido['Pagamento']), unsafe_allow_html=True)
                with col7:
                    if st.button("👁️", key=f"ver_hist_{pedido['ID_Pedido']}", help="Visualizar", use_container_width=True):
                        st.session_state[f"visualizar_hist_{pedido['ID_Pedido']}"] = not st.session_state.get(f"visualizar_hist_{pedido['ID_Pedido']}", False)
                        st.rerun()
                with col8:
                    if st.button("↩️", key=f"reverter_{pedido['ID_Pedido']}", help="Reverter para Pendente", use_container_width=True):
                        st.session_state[f"reverter_{pedido['ID_Pedido']}"] = True
                        st.rerun()

            # Visualização detalhada
            if st.session_state.get(f"visualizar_hist_{pedido['ID_Pedido']}", False):
                with st.expander("📋 Detalhes Completos", expanded=True):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown(f"**👤 Cliente:** {pedido['Cliente']}")
                        st.markdown(f"**📱 Contato:** {pedido['Contato']}")
                        st.markdown(f"**📅 Data:** {data_str}")
                        st.markdown(f"**⏰ Hora:** {hora_str}")
                    with col_b:
                        st.markdown(f"**🥘 Caruru:** {int(pedido['Caruru'])} potes")
                        st.markdown(f"**🦐 Bobó:** {int(pedido['Bobo'])} potes")
                        st.markdown(f"**💰 Valor:** R$ {pedido['Valor']:.2f}")
                        if pedido.get('Desconto', 0) > 0:
                            st.markdown(f"**💸 Desconto:** {pedido['Desconto']}%")
                    st.markdown(f"**📊 Status:** {pedido['Status']}")
                    st.markdown(f"**💳 Pagamento:** {pedido['Pagamento']}")
                    if pedido.get('Observacoes'):
                        st.markdown(f"**📝 Observações:**\n{pedido['Observacoes']}")

            # Confirmação de reversão
            if st.session_state.get(f"reverter_{pedido['ID_Pedido']}", False):
                with st.expander("⚠️ Confirmar Reversão", expanded=True):
                    st.warning(f"Tem certeza que deseja reverter o pedido #{int(pedido['ID_Pedido'])} de {pedido['Cliente']}?")
                    st.info("O pedido será marcado como '🔴 Pendente' e voltará para as abas principais.")

                    col_conf1, col_conf2, col_conf3 = st.columns([1, 1, 2])
                    with col_conf1:
                        if st.button("✅ Sim, Reverter", key=f"confirmar_reverter_{pedido['ID_Pedido']}", use_container_width=True):
                            try:
                                df_atual = st.session_state.pedidos
                                df_atual.loc[df_atual['ID_Pedido'] == pedido['ID_Pedido'], 'Status'] = "🔴 Pendente"
                                salvar_pedidos(df_atual)
                                st.session_state.pedidos = carregar_pedidos()
                                st.session_state[f"reverter_{pedido['ID_Pedido']}"] = False
                                st.toast(f"↩️ Pedido #{int(pedido['ID_Pedido'])} revertido para Pendente!", icon="↩️")
                                st.rerun()
                            except Exception as e:
                                st.error(f"❌ Erro ao reverter: {e}")
                    with col_conf2:
                        if st.button("❌ Cancelar", key=f"cancelar_reverter_{pedido['ID_Pedido']}", use_container_width=True):
                            st.session_state[f"reverter_{pedido['ID_Pedido']}"] = False
                            st.rerun()

            linha_num += 1

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
            dt = st.date_input("Data:", hoje_brasil(), format="DD/MM/YYYY", key="rel_data")
            df_rel = df[df['Data'] == dt]
            nome = f"Relatorio_{dt.strftime('%d-%m-%Y')}.pdf"
        elif tipo == "Período":
            c1, c2 = st.columns(2)
            with c1:
                dt_ini = st.date_input("De:", hoje_brasil() - timedelta(days=7), format="DD/MM/YYYY")
            with c2:
                dt_fim = st.date_input("Até:", hoje_brasil(), format="DD/MM/YYYY")
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
                        st.toast(f"Cliente '{n}' cadastrado!", icon="✅")
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
                    st.toast("Clientes importados!", icon="✅")
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
                st.toast(f"Cliente '{d}' excluído!", icon="🗑️")
                st.rerun()
        else:
            st.info("Nenhum cliente cadastrado.")

# --- ADMIN ---
elif menu == "🛠️ Manutenção":
    st.title("🛠️ Manutenção do Sistema")

    t1, t2, t3, t4, t5 = st.tabs(["📋 Logs", "📜 Histórico", "💾 Backups", "☁️ Google Sheets", "⚙️ Config"])
    
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
        st.subheader("💾 Gerenciamento de Backups")

        # Informações sobre backups
        st.info("📂 **Localização dos Backups:** Mesma pasta do sistema (arquivos .bak)")

        # Abas internas para organizar funcionalidades
        tab_lista, tab_restaurar, tab_limpar, tab_importar = st.tabs([
            "📊 Listar", "🔄 Restaurar", "🧹 Limpar", "📤 Importar CSV"
        ])

        with tab_lista:
            st.markdown("### 📊 Backups Disponíveis")

            df_backups = listar_backups()

            if not df_backups.empty:
                # Formata para exibição
                df_display = df_backups.copy()
                df_display['Data/Hora'] = df_display['Data/Hora'].dt.strftime('%d/%m/%Y %H:%M:%S')
                df_display['Tamanho'] = df_display['Tamanho_KB'].apply(lambda x: f"{x:.1f} KB")

                st.dataframe(
                    df_display[['Arquivo', 'Origem', 'Data/Hora', 'Tamanho']],
                    use_container_width=True,
                    hide_index=True
                )

                st.caption(f"**Total:** {len(df_backups)} backup(s) | **Espaço:** {df_backups['Tamanho_KB'].sum():.1f} KB")
            else:
                st.info("Nenhum backup encontrado.")

        with tab_restaurar:
            st.markdown("### 🔄 Restaurar Backup")
            st.warning("⚠️ **Atenção:** Restaurar um backup substituirá os dados atuais!")

            df_backups = listar_backups()

            if not df_backups.empty:
                # Agrupa por arquivo de origem
                origens = df_backups['Origem'].unique().tolist()

                origem_selecionada = st.selectbox(
                    "1️⃣ Selecione o arquivo a restaurar:",
                    origens,
                    key="restaurar_origem"
                )

                if origem_selecionada:
                    # Filtra backups da origem selecionada
                    backups_origem = df_backups[df_backups['Origem'] == origem_selecionada]

                    # Formata opções
                    opcoes_backup = {}
                    for _, row in backups_origem.iterrows():
                        label = f"{row['Data/Hora'].strftime('%d/%m/%Y %H:%M:%S')} ({row['Tamanho_KB']:.1f} KB)"
                        opcoes_backup[label] = row['Caminho']

                    backup_selecionado_label = st.selectbox(
                        "2️⃣ Selecione a versão:",
                        opcoes_backup.keys(),
                        key="restaurar_versao"
                    )

                    if backup_selecionado_label:
                        backup_caminho = opcoes_backup[backup_selecionado_label]

                        st.divider()

                        st.markdown("**Resumo da Restauração:**")
                        st.write(f"- **Arquivo:** {origem_selecionada}")
                        st.write(f"- **Versão:** {backup_selecionado_label}")
                        st.write(f"- **Ação:** Um backup de segurança do arquivo atual será criado antes da restauração")

                        confirmar = st.checkbox(
                            "✅ Confirmo que desejo restaurar este backup",
                            key="confirmar_restaurar"
                        )

                        if st.button(
                            "🔄 RESTAURAR BACKUP",
                            type="primary",
                            disabled=not confirmar,
                            use_container_width=True
                        ):
                            sucesso, msg = restaurar_backup(backup_caminho, origem_selecionada)

                            if sucesso:
                                st.success(msg)
                                st.info("💡 Clique em 'Recarregar Dados' na aba Config para aplicar as mudanças")

                                # Botão para recarregar
                                if st.button("🔄 Recarregar Dados Agora", use_container_width=True):
                                    st.session_state.pedidos = carregar_pedidos()
                                    st.session_state.clientes = carregar_clientes()
                                    st.toast("Dados recarregados!", icon="✅")
                                    st.rerun()
                            else:
                                st.error(msg)
            else:
                st.info("Nenhum backup disponível para restaurar.")

        with tab_limpar:
            st.markdown("### 🧹 Limpeza de Backups Antigos")

            df_backups = listar_backups()

            if not df_backups.empty:
                st.write(f"**Backups atuais:** {len(df_backups)} arquivo(s)")

                dias = st.slider(
                    "Remover backups com mais de quantos dias?",
                    min_value=1,
                    max_value=90,
                    value=30,
                    help="Backups mais antigos que este período serão removidos"
                )

                # Calcula quantos seriam removidos
                limite = agora_brasil() - timedelta(days=dias)
                a_remover = df_backups[df_backups['Data/Hora'] < limite]

                st.info(f"📊 Serão removidos **{len(a_remover)}** backup(s) com mais de {dias} dia(s)")

                if len(a_remover) > 0:
                    st.dataframe(
                        a_remover[['Arquivo', 'Data/Hora', 'Tamanho_KB']],
                        use_container_width=True,
                        hide_index=True
                    )

                    confirmar_limpar = st.checkbox(
                        f"✅ Confirmo a remoção de {len(a_remover)} backup(s)",
                        key="confirmar_limpar"
                    )

                    if st.button(
                        "🧹 LIMPAR BACKUPS ANTIGOS",
                        type="primary",
                        disabled=not confirmar_limpar,
                        use_container_width=True
                    ):
                        sucesso, msg = limpar_backups_por_data(dias)
                        if sucesso:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                else:
                    st.success("✅ Nenhum backup antigo para remover!")
            else:
                st.info("Nenhum backup encontrado.")

        with tab_importar:
            st.markdown("### 📤 Importar CSV Externo")
            st.info("💡 Importe arquivos CSV de outras fontes para substituir os dados do sistema")

            destino = st.selectbox(
                "1️⃣ Selecione qual arquivo deseja substituir:",
                ["Pedidos", "Clientes", "Histórico"],
                key="importar_destino"
            )

            arquivo_upload = st.file_uploader(
                "2️⃣ Envie o arquivo CSV:",
                type="csv",
                key="importar_arquivo"
            )

            if arquivo_upload:
                try:
                    # Lê para preview
                    df_preview = pd.read_csv(arquivo_upload)

                    st.markdown("**📋 Preview do Arquivo:**")
                    st.write(f"- **Linhas:** {len(df_preview)}")
                    st.write(f"- **Colunas:** {', '.join(df_preview.columns.tolist())}")

                    st.dataframe(df_preview.head(10), use_container_width=True)

                    st.divider()

                    st.warning(f"⚠️ **Atenção:** O arquivo **{destino}** será substituído!")
                    st.info("✅ Um backup do arquivo atual será criado automaticamente")

                    confirmar_import = st.checkbox(
                        f"✅ Confirmo a importação de {len(df_preview)} registro(s)",
                        key="confirmar_importar"
                    )

                    if st.button(
                        "📤 IMPORTAR CSV",
                        type="primary",
                        disabled=not confirmar_import,
                        use_container_width=True
                    ):
                        # Reseta o ponteiro do arquivo
                        arquivo_upload.seek(0)

                        sucesso, msg, df_importado = importar_csv_externo(arquivo_upload, destino)

                        if sucesso:
                            st.success(msg)
                            st.info("💡 Clique em 'Recarregar Dados' para aplicar as mudanças")

                            # Botão para recarregar
                            if st.button("🔄 Recarregar Dados Agora", use_container_width=True, key="reload_import"):
                                st.session_state.pedidos = carregar_pedidos()
                                st.session_state.clientes = carregar_clientes()
                                st.toast("Dados recarregados!", icon="✅")
                                st.rerun()
                        else:
                            st.error(msg)

                except Exception as e:
                    st.error(f"❌ Erro ao ler arquivo: {e}")

    with t4:
        st.subheader("☁️ Integração Google Sheets")

        st.info("""
        💡 **Por que usar Google Sheets?**
        - ✅ Seus dados ficam seguros na nuvem do Google
        - ✅ Não perde dados quando o Streamlit reinicia
        - ✅ Backup automático do Google (30 dias de histórico)
        - ✅ Acesse e edite dados direto no Google Sheets
        - ✅ Gratuito e confiável
        """)

        # Verifica status
        status_ok, status_msg = verificar_status_sheets()

        if status_ok:
            st.success(status_msg)
        else:
            st.warning(status_msg)

        st.divider()

        # Abas de funcionalidades
        tab_sync, tab_manual, tab_config = st.tabs(["🔄 Sincronização", "📤 Manual", "⚙️ Configurar"])

        with tab_sync:
            st.markdown("### 🔄 Sincronização Automática")

            if not status_ok:
                st.error("❌ Configure as credenciais primeiro na aba '⚙️ Configurar'")
            else:
                col1, col2, col3 = st.columns(3)

                with col1:
                    if st.button("📤 Enviar para Sheets", use_container_width=True, help="Faz backup dos dados locais no Google Sheets"):
                        with st.spinner("Enviando dados..."):
                            sucesso, msg = sincronizar_com_sheets(modo="enviar")
                            if sucesso:
                                st.toast("Dados enviados para Google Sheets!", icon="☁️")
                                st.text(msg)
                            else:
                                st.error(msg)

                with col2:
                    if st.button("📥 Baixar do Sheets", use_container_width=True, help="Restaura dados do Google Sheets"):
                        with st.spinner("Baixando dados..."):
                            sucesso, msg = sincronizar_com_sheets(modo="receber")
                            if sucesso:
                                st.toast("Dados restaurados do Google Sheets!", icon="☁️")
                                st.text(msg)
                                st.rerun()
                            else:
                                st.error(msg)

                with col3:
                    if st.button("🔄 Sincronizar Ambos", use_container_width=True, help="Sincronização bidirecional"):
                        with st.spinner("Sincronizando..."):
                            sucesso, msg = sincronizar_com_sheets(modo="ambos")
                            if sucesso:
                                st.toast("Sincronização completa!", icon="🔄")
                                st.text(msg)
                            else:
                                st.error(msg)

                st.divider()

                st.markdown("**💡 Quando usar cada opção:**")
                st.write("- **📤 Enviar:** Após fazer mudanças no sistema (backup)")
                st.write("- **📥 Baixar:** Para restaurar dados do Sheets")
                st.write("- **🔄 Ambos:** Sincronização completa (cuidado com sobrescrita)")

        with tab_manual:
            st.markdown("### 📤 Operações Manuais")

            if not status_ok:
                st.error("❌ Configure as credenciais primeiro")
            else:
                st.markdown("#### Enviar Dados Específicos")

                tipo_envio = st.selectbox(
                    "Selecione o que deseja enviar:",
                    ["Pedidos", "Clientes", "Ambos"]
                )

                if st.button("📤 Enviar Selecionado", use_container_width=True):
                    try:
                        client = conectar_google_sheets()
                        if client:
                            if tipo_envio in ["Pedidos", "Ambos"]:
                                sucesso, msg = salvar_no_sheets(client, "Pedidos", st.session_state.pedidos)
                                st.info(msg)

                            if tipo_envio in ["Clientes", "Ambos"]:
                                sucesso, msg = salvar_no_sheets(client, "Clientes", st.session_state.clientes)
                                st.info(msg)

                            st.success("✅ Operação concluída!")
                        else:
                            st.error("❌ Erro ao conectar")
                    except Exception as e:
                        st.error(f"❌ Erro: {e}")

                st.divider()

                st.markdown("#### Baixar Dados Específicos")

                tipo_download = st.selectbox(
                    "Selecione o que deseja baixar:",
                    ["Pedidos", "Clientes"],
                    key="download_tipo"
                )

                if st.button("📥 Baixar Selecionado", use_container_width=True):
                    try:
                        client = conectar_google_sheets()
                        if client:
                            if tipo_download == "Pedidos":
                                df, msg = carregar_do_sheets(client, "Pedidos")
                                if df is not None and not df.empty:
                                    st.dataframe(df.head(10), use_container_width=True)
                                    st.info(msg)

                                    if st.button("✅ Confirmar e Aplicar"):
                                        salvar_pedidos(df)
                                        st.session_state.pedidos = carregar_pedidos()
                                        st.success("✅ Pedidos restaurados!")
                                        st.rerun()

                            elif tipo_download == "Clientes":
                                df, msg = carregar_do_sheets(client, "Clientes")
                                if df is not None and not df.empty:
                                    st.dataframe(df.head(10), use_container_width=True)
                                    st.info(msg)

                                    if st.button("✅ Confirmar e Aplicar", key="aplicar_clientes"):
                                        salvar_clientes(df)
                                        st.session_state.clientes = carregar_clientes()
                                        st.success("✅ Clientes restaurados!")
                                        st.rerun()
                        else:
                            st.error("❌ Erro ao conectar")
                    except Exception as e:
                        st.error(f"❌ Erro: {e}")

        with tab_config:
            st.markdown("### ⚙️ Configuração")

            st.markdown("""
            **📋 Passo a Passo para Configurar:**

            1. **Criar Projeto no Google Cloud**
            2. **Ativar APIs necessárias**
            3. **Criar Service Account**
            4. **Baixar credenciais JSON**
            5. **Adicionar credenciais no Streamlit Secrets**

            👉 **Tutorial completo será fornecido após o commit!**
            """)

            st.divider()

            st.markdown("**🔍 Status Atual:**")

            if GSPREAD_AVAILABLE:
                st.success("✅ Biblioteca gspread instalada")
            else:
                st.error("❌ Biblioteca gspread não instalada")
                st.code("pip install gspread google-auth")

            if "gcp_service_account" in st.secrets:
                st.success("✅ Credenciais configuradas")

                # Mostra informações (sem expor dados sensíveis)
                try:
                    creds = dict(st.secrets["gcp_service_account"])
                    st.write(f"- **Project ID:** {creds.get('project_id', 'N/A')}")
                    st.write(f"- **Client Email:** {creds.get('client_email', 'N/A')}")
                except:
                    pass
            else:
                st.warning("⚠️ Credenciais não configuradas")
                st.info("Adicione as credenciais em `.streamlit/secrets.toml`")

            st.divider()

            # Link para a planilha
            if status_ok:
                try:
                    client = conectar_google_sheets()
                    if client:
                        spreadsheet = obter_ou_criar_planilha(client)
                        if spreadsheet:
                            st.markdown(f"**📊 Sua Planilha:**")
                            st.markdown(f"[🔗 Abrir no Google Sheets](https://docs.google.com/spreadsheets/d/{spreadsheet.id})")
                except:
                    pass

    with t5:
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
