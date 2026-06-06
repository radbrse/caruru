#!/usr/bin/env python3
"""
Notificador de pedidos — Cantinho do Caruru
Executado pelo GitHub Actions diariamente às 07h (horário de Brasília).
Lê os pedidos do dia seguinte no Google Sheets e envia resumo via Telegram.
"""

import os
import json
import sys
import requests
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from telegram_format import formatar_mensagem

FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")
NOME_PLANILHA = "Cantinho do Caruru - Dados"
ABA_PEDIDOS   = "Pedidos"


def gh_error(msg: str):
    """Emite mensagem como GitHub Actions annotation (aparece no painel de anotações)."""
    print(f"::error::{msg}")


def gh_notice(msg: str):
    print(f"::notice::{msg}")


def _mascarar(valor: str) -> str:
    """Mascara identificador sensível para logs (mantém só os 4 últimos dígitos)."""
    s = str(valor or "")
    return f"***{s[-4:]}" if len(s) > 4 else "***"


def validar_secrets() -> tuple[str, str, str]:
    """Valida e retorna os 3 secrets, com diagnóstico claro de qual está faltando."""
    print("🔐 Validando secrets...")

    gcp = os.environ.get("GCP_SERVICE_ACCOUNT", "").strip()
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    cid = os.environ.get("TELEGRAM_CHAT_ID", "").strip()

    if not gcp:
        gh_error("Secret GCP_SERVICE_ACCOUNT não foi configurado no repositório GitHub.")
        sys.exit(1)
    if not tok:
        gh_error("Secret TELEGRAM_BOT_TOKEN não foi configurado no repositório GitHub.")
        sys.exit(1)
    if not cid:
        gh_error("Secret TELEGRAM_CHAT_ID não foi configurado no repositório GitHub.")
        sys.exit(1)

    # Valida formato do token (deve ser tipo "123456789:ABCdef...")
    if ":" not in tok or len(tok) < 30:
        gh_error(f"TELEGRAM_BOT_TOKEN parece inválido (deve ter formato '123456789:ABCxyz...'). Recebido: {len(tok)} chars")
        sys.exit(1)

    # Valida formato do chat_id (deve ser número, opcionalmente negativo)
    try:
        int(cid)
    except ValueError:
        gh_error(f"TELEGRAM_CHAT_ID deve ser um número inteiro. Recebido: '{cid}'")
        sys.exit(1)

    # Valida JSON do GCP
    try:
        gcp_dict = json.loads(gcp)
    except json.JSONDecodeError as e:
        gh_error(f"GCP_SERVICE_ACCOUNT não é JSON válido: {e}. Cole o conteúdo do arquivo .json completo (começando com {{ e terminando com }}).")
        sys.exit(1)

    campos_obrigatorios = ["type", "project_id", "private_key", "client_email"]
    faltantes = [c for c in campos_obrigatorios if c not in gcp_dict]
    if faltantes:
        gh_error(f"GCP_SERVICE_ACCOUNT JSON está incompleto. Campos faltando: {', '.join(faltantes)}")
        sys.exit(1)

    print(f"   ✅ GCP_SERVICE_ACCOUNT — JSON válido (projeto: {gcp_dict.get('project_id')})")
    print(f"   ✅ TELEGRAM_BOT_TOKEN — formato OK")
    print(f"   ✅ TELEGRAM_CHAT_ID — {_mascarar(cid)}")
    return gcp, tok, cid


def amanha_brasil() -> date:
    return (datetime.now(FUSO_BRASIL) + timedelta(days=1)).date()


def conectar_sheets(gcp_json: str) -> gspread.Client:
    try:
        creds_dict = json.loads(gcp_json)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        gh_error(f"Falha ao autenticar no Google: {e}")
        raise


def obter_hora_notificacao(client: gspread.Client) -> int:
    """Lê a hora de notificação da aba Config do Sheets. Default: 7."""
    ABA_CONFIG = "Config"
    try:
        spreadsheet = client.open(NOME_PLANILHA)
        try:
            ws = spreadsheet.worksheet(ABA_CONFIG)
        except gspread.WorksheetNotFound:
            return 7
        for row in ws.get_all_records():
            if str(row.get("Chave", "")).strip() == "notification_hour":
                return int(row.get("Valor", 7))
        return 7
    except Exception:
        return 7


def obter_ultima_data_envio(client: gspread.Client) -> str:
    """Lê last_notification_date (ISO) da aba Config. Retorna '' se nunca enviou."""
    ABA_CONFIG = "Config"
    try:
        spreadsheet = client.open(NOME_PLANILHA)
        try:
            ws = spreadsheet.worksheet(ABA_CONFIG)
        except gspread.WorksheetNotFound:
            return ""
        for row in ws.get_all_records():
            if str(row.get("Chave", "")).strip() == "last_notification_date":
                return str(row.get("Valor", "")).strip()
        return ""
    except Exception as e:
        print(f"⚠️ Erro ao ler última data de envio: {e}")
        return ""


def salvar_ultima_data_envio(client: gspread.Client, data_iso: str) -> None:
    """Grava last_notification_date na aba Config (cria aba/linha se não existir)."""
    ABA_CONFIG = "Config"
    try:
        spreadsheet = client.open(NOME_PLANILHA)
        try:
            ws = spreadsheet.worksheet(ABA_CONFIG)
        except gspread.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=ABA_CONFIG, rows=20, cols=2)
            ws.append_row(["Chave", "Valor"])
        rows = ws.get_all_records()
        for i, row in enumerate(rows, start=2):
            if str(row.get("Chave", "")).strip() == "last_notification_date":
                ws.update_cell(i, 2, data_iso)
                return
        ws.append_row(["last_notification_date", data_iso])
    except Exception as e:
        print(f"⚠️ Erro ao salvar última data de envio: {e}")


def carregar_pedidos_amanha(client: gspread.Client, data_alvo: date) -> list[dict]:
    """Retorna pedidos cujo campo Data bate com data_alvo."""
    try:
        spreadsheet = client.open(NOME_PLANILHA)
    except gspread.SpreadsheetNotFound:
        gh_error(f"Planilha '{NOME_PLANILHA}' não encontrada. Verifique se o e-mail da service account tem acesso.")
        raise

    try:
        ws = spreadsheet.worksheet(ABA_PEDIDOS)
    except gspread.WorksheetNotFound:
        gh_error(f"Aba '{ABA_PEDIDOS}' não existe na planilha.")
        raise

    rows = ws.get_all_records()

    alvo_iso = data_alvo.isoformat()
    alvo_br  = data_alvo.strftime("%d/%m/%Y")

    pedidos = []
    for row in rows:
        data_cell = str(row.get("Data", "")).strip()
        if data_cell in (alvo_iso, alvo_br):
            status = str(row.get("Status", "")).strip()
            if "Entregue" not in status and "Cancelado" not in status:
                pedidos.append(row)

    return pedidos


def enviar_telegram(token: str, chat_id: str, mensagem: str) -> dict:
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={
        "chat_id":    chat_id,
        "text":       mensagem,
        "parse_mode": "Markdown",
    }, timeout=15)

    if resp.status_code != 200:
        try:
            erro = resp.json()
            desc = erro.get("description", resp.text)
        except Exception:
            desc = resp.text

        if resp.status_code == 401:
            gh_error(f"TELEGRAM_BOT_TOKEN inválido — Telegram rejeitou: {desc}")
        elif resp.status_code == 400 and "chat not found" in desc.lower():
            gh_error(f"TELEGRAM_CHAT_ID '{_mascarar(chat_id)}' não encontrado. Você enviou alguma mensagem ao bot primeiro? Detalhe: {desc}")
        elif resp.status_code == 403:
            gh_error(f"Bot bloqueado ou sem permissão no chat {_mascarar(chat_id)}. Detalhe: {desc}")
        else:
            gh_error(f"Telegram retornou HTTP {resp.status_code}: {desc}")

        resp.raise_for_status()

    return resp.json()


def main():
    gcp_json, token, chat_id = validar_secrets()

    print("\n🔗 Conectando ao Google Sheets...")
    client = conectar_sheets(gcp_json)

    # Janela de envio com idempotência — disparos manuais (workflow_dispatch) sempre enviam.
    # O cron do GitHub Actions é "best-effort" e frequentemente pula horários específicos.
    # Por isso usamos hora_atual >= hora_config + flag de "já enviei hoje" no Sheets:
    # se o run das 11h for pulado, o das 12h pega; depois de enviar, os runs seguintes pulam.
    trigger = os.environ.get("GITHUB_EVENT_NAME", "schedule")
    hoje_iso = datetime.now(FUSO_BRASIL).date().isoformat()

    if trigger != "workflow_dispatch":
        hora_config = obter_hora_notificacao(client)
        hora_atual = datetime.now(FUSO_BRASIL).hour
        ultima_data = obter_ultima_data_envio(client)
        print(f"⏰ Horário atual: {hora_atual:02d}h Brasília | Janela: a partir das {hora_config:02d}h")
        print(f"📅 Hoje: {hoje_iso} | Última notificação enviada: {ultima_data or '(nunca)'}")

        if hora_atual < hora_config:
            msg = f"⏭️ Ainda não chegou a janela ({hora_atual:02d}h < {hora_config:02d}h Brasília)."
            gh_notice(msg)
            print(msg)
            sys.exit(0)

        if ultima_data == hoje_iso:
            msg = f"✅ Notificação de hoje ({hoje_iso}) já foi enviada — pulando."
            gh_notice(msg)
            print(msg)
            sys.exit(0)
    else:
        print("📤 Disparado manualmente — verificação de horário/idempotência ignorada")

    amanha = amanha_brasil()
    print(f"📅 Buscando pedidos para: {amanha.isoformat()}")

    pedidos = carregar_pedidos_amanha(client, amanha)
    print(f"📦 {len(pedidos)} pedido(s) encontrado(s)")

    # Em disparos automáticos (cron), só envia se houver pelo menos 1 pedido.
    # NÃO atualiza last_notification_date aqui — assim o próximo cron tenta de novo
    # caso o usuário cadastre um pedido depois (no mesmo dia, dentro da janela).
    if not pedidos and trigger != "workflow_dispatch":
        msg = f"📭 Nenhum pedido para {amanha.isoformat()} — sem envio (tentará novamente na próxima hora)."
        gh_notice(msg)
        print(msg)
        sys.exit(0)

    mensagem = formatar_mensagem(pedidos, amanha, rotulo_data="Pedidos para amanhã")
    print("\n--- Mensagem a enviar ---")
    print(mensagem)
    print("-------------------------\n")

    print("📤 Enviando para Telegram...")
    resultado = enviar_telegram(token, chat_id, mensagem)
    msg_id = resultado.get("result", {}).get("message_id", "?")
    gh_notice(f"Mensagem enviada com sucesso! Message ID: {msg_id}")
    print(f"✅ Sucesso!")

    # Marca como enviado hoje apenas em disparos automáticos
    # (manuais não devem bloquear o envio automático do mesmo dia)
    if trigger != "workflow_dispatch":
        salvar_ultima_data_envio(client, hoje_iso)
        print(f"📝 Registrado: notificação de {hoje_iso} enviada.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        gh_error(f"Erro inesperado: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

