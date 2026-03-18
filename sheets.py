"""
Integração com Google Sheets: conexão, sincronização, backup na nuvem.
"""

import streamlit as st
import pandas as pd

from config import logger, agora_brasil

# Google Sheets
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False

# ==============================================================================
# CONEXÃO
# ==============================================================================
@st.cache_resource
def conectar_google_sheets():
    """Conecta ao Google Sheets usando credenciais do Streamlit Secrets."""
    if not GSPREAD_AVAILABLE:
        logger.error("gspread não disponível")
        return None

    try:
        if "gcp_service_account" not in st.secrets:
            logger.warning("Credenciais Google Sheets não configuradas")
            return None

        creds_dict = dict(st.secrets["gcp_service_account"])

        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]

        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)

        logger.info("Conectado ao Google Sheets com sucesso")
        return client

    except Exception as e:
        logger.error(f"Erro ao conectar ao Google Sheets: {e}", exc_info=True)
        return None

def obter_ou_criar_planilha(client, nome_planilha="Cantinho do Caruru - Dados"):
    """Obtém a planilha ou cria se não existir."""
    try:
        try:
            spreadsheet = client.open(nome_planilha)
            logger.info(f"Planilha '{nome_planilha}' encontrada")
            return spreadsheet
        except gspread.exceptions.SpreadsheetNotFound:
            spreadsheet = client.create(nome_planilha)
            logger.info(f"Planilha '{nome_planilha}' criada")

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

# ==============================================================================
# SALVAR / CARREGAR
# ==============================================================================
def salvar_no_sheets(client, nome_aba, df):
    """Salva DataFrame no Google Sheets."""
    try:
        spreadsheet = obter_ou_criar_planilha(client)
        if not spreadsheet:
            return False, "❌ Erro ao acessar planilha"

        try:
            worksheet = spreadsheet.worksheet(nome_aba)
        except gspread.exceptions.WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(nome_aba, rows=len(df)+100, cols=len(df.columns))

        df_str = df.copy()
        for col in df_str.columns:
            df_str[col] = df_str[col].astype(str)

        if 'Contato' in df_str.columns:
            df_str['Contato'] = df_str['Contato'].str.replace(".0", "", regex=False)

        dados_completos = [df_str.columns.values.tolist()] + df_str.values.tolist()

        num_linhas = len(dados_completos)
        num_colunas = len(df_str.columns)

        from gspread.utils import rowcol_to_a1
        ultima_celula = rowcol_to_a1(num_linhas, num_colunas)
        range_atualizar = f'A1:{ultima_celula}'

        worksheet.update(range_atualizar, dados_completos)

        try:
            linhas_antigas = worksheet.row_count
            if linhas_antigas > num_linhas:
                inicio_limpar = rowcol_to_a1(num_linhas + 1, 1)
                fim_limpar = rowcol_to_a1(linhas_antigas, num_colunas)
                range_limpar = f'{inicio_limpar}:{fim_limpar}'
                worksheet.batch_clear([range_limpar])
                logger.info(f"🧹 Limpou {linhas_antigas - num_linhas} linhas antigas - Range: {range_limpar}")
        except Exception as e_limpar:
            logger.warning(f"⚠️ Dados salvos OK, mas limpeza de linhas antigas falhou: {e_limpar}")

        logger.info(f"Dados salvos no Sheets: {nome_aba} ({len(df)} linhas)")
        return True, f"✅ {len(df)} registros salvos no Google Sheets"

    except Exception as e:
        logger.error(f"Erro ao salvar no Sheets: {e}", exc_info=True)
        return False, f"❌ Erro ao salvar: {e}"

def carregar_do_sheets(client, nome_aba):
    """Carrega DataFrame do Google Sheets."""
    try:
        spreadsheet = obter_ou_criar_planilha(client)
        if not spreadsheet:
            return None, "❌ Erro ao acessar planilha"

        try:
            worksheet = spreadsheet.worksheet(nome_aba)
        except gspread.exceptions.WorksheetNotFound:
            logger.warning(f"Aba '{nome_aba}' não encontrada")
            return pd.DataFrame(), f"⚠️ Aba '{nome_aba}' não existe (vazia)"

        dados = worksheet.get_all_values()

        if not dados or len(dados) < 2:
            return pd.DataFrame(), f"⚠️ Aba '{nome_aba}' está vazia"

        df = pd.DataFrame(dados[1:], columns=dados[0])

        logger.info(f"Dados carregados do Sheets: {nome_aba} ({len(df)} linhas)")
        return df, f"✅ {len(df)} registros carregados"

    except Exception as e:
        logger.error(f"Erro ao carregar do Sheets: {e}", exc_info=True)
        return None, f"❌ Erro ao carregar: {e}"

# ==============================================================================
# SINCRONIZAÇÃO
# ==============================================================================
def sincronizar_com_sheets(modo="enviar"):
    """
    Sincroniza dados entre CSV local e Google Sheets.

    Modos:
    - "enviar": Faz backup dos dados locais para o Sheets (RECOMENDADO)
    - "receber": Restaura dados do Sheets para o local (CUIDADO: sobrescreve!)

    NOTA: Modo "ambos" foi removido por segurança. Use apenas "enviar" para backup.
    """
    from database import salvar_pedidos, carregar_pedidos, salvar_clientes, carregar_clientes

    try:
        client = conectar_google_sheets()
        if not client:
            return False, "❌ Não foi possível conectar ao Google Sheets"

        resultados = []

        if modo == "enviar":
            envio_ok = True

            df_pedidos = st.session_state.pedidos
            sucesso_pedidos, msg = salvar_no_sheets(client, "Pedidos", df_pedidos)
            resultados.append(f"Pedidos: {msg}")
            if not sucesso_pedidos:
                envio_ok = False

            df_clientes = st.session_state.clientes
            sucesso_clientes, msg = salvar_no_sheets(client, "Clientes", df_clientes)
            resultados.append(f"Clientes: {msg}")
            if not sucesso_clientes:
                envio_ok = False

            if not envio_ok:
                return False, "\n".join(resultados)

            # ✅ CORREÇÃO: Usar append_row nativo do Sheets (append-only, sem race condition)
            try:
                spreadsheet = obter_ou_criar_planilha(client)
                if spreadsheet:
                    worksheet = spreadsheet.worksheet("Backups_Log")
                    nova_linha = [
                        agora_brasil().strftime("%Y-%m-%d %H:%M:%S"),
                        "Backup Automático",
                        len(df_pedidos),
                        len(df_clientes)
                    ]
                    worksheet.append_row(nova_linha)  # ✅ Append atômico
                    logger.info("Backup registrado no log")
            except Exception as e_log:
                logger.warning(f"⚠️ Erro ao registrar backup log: {e_log}")

        elif modo == "receber":
            df_pedidos, msg = carregar_do_sheets(client, "Pedidos")
            if df_pedidos is not None and not df_pedidos.empty:
                if not salvar_pedidos(df_pedidos):
                    return False, "❌ Erro ao salvar pedidos baixados do Sheets"
                st.session_state.pedidos = carregar_pedidos()
                resultados.append(f"Pedidos: {msg}")

            df_clientes, msg = carregar_do_sheets(client, "Clientes")
            if df_clientes is not None and not df_clientes.empty:
                if not salvar_clientes(df_clientes):
                    return False, "❌ Erro ao salvar clientes baixados do Sheets"
                st.session_state.clientes = carregar_clientes()
                resultados.append(f"Clientes: {msg}")
        else:
            return False, f"❌ Modo '{modo}' inválido. Use 'enviar' ou 'receber'."

        return True, "\n".join(resultados)

    except Exception as e:
        logger.error(f"Erro na sincronização: {e}", exc_info=True)
        return False, f"❌ Erro na sincronização: {e}"

def verificar_status_sheets():
    """Verifica se Google Sheets está configurado e acessível."""
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

def sincronizar_automaticamente(operacao="geral"):
    """Sincroniza automaticamente com Google Sheets após operações CRUD."""
    st.session_state['sync_stats']['total_tentativas'] += 1

    if not st.session_state.get('sync_automatico_habilitado', False):
        st.session_state['sync_stats']['ultimo_status'] = '⚪ DESABILITADO'
        st.session_state['sync_stats']['ultimo_erro'] = 'Sincronização automática desabilitada pelo usuário'
        logger.info("🔴 Sync automático: DESABILITADO pelo usuário")
        return

    if not GSPREAD_AVAILABLE:
        st.session_state['sync_stats']['ultimo_status'] = '❌ GSPREAD NÃO DISPONÍVEL'
        st.session_state['sync_stats']['ultimo_erro'] = 'Biblioteca gspread não está instalada'
        st.session_state['sync_stats']['falhas'] += 1
        logger.error("🔴 Sync automático: gspread não disponível")
        return

    if "gcp_service_account" not in st.secrets:
        st.session_state['sync_stats']['ultimo_status'] = '❌ SEM CREDENCIAIS'
        st.session_state['sync_stats']['ultimo_erro'] = 'Credenciais do Google Sheets não configuradas'
        st.session_state['sync_stats']['falhas'] += 1
        logger.error("🔴 Sync automático: credenciais não configuradas")
        return

    try:
        client = conectar_google_sheets()
        if not client:
            st.session_state['sync_stats']['ultimo_status'] = '❌ FALHA CONEXÃO'
            st.session_state['sync_stats']['ultimo_erro'] = 'Não foi possível conectar ao Google Sheets'
            st.session_state['sync_stats']['falhas'] += 1
            logger.warning("🔴 Sync automático: não foi possível conectar ao Sheets")
            return

        df_pedidos = st.session_state.pedidos
        sucesso_pedidos, msg_pedidos = salvar_no_sheets(client, "Pedidos", df_pedidos)

        df_clientes = st.session_state.clientes
        sucesso_clientes, msg_clientes = salvar_no_sheets(client, "Clientes", df_clientes)

        agora = agora_brasil().strftime("%d/%m/%Y %H:%M:%S")
        st.session_state['sync_stats']['ultima_sync'] = agora

        if sucesso_pedidos and sucesso_clientes:
            st.session_state['sync_stats']['sucessos'] += 1
            st.session_state['sync_stats']['ultimo_status'] = '✅ SUCESSO'
            st.session_state['sync_stats']['ultimo_erro'] = None
            logger.info(f"🟢 Sync automático ({operacao}): Pedidos e Clientes sincronizados ✅")
            # ✅ NOTIFICAÇÃO: Backup bem-sucedido
            st.toast("☁️ Backup automático realizado", icon="✅")
        elif sucesso_pedidos:
            st.session_state['sync_stats']['falhas'] += 1
            st.session_state['sync_stats']['ultimo_status'] = '⚠️ PARCIAL (só Pedidos)'
            st.session_state['sync_stats']['ultimo_erro'] = f'Clientes falhou: {msg_clientes}'
            logger.warning(f"🟡 Sync automático ({operacao}): Pedidos OK, Clientes falhou - {msg_clientes}")
            # ⚠️ NOTIFICAÇÃO: Backup parcial
            st.toast("⚠️ Backup parcial (só Pedidos)", icon="⚠️")
        elif sucesso_clientes:
            st.session_state['sync_stats']['falhas'] += 1
            st.session_state['sync_stats']['ultimo_status'] = '⚠️ PARCIAL (só Clientes)'
            st.session_state['sync_stats']['ultimo_erro'] = f'Pedidos falhou: {msg_pedidos}'
            logger.warning(f"🟡 Sync automático ({operacao}): Clientes OK, Pedidos falhou - {msg_pedidos}")
            # ⚠️ NOTIFICAÇÃO: Backup parcial
            st.toast("⚠️ Backup parcial (só Clientes)", icon="⚠️")
        else:
            st.session_state['sync_stats']['falhas'] += 1
            st.session_state['sync_stats']['ultimo_status'] = '❌ AMBOS FALHARAM'
            st.session_state['sync_stats']['ultimo_erro'] = f'Pedidos: {msg_pedidos} | Clientes: {msg_clientes}'
            logger.warning(f"🔴 Sync automático ({operacao}): Ambos falharam")
            # ❌ NOTIFICAÇÃO: Backup falhou
            st.toast("❌ Backup falhou - Dados não salvos!", icon="🚨")

    except Exception as e:
        st.session_state['sync_stats']['falhas'] += 1
        st.session_state['sync_stats']['ultimo_status'] = '❌ EXCEÇÃO'
        st.session_state['sync_stats']['ultimo_erro'] = str(e)
        logger.warning(f"🔴 Sync automático ({operacao}) com erro: {e}")
