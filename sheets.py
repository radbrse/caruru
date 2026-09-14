"""
Integração com Google Sheets: conexão, sincronização, backup na nuvem.
"""

import streamlit as st
import pandas as pd

from config import logger, agora_brasil
from storage import transacional, registrar_resultado_backup

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

@st.cache_resource
def obter_ou_criar_planilha(_client, nome_planilha="Cantinho do Caruru - Dados"):
    """Obtém a planilha ou cria se não existir.
    O prefixo _ em _client evita que o Streamlit tente fazer hash do objeto gspread.
    """
    try:
        try:
            spreadsheet = _client.open(nome_planilha)
            logger.info(f"Planilha '{nome_planilha}' encontrada")
            return spreadsheet
        except gspread.exceptions.SpreadsheetNotFound:
            spreadsheet = _client.create(nome_planilha)
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

        # Serializa com tratamento explícito de nan/None/NaT
        # (astype(str) puro deixa float nan passar como float para o json.dumps do gspread)
        _NULOS = {"nan", "None", "NaT", "none", "NAN", "<NA>"}

        def _para_str(val):
            try:
                if pd.isna(val):
                    return ""
            except (TypeError, ValueError):
                pass
            if val is None:
                return ""
            s = str(val)
            return "" if s in _NULOS else s

        df_str = df.copy()
        for col in df_str.columns:
            df_str[col] = df_str[col].apply(_para_str)

        if 'Contato' in df_str.columns:
            df_str['Contato'] = df_str['Contato'].str.replace(".0", "", regex=False)

        dados_completos = [df_str.columns.values.tolist()] + df_str.values.tolist()

        num_linhas = len(dados_completos)
        num_colunas = len(df_str.columns)

        from gspread.utils import rowcol_to_a1
        ultima_celula = rowcol_to_a1(num_linhas, num_colunas)
        range_atualizar = f'A1:{ultima_celula}'

        worksheet.update(range_name=range_atualizar, values=dados_completos)

        try:
            linhas_antigas = worksheet.row_count
            if linhas_antigas > num_linhas:
                inicio_limpar = rowcol_to_a1(num_linhas + 1, 1)
                fim_limpar = rowcol_to_a1(linhas_antigas, num_colunas)
                range_limpar = f'{inicio_limpar}:{fim_limpar}'
                worksheet.batch_clear([range_limpar])
                logger.info(f"🧹 Limpou {linhas_antigas - num_linhas} linhas antigas - Range: {range_limpar}")
        except Exception as e_limpar:
            return False, f"Dados enviados, mas a remoção de linhas antigas falhou: {e_limpar}"

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
            return None, f"Aba '{nome_aba}' não existe"

        dados = worksheet.get_all_values()

        if not dados:
            return None, f"Aba '{nome_aba}' sem cabeçalho"

        df = pd.DataFrame(dados[1:], columns=dados[0])

        if "Data" in df.columns:
            df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.date

        logger.info(f"Dados carregados do Sheets: {nome_aba} ({len(df)} linhas)")
        return df, f"✅ {len(df)} registros carregados"

    except Exception as e:
        logger.error(f"Erro ao carregar do Sheets: {e}", exc_info=True)
        return None, f"❌ Erro ao carregar: {e}"

# ==============================================================================
# SINCRONIZAÇÃO
# ==============================================================================
def ler_config_negocio(client):
    """None significa chave ainda não migrada; erro de rede nunca significa default."""
    planilha = obter_ou_criar_planilha(client)
    if planilha is None:
        raise RuntimeError('Planilha indisponível')
    try:
        ws = planilha.worksheet('Config')
    except gspread.exceptions.WorksheetNotFound:
        return None
    for row in ws.get_all_records():
        if str(row.get('Chave', '')).strip() == 'preco_base':
            from config import validar_config
            return validar_config({'preco_base': row.get('Valor')})
    return None


def salvar_config_negocio(client, config):
    from config import validar_config
    dados = validar_config(config)
    planilha = obter_ou_criar_planilha(client)
    if planilha is None:
        raise RuntimeError('Planilha indisponível')
    try:
        ws = planilha.worksheet('Config')
    except gspread.exceptions.WorksheetNotFound:
        ws = planilha.add_worksheet(title='Config', rows=20, cols=2)
        ws.append_row(['Chave', 'Valor'])
    for i, row in enumerate(ws.get_all_records(), start=2):
        if str(row.get('Chave', '')).strip() == 'preco_base':
            ws.update_cell(i, 2, str(dados['preco_base']))
            break
    else:
        ws.append_row(['preco_base', str(dados['preco_base'])])
    if ler_config_negocio(client) != dados:
        raise RuntimeError('Preço não confirmado após gravação no Sheets')


@transacional
def sincronizar_com_sheets(modo='enviar'):
    from database import carregar_pedidos, carregar_clientes, restaurar_conjunto
    from config import carregar_config
    try:
        client = conectar_google_sheets()
        if not client:
            raise RuntimeError('Não foi possível conectar ao Google Sheets')
        if modo == 'enviar':
            # Snapshot do disco, nunca da sessão. A trava também serializa uploads.
            config = carregar_config()
            df_pedidos, df_clientes = carregar_pedidos(), carregar_clientes()
            resultados = []
            for aba, df in [('Pedidos', df_pedidos), ('Clientes', df_clientes)]:
                ok, msg = salvar_no_sheets(client, aba, df)
                resultados.append(f'{aba}: {msg}')
                if not ok:
                    raise RuntimeError('Backup parcial: ' + '; '.join(resultados))
            salvar_config_negocio(client, config)
            registrar_resultado_backup(True)
            try:
                ws = obter_ou_criar_planilha(client).worksheet('Backups_Log')
                ws.append_row([agora_brasil().strftime('%Y-%m-%d %H:%M:%S'),
                               'Backup confirmado', len(df_pedidos), len(df_clientes)])
            except Exception as e:
                logger.warning(f'Backup confirmado, mas log auxiliar indisponível: {e}')
            return True, 'Pedidos, clientes e preço base confirmados no Sheets.'
        if modo == 'receber':
            df_pedidos, msg_p = carregar_do_sheets(client, 'Pedidos')
            df_clientes, msg_c = carregar_do_sheets(client, 'Clientes')
            if df_pedidos is None or df_clientes is None:
                raise RuntimeError(f'Restauração cancelada antes de salvar: {msg_p}; {msg_c}')
            config = ler_config_negocio(client)
            if config is None:
                raise RuntimeError('Preço base ausente no Sheets. Faça a migração pela configuração antes de restaurar.')
            ok, msg = restaurar_conjunto(df_pedidos, df_clientes, config)
            if not ok:
                return False, msg
            st.session_state.pedidos = carregar_pedidos()
            st.session_state.clientes = carregar_clientes()
            st.session_state.config = config
            # A restauração foi normalizada localmente; um novo envio confirmará a assinatura.
            return True, msg
        return False, 'Modo inválido. Use enviar ou receber.'
    except Exception as e:
        if modo == 'enviar':
            registrar_resultado_backup(False, str(e))
        logger.error(f'Erro na sincronização: {e}', exc_info=True)
        return False, str(e)


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
        # Limpa cache para forçar reconexão na próxima tentativa
        # (evita UI mostrar "Conectado" com credenciais expiradas/inválidas)
        try:
            conectar_google_sheets.clear()
            obter_ou_criar_planilha.clear()
            logger.warning(f"Cache do Sheets limpo após falha de conexão: {e}")
        except Exception:
            pass
        return False, f"❌ Erro: {str(e)[:100]}"

# ==============================================================================
# CONFIG (horário de notificação)
# ==============================================================================
_ABA_CONFIG = "Config"


def ler_hora_notificacao(client) -> int:
    """Lê a hora de notificação configurada no Google Sheets. Default: 7."""
    try:
        spreadsheet = obter_ou_criar_planilha(client)
        if not spreadsheet:
            return 7
        try:
            ws = spreadsheet.worksheet(_ABA_CONFIG)
        except gspread.exceptions.WorksheetNotFound:
            return 7
        for row in ws.get_all_records():
            if str(row.get("Chave", "")).strip() == "notification_hour":
                return int(row.get("Valor", 7))
        return 7
    except Exception as e:
        logger.warning(f"Erro ao ler hora de notificação: {e}")
        return 7


def ler_ultima_data_envio(client) -> str:
    """Lê last_notification_date (ISO) da aba Config. Retorna '' se nunca enviou."""
    try:
        spreadsheet = obter_ou_criar_planilha(client)
        if not spreadsheet:
            return ""
        try:
            ws = spreadsheet.worksheet(_ABA_CONFIG)
        except gspread.exceptions.WorksheetNotFound:
            return ""
        for row in ws.get_all_records():
            if str(row.get("Chave", "")).strip() == "last_notification_date":
                return str(row.get("Valor", "")).strip()
        return ""
    except Exception as e:
        logger.warning(f"Erro ao ler última data de envio: {e}")
        return ""


def resetar_ultima_data_envio(client) -> tuple[bool, str]:
    """Limpa last_notification_date — útil para forçar reenvio no mesmo dia."""
    try:
        spreadsheet = obter_ou_criar_planilha(client)
        if not spreadsheet:
            return False, "❌ Erro ao acessar planilha"
        try:
            ws = spreadsheet.worksheet(_ABA_CONFIG)
        except gspread.exceptions.WorksheetNotFound:
            return True, "✅ Nenhum registro de envio para limpar"
        rows = ws.get_all_records()
        for i, row in enumerate(rows, start=2):
            if str(row.get("Chave", "")).strip() == "last_notification_date":
                ws.update_cell(i, 2, "")
                logger.info("last_notification_date limpa")
                return True, "✅ Registro de envio limpo — próximo cron tentará enviar"
        return True, "✅ Nenhum registro de envio para limpar"
    except Exception as e:
        logger.error(f"Erro ao limpar última data de envio: {e}")
        return False, f"❌ Erro: {e}"


def salvar_hora_notificacao(client, hora: int) -> tuple[bool, str]:
    """Salva a hora de notificação no Google Sheets (cria aba Config se não existir)."""
    try:
        spreadsheet = obter_ou_criar_planilha(client)
        if not spreadsheet:
            return False, "❌ Erro ao acessar planilha"
        try:
            ws = spreadsheet.worksheet(_ABA_CONFIG)
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=_ABA_CONFIG, rows=20, cols=2)
            ws.append_row(["Chave", "Valor"])
        rows = ws.get_all_records()
        for i, row in enumerate(rows, start=2):
            if str(row.get("Chave", "")).strip() == "notification_hour":
                ws.update_cell(i, 2, str(hora))
                logger.info(f"Hora de notificação atualizada: {hora:02d}h")
                return True, f"✅ Horário atualizado para {hora:02d}:00 (Brasília)"
        ws.append_row(["notification_hour", str(hora)])
        logger.info(f"Hora de notificação criada: {hora:02d}h")
        return True, f"✅ Horário configurado para {hora:02d}:00 (Brasília)"
    except Exception as e:
        logger.error(f"Erro ao salvar hora de notificação: {e}")
        return False, f"❌ Erro ao salvar: {e}"


def sincronizar_automaticamente(operacao='geral'):
    stats = st.session_state.setdefault('sync_stats', {
        'total_tentativas': 0, 'sucessos': 0, 'falhas': 0,
        'ultima_sync': None, 'ultimo_status': None, 'ultimo_erro': None,
    })
    if not st.session_state.get('sync_automatico_habilitado', False):
        stats['ultimo_status'] = '⚪ DESABILITADO'
        return
    stats['total_tentativas'] += 1
    ok, msg = sincronizar_com_sheets('enviar')
    stats['ultima_sync'] = agora_brasil().strftime('%d/%m/%Y %H:%M:%S')
    stats['sucessos' if ok else 'falhas'] += 1
    stats['ultimo_status'] = '✅ SUCESSO' if ok else '❌ FALHA'
    stats['ultimo_erro'] = None if ok else msg
    st.toast('Backup confirmado' if ok else 'Alteração local salva; backup não confirmado. Consulte Manutenção.',
             icon='✅' if ok else '⚠️')
