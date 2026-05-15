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

FUSO_BRASIL = ZoneInfo("America/Sao_Paulo")
NOME_PLANILHA = "Cantinho do Caruru - Dados"
ABA_PEDIDOS   = "Pedidos"


def gh_error(msg: str):
    """Emite mensagem como GitHub Actions annotation (aparece no painel de anotações)."""
    print(f"::error::{msg}")


def gh_notice(msg: str):
    print(f"::notice::{msg}")


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
        gh_error(f"TELEGRAM_BOT_TOKEN parece inválido (deve ter formato '123456789:ABCxyz...'). Recebido: '{tok[:10]}...' ({len(tok)} chars)")
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
    print(f"   ✅ TELEGRAM_CHAT_ID — {cid}")
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


def _bool_campo(row: dict, campo: str) -> bool:
    return str(row.get(campo, "")).strip().lower() in ("true", "1", "sim")


def formatar_mensagem(pedidos: list[dict], data_alvo: date) -> str:
    dias_pt = {
        "Monday": "segunda-feira", "Tuesday": "terça-feira",
        "Wednesday": "quarta-feira", "Thursday": "quinta-feira",
        "Friday": "sexta-feira", "Saturday": "sábado", "Sunday": "domingo",
    }
    dia_semana = dias_pt.get(data_alvo.strftime("%A"), data_alvo.strftime("%A"))
    data_fmt = f"{data_alvo.strftime('%d/%m/%Y')} ({dia_semana})"

    if not pedidos:
        return (
            f"🍛 *Cantinho do Caruru*\n\n"
            f"📅 Amanhã: {data_fmt}\n\n"
            f"📭 Nenhum pedido cadastrado para amanhã."
        )

    total_caruru = sum(int(float(p.get("Caruru") or 0)) for p in pedidos)
    total_bobo   = sum(int(float(p.get("Bobo")   or 0)) for p in pedidos)
    total_valor  = sum(float(p.get("Valor") or 0)       for p in pedidos)

    def _falta(p) -> float:
        pag = str(p.get("Pagamento", "")).strip().upper()
        v = float(p.get("Valor") or 0)
        if pag == "NÃO PAGO": return v
        if pag == "METADE":   return v / 2
        return 0.0

    def _brl(v: float) -> str:
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    total_pendente = sum(_falta(p) for p in pedidos)
    valor_fmt    = _brl(total_valor)
    pendente_fmt = _brl(total_pendente)

    linhas = []
    for p in pedidos:
        nome = str(p.get("Cliente", "?")).strip()
        qc   = int(float(p.get("Caruru") or 0))
        qb   = int(float(p.get("Bobo")   or 0))

        itens = []
        if qc: itens.append(f"{qc}x 🥘")
        if qb: itens.append(f"{qb}x 🦐")

        hora = str(p.get("Hora", "")).strip()
        hora_str = f" ⏰ {hora}" if hora and hora != "nan" else ""

        flags = []
        if _bool_campo(p, "Extra"):    flags.append("⚡ Extra")
        if _bool_campo(p, "Vegano"):   flags.append("🌿 Vegano")
        if _bool_campo(p, "Delivery"): flags.append("🛵 Delivery")
        flags_str = f"  {' '.join(flags)}" if flags else ""

        falta = _falta(p)
        if falta > 0:
            pagamento = str(p.get("Pagamento", "")).strip().upper()
            icone = "💸" if pagamento == "NÃO PAGO" else "🔸"
            pag_str = f"  {icone} {_brl(falta)}"
        else:
            pag_str = ""

        linhas.append(f"• {nome} — {' '.join(itens)}{hora_str}{flags_str}{pag_str}")

    pedidos_txt = "\n".join(linhas)

    return (
        f"🍛 *Cantinho do Caruru*\n\n"
        f"📅 Pedidos para amanhã: *{data_fmt}*\n\n"
        f"📦 *{len(pedidos)} pedido(s)*\n"
        f"🥘 Caruru: *{total_caruru}* un  |  🦐 Bobó: *{total_bobo}* un\n"
        f"💰 Total: *{valor_fmt}*\n"
        + (f"💸 A receber: *{pendente_fmt}*\n" if total_pendente > 0 else "")
        + f"\n👥 *Clientes:*\n{pedidos_txt}"
    )


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
            gh_error(f"TELEGRAM_CHAT_ID '{chat_id}' não encontrado. Você enviou alguma mensagem ao bot primeiro? Detalhe: {desc}")
        elif resp.status_code == 403:
            gh_error(f"Bot bloqueado ou sem permissão no chat {chat_id}. Detalhe: {desc}")
        else:
            gh_error(f"Telegram retornou HTTP {resp.status_code}: {desc}")

        resp.raise_for_status()

    return resp.json()


def main():
    gcp_json, token, chat_id = validar_secrets()

    print("\n🔗 Conectando ao Google Sheets...")
    client = conectar_sheets(gcp_json)

    # Verifica horário configurado — disparos manuais (workflow_dispatch) sempre enviam
    trigger = os.environ.get("GITHUB_EVENT_NAME", "schedule")
    if trigger != "workflow_dispatch":
        hora_config = obter_hora_notificacao(client)
        hora_atual = datetime.now(FUSO_BRASIL).hour
        print(f"⏰ Horário atual: {hora_atual:02d}h Brasília | Configurado: {hora_config:02d}h")
        if hora_atual != hora_config:
            msg = f"⏭️ Horário atual {hora_atual:02d}h ≠ configurado {hora_config:02d}h (Brasília). Sem envio hoje neste ciclo."
            gh_notice(msg)
            print(msg)
            sys.exit(0)
    else:
        print("📤 Disparado manualmente — verificação de horário ignorada")

    amanha = amanha_brasil()
    print(f"📅 Buscando pedidos para: {amanha.isoformat()}")

    pedidos = carregar_pedidos_amanha(client, amanha)
    print(f"📦 {len(pedidos)} pedido(s) encontrado(s)")

    mensagem = formatar_mensagem(pedidos, amanha)
    print("\n--- Mensagem a enviar ---")
    print(mensagem)
    print("-------------------------\n")

    print("📤 Enviando para Telegram...")
    resultado = enviar_telegram(token, chat_id, mensagem)
    msg_id = resultado.get("result", {}).get("message_id", "?")
    gh_notice(f"Mensagem enviada com sucesso! Message ID: {msg_id}")
    print(f"✅ Sucesso!")


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

