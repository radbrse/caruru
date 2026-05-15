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


def amanha_brasil() -> date:
    return (datetime.now(FUSO_BRASIL) + timedelta(days=1)).date()


def conectar_sheets() -> gspread.Client:
    raw = os.environ["GCP_SERVICE_ACCOUNT"]
    creds_dict = json.loads(raw)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def carregar_pedidos_amanha(client: gspread.Client, data_alvo: date) -> list[dict]:
    """Retorna pedidos cujo campo Data bate com data_alvo."""
    spreadsheet = client.open(NOME_PLANILHA)
    ws = spreadsheet.worksheet(ABA_PEDIDOS)
    rows = ws.get_all_records()

    alvo_iso = data_alvo.isoformat()          # "YYYY-MM-DD"
    alvo_br  = data_alvo.strftime("%d/%m/%Y") # "DD/MM/YYYY" (fallback)

    pedidos = []
    for row in rows:
        data_cell = str(row.get("Data", "")).strip()
        if data_cell in (alvo_iso, alvo_br):
            # Ignorar pedidos já entregues ou cancelados
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
            f"📭 Nenhum pedido cadastrado para amanhã\\."
        )

    total_caruru = sum(int(float(p.get("Caruru") or 0)) for p in pedidos)
    total_bobo   = sum(int(float(p.get("Bobo")   or 0)) for p in pedidos)
    total_valor  = sum(float(p.get("Valor") or 0)       for p in pedidos)
    valor_fmt = f"R$ {total_valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

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

        linhas.append(f"• {nome} — {' '.join(itens)}{hora_str}{flags_str}")

    pedidos_txt = "\n".join(linhas)

    return (
        f"🍛 *Cantinho do Caruru*\n\n"
        f"📅 Pedidos para amanhã: *{data_fmt}*\n\n"
        f"📦 *{len(pedidos)} pedido(s)*\n"
        f"🥘 Caruru: *{total_caruru}* un  |  🦐 Bobó: *{total_bobo}* un\n"
        f"💰 Total: *{valor_fmt}*\n\n"
        f"👥 *Clientes:*\n{pedidos_txt}"
    )


def enviar_telegram(token: str, chat_id: str, mensagem: str) -> dict:
    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={
        "chat_id":    chat_id,
        "text":       mensagem,
        "parse_mode": "Markdown",
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()


def main():
    token   = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

    print("🔗 Conectando ao Google Sheets...")
    client = conectar_sheets()

    amanha = amanha_brasil()
    print(f"📅 Buscando pedidos para: {amanha.isoformat()}")

    pedidos = carregar_pedidos_amanha(client, amanha)
    print(f"📦 {len(pedidos)} pedido(s) encontrado(s)")

    mensagem = formatar_mensagem(pedidos, amanha)
    print("\n--- Mensagem a enviar ---")
    print(mensagem)
    print("-------------------------\n")

    resultado = enviar_telegram(token, chat_id, mensagem)
    msg_id = resultado.get("result", {}).get("message_id", "?")
    print(f"✅ Mensagem enviada! Message ID: {msg_id}")


if __name__ == "__main__":
    try:
        main()
    except KeyError as e:
        print(f"❌ Variável de ambiente ausente: {e}")
        print("   Verifique os secrets: GCP_SERVICE_ACCOUNT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Erro inesperado: {e}")
        sys.exit(1)
