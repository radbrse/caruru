"""
Operações de banco de dados (CSV): file locking, backup, carregar/salvar.
"""

import os
import shutil
import fcntl
import time as time_module
import pandas as pd
from datetime import datetime, time
from contextlib import contextmanager

from config import (
    logger, FUSO_BRASIL, agora_brasil,
    ARQUIVO_PEDIDOS, ARQUIVO_CLIENTES, ARQUIVO_HISTORICO,
    MAX_BACKUP_FILES, OPCOES_STATUS, OPCOES_PAGAMENTO
)
from utils import validar_hora, limpar_telefone

# ==============================================================================
# FILE LOCKING
# ==============================================================================
@contextmanager
def file_lock(filepath, timeout=10):
    """Context manager para file locking com timeout."""
    lock_file = f"{filepath}.lock"
    lock_fd = None
    start_time = time_module.time()

    try:
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)

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
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
                if os.path.exists(lock_file):
                    os.remove(lock_file)
                logger.info(f"Lock liberado: {filepath}")
            except Exception as e:
                logger.error(f"Erro ao liberar lock: {e}")

# ==============================================================================
# BACKUPS
# ==============================================================================
def limpar_backups_antigos(arquivo_base):
    """Remove backups antigos mantendo apenas os MAX_BACKUP_FILES mais recentes."""
    try:
        pasta = os.path.dirname(arquivo_base) or "."
        nome_base = os.path.basename(arquivo_base)
        backups = [
            os.path.join(pasta, f) for f in os.listdir(pasta)
            if f.startswith(nome_base) and f.endswith(".bak")
        ]

        if len(backups) > MAX_BACKUP_FILES:
            backups.sort(key=lambda x: os.path.getmtime(x))
            for backup in backups[:-MAX_BACKUP_FILES]:
                os.remove(backup)
                logger.info(f"Backup antigo removido: {backup}")

    except Exception as e:
        logger.error(f"Erro ao limpar backups: {e}")

def criar_backup_com_timestamp(arquivo):
    """Cria backup com timestamp."""
    if os.path.exists(arquivo):
        timestamp = agora_brasil().strftime("%Y%m%d_%H%M%S")
        backup = f"{arquivo}.{timestamp}.bak"
        shutil.copy(arquivo, backup)
        logger.info(f"Backup criado: {backup}")
        limpar_backups_antigos(arquivo)
        return backup
    return None

def listar_backups():
    """Lista todos os backups disponíveis."""
    try:
        backups = []
        pasta = "."

        for arquivo in os.listdir(pasta):
            if ".bak" in arquivo:
                caminho = os.path.join(pasta, arquivo)
                stats = os.stat(caminho)

                if arquivo.count('.') >= 2:
                    partes = arquivo.split('.')
                    origem = '.'.join(partes[:-2])
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
    """Restaura um backup específico."""
    try:
        if not os.path.exists(arquivo_backup):
            logger.error(f"Backup não encontrado: {arquivo_backup}")
            return False, f"❌ Backup não encontrado: {arquivo_backup}"

        if os.path.exists(arquivo_destino):
            backup_seguranca = criar_backup_com_timestamp(arquivo_destino)
            logger.info(f"Backup de segurança criado: {backup_seguranca}")

        with file_lock(arquivo_destino):
            shutil.copy(arquivo_backup, arquivo_destino)
            logger.info(f"Backup restaurado: {arquivo_backup} -> {arquivo_destino}")

        return True, f"✅ Backup restaurado com sucesso!"

    except Exception as e:
        logger.error(f"Erro ao restaurar backup: {e}", exc_info=True)
        return False, f"❌ Erro ao restaurar backup: {e}"

def limpar_backups_por_data(dias):
    """Remove backups com mais de X dias."""
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
    """Importa CSV externo para um dos arquivos do sistema."""
    try:
        destinos_validos = {
            'Pedidos': ARQUIVO_PEDIDOS,
            'Clientes': ARQUIVO_CLIENTES,
            'Histórico': ARQUIVO_HISTORICO
        }

        if destino not in destinos_validos:
            return False, f"❌ Destino inválido: {destino}", None

        arquivo_destino = destinos_validos[destino]

        df_novo = pd.read_csv(arquivo_upload)

        schemas_obrigatorios = {
            'Pedidos': ["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"],
            'Clientes': ["Nome", "Contato", "Observacoes"],
            'Histórico': ["Timestamp", "Tipo", "ID_Pedido", "Campo", "Valor_Antigo", "Valor_Novo"]
        }

        colunas_esperadas = schemas_obrigatorios[destino]
        colunas_recebidas = df_novo.columns.tolist()

        colunas_faltantes = set(colunas_esperadas) - set(colunas_recebidas)
        if colunas_faltantes:
            return False, f"❌ Colunas obrigatórias faltando: {', '.join(sorted(colunas_faltantes))}", None

        colunas_extras = set(colunas_recebidas) - set(colunas_esperadas)
        if colunas_extras:
            logger.warning(f"Colunas extras detectadas no CSV (serão ignoradas): {', '.join(sorted(colunas_extras))}")

        df_novo = df_novo[colunas_esperadas]

        if os.path.exists(arquivo_destino):
            backup = criar_backup_com_timestamp(arquivo_destino)
            logger.info(f"Backup criado antes da importação: {backup}")

        with file_lock(arquivo_destino):
            temp_file = f"{arquivo_destino}.tmp"
            df_novo.to_csv(temp_file, index=False)
            shutil.move(temp_file, arquivo_destino)

        logger.info(f"CSV importado: {destino} ({len(df_novo)} registros)")

        registrar_alteracao(
            "IMPORTAR", 0, destino,
            f"Importação externa",
            f"{len(df_novo)} registros"
        )

        return True, f"✅ {len(df_novo)} registros importados com sucesso!", df_novo

    except Exception as e:
        logger.error(f"Erro ao importar CSV: {e}", exc_info=True)
        return False, f"❌ Erro ao importar: {e}", None

# ==============================================================================
# CARREGAR / SALVAR DADOS
# ==============================================================================
def carregar_clientes():
    """Carrega banco de clientes com file locking e auto-recovery do Google Sheets."""
    import streamlit as st
    colunas = ["Nome", "Contato", "Observacoes"]

    # AUTO-RECOVERY do Google Sheets
    if not os.path.exists(ARQUIVO_CLIENTES):
        try:
            from sheets import conectar_google_sheets, carregar_do_sheets
            if "gcp_service_account" in st.secrets:
                logger.warning("⚠️ Arquivo de clientes não encontrado. Tentando Auto-Recovery do Google Sheets...")
                client = conectar_google_sheets()
                if client:
                    df_cloud, msg = carregar_do_sheets(client, "Clientes")
                    if df_cloud is not None and not df_cloud.empty:
                        if salvar_clientes(df_cloud):
                            logger.info(f"✅ AUTO-RECOVERY: {len(df_cloud)} clientes recuperados do Google Sheets!")
        except Exception as e:
            logger.error(f"❌ Falha no Auto-Recovery de Clientes: {e}")

    if not os.path.exists(ARQUIVO_CLIENTES):
        logger.info("Arquivo de clientes não existe, criando novo DataFrame")
        return pd.DataFrame(columns=colunas)

    try:
        with file_lock(ARQUIVO_CLIENTES):
            df = pd.read_csv(ARQUIVO_CLIENTES, dtype=str)
            df = df.fillna("")

            for c in colunas:
                if c not in df.columns:
                    df[c] = ""
                    logger.warning(f"Coluna {c} não encontrada, adicionando")

            df["Contato"] = df["Contato"].str.replace(".0", "", regex=False)

            logger.info(f"Clientes carregados: {len(df)} registros")
            return df[colunas]

    except Exception as e:
        logger.error(f"Erro ao carregar clientes: {e}", exc_info=True)
        return pd.DataFrame(columns=colunas)

def carregar_pedidos():
    """Carrega banco de pedidos com validação completa, file locking e auto-recovery."""
    import streamlit as st
    colunas_padrao = ["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]

    # AUTO-RECOVERY do Google Sheets
    if not os.path.exists(ARQUIVO_PEDIDOS):
        try:
            from sheets import conectar_google_sheets, carregar_do_sheets
            if "gcp_service_account" in st.secrets:
                logger.warning("⚠️ Arquivo de pedidos não encontrado. Tentando Auto-Recovery do Google Sheets...")
                client = conectar_google_sheets()
                if client:
                    df_cloud, msg = carregar_do_sheets(client, "Pedidos")
                    if df_cloud is not None and not df_cloud.empty:
                        if salvar_pedidos(df_cloud):
                            logger.info(f"✅ AUTO-RECOVERY: {len(df_cloud)} pedidos recuperados do Google Sheets!")
        except Exception as e:
            logger.error(f"❌ Falha no Auto-Recovery de Pedidos: {e}")

    if not os.path.exists(ARQUIVO_PEDIDOS):
        logger.info("Arquivo de pedidos não existe, criando novo DataFrame")
        return pd.DataFrame(columns=colunas_padrao)

    try:
        with file_lock(ARQUIVO_PEDIDOS):
            df = pd.read_csv(ARQUIVO_PEDIDOS, dtype={'Contato': str})

            for c in colunas_padrao:
                if c not in df.columns:
                    df[c] = None
                    logger.warning(f"Coluna {c} não encontrada, adicionando")

            df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.date
            df["Hora"] = df["Hora"].apply(lambda x: validar_hora(x)[0])

            for col in ["Caruru", "Bobo", "Desconto", "Valor"]:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

            df['ID_Pedido'] = pd.to_numeric(df['ID_Pedido'], errors='coerce').fillna(0).astype(int)
            if df['ID_Pedido'].duplicated().any():
                logger.warning("IDs duplicados detectados, reindexando")
                df['ID_Pedido'] = range(1, len(df) + 1)
            elif not df.empty and df['ID_Pedido'].max() == 0:
                logger.warning("IDs inválidos detectados, reindexando")
                df['ID_Pedido'] = range(1, len(df) + 1)

            mapa = {
                "Pendente": "🔴 Pendente",
                "Em Produção": "🟡 Em Produção",
                "Entregue": "✅ Entregue",
                "Cancelado": "🚫 Cancelado"
            }
            df['Status'] = df['Status'].replace(mapa)

            invalid_status = ~df['Status'].isin(OPCOES_STATUS)
            if invalid_status.any():
                logger.warning(f"{invalid_status.sum()} pedidos com status inválido, ajustando")
                df.loc[invalid_status, 'Status'] = "🔴 Pendente"

            for c in ["Cliente", "Status", "Pagamento", "Observacoes"]:
                df[c] = df[c].fillna("").astype(str)

            df["Contato"] = df["Contato"].fillna("").str.replace(".0", "", regex=False)

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
            backup_path = criar_backup_com_timestamp(ARQUIVO_PEDIDOS)

            salvar = df.copy()
            salvar['Data'] = salvar['Data'].apply(
                lambda x: x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else x
            )
            salvar['Hora'] = salvar['Hora'].apply(
                lambda x: x.strftime('%H:%M') if isinstance(x, time) else str(x) if x else "12:00"
            )
            salvar['Contato'] = salvar['Contato'].astype(str).str.replace(".0", "", regex=False)

            temp_file = f"{ARQUIVO_PEDIDOS}.tmp"
            salvar.to_csv(temp_file, index=False)
            shutil.move(temp_file, ARQUIVO_PEDIDOS)

            if os.path.exists(ARQUIVO_PEDIDOS):
                tamanho = os.path.getsize(ARQUIVO_PEDIDOS)
                logger.info(f"✅ Pedidos salvos com sucesso: {len(df)} registros, arquivo: {tamanho} bytes")
            else:
                logger.error(f"❌ ERRO: Arquivo {ARQUIVO_PEDIDOS} não existe após salvar!")
                return False

            return True

    except Exception as e:
        logger.error(f"Erro ao salvar pedidos: {e}", exc_info=True)

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
            backup_path = criar_backup_com_timestamp(ARQUIVO_CLIENTES)

            salvar = df.copy()
            if 'Contato' in salvar.columns:
                salvar['Contato'] = salvar['Contato'].astype(str).str.replace(".0", "", regex=False)

            temp_file = f"{ARQUIVO_CLIENTES}.tmp"
            salvar.to_csv(temp_file, index=False)
            shutil.move(temp_file, ARQUIVO_CLIENTES)

            logger.info(f"Clientes salvos com sucesso: {len(df)} registros")
            return True

    except Exception as e:
        logger.error(f"Erro ao salvar clientes: {e}", exc_info=True)

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
def salvar_historico(df):
    """Salva histórico de alterações com backup automático, file locking e transação."""
    if df is None or not isinstance(df, pd.DataFrame):
        logger.error("DataFrame inválido para salvar histórico")
        return False

    backup_path = None
    try:
        with file_lock(ARQUIVO_HISTORICO):
            backup_path = criar_backup_com_timestamp(ARQUIVO_HISTORICO)

            temp_file = f"{ARQUIVO_HISTORICO}.tmp"
            df.to_csv(temp_file, index=False)
            shutil.move(temp_file, ARQUIVO_HISTORICO)

            logger.info(f"Histórico salvo com sucesso: {len(df)} registros")
            return True

    except Exception as e:
        logger.error(f"Erro ao salvar histórico: {e}", exc_info=True)

        if backup_path and os.path.exists(backup_path):
            try:
                shutil.copy(backup_path, ARQUIVO_HISTORICO)
                logger.info(f"Backup de histórico restaurado: {backup_path}")
            except Exception as restore_error:
                logger.error(f"Erro ao restaurar backup de histórico: {restore_error}", exc_info=True)

        return False

def registrar_alteracao(tipo, id_pedido, campo, valor_antigo, valor_novo):
    """Registra alterações para auditoria. Read+append+write tudo dentro do lock."""
    try:
        registro = {
            "Timestamp": agora_brasil().strftime("%Y-%m-%d %H:%M:%S"),
            "Tipo": tipo,
            "ID_Pedido": id_pedido,
            "Campo": campo,
            "Valor_Antigo": str(valor_antigo)[:100],
            "Valor_Novo": str(valor_novo)[:100]
        }

        backup_path = None
        with file_lock(ARQUIVO_HISTORICO):
            if os.path.exists(ARQUIVO_HISTORICO):
                df = pd.read_csv(ARQUIVO_HISTORICO)
            else:
                df = pd.DataFrame()

            df = pd.concat([df, pd.DataFrame([registro])], ignore_index=True)

            if len(df) > 1000:
                df = df.tail(1000)

            backup_path = criar_backup_com_timestamp(ARQUIVO_HISTORICO)
            temp_file = f"{ARQUIVO_HISTORICO}.tmp"
            df.to_csv(temp_file, index=False)
            shutil.move(temp_file, ARQUIVO_HISTORICO)
            logger.info(f"Alteração registrada: {tipo} - Pedido {id_pedido}")

    except Exception as e:
        logger.error(f"Erro registrar alteração: {e}")
