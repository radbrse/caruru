"""
Formatação compartilhada das mensagens de Telegram.

Módulo SEM dependências pesadas (apenas stdlib) — usado tanto pelo app
Streamlit (views/manutencao.py) quanto pelo notificador.py standalone
executado no GitHub Actions, onde streamlit/pandas não estão instalados.

`pedidos` aceita lista de objetos dict-like: tanto `dict` (vindo do
gspread `get_all_records()`) quanto `pandas.Series` (via `df.to_dict('records')`),
pois ambos expõem `.get()`.
"""

from datetime import date

_DIAS_PT = {
    "Monday": "segunda-feira", "Tuesday": "terça-feira",
    "Wednesday": "quarta-feira", "Thursday": "quinta-feira",
    "Friday": "sexta-feira", "Saturday": "sábado", "Sunday": "domingo",
}


def _num(valor) -> float:
    """Converte para float de forma resiliente: '', None, 'nan' e NaN → 0.0."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if v != v else v  # v != v é True apenas para NaN


def brl(valor) -> str:
    """Formata valor em reais no padrão brasileiro (R$ 1.234,56)."""
    v = _num(valor)
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def calcular_falta(pagamento, valor) -> float:
    """Quanto ainda falta pagar conforme o status de pagamento."""
    pag = str(pagamento or "").strip().upper()
    v = _num(valor)
    if pag == "NÃO PAGO":
        return v
    if pag == "METADE":
        return v / 2
    return 0.0


def campo_verdadeiro(valor) -> bool:
    """Interpreta campo booleano vindo de CSV/Sheets (string) ou bool real."""
    return str(valor).strip().lower() in ("true", "1", "sim")


def formatar_data_extenso(data_alvo: date) -> str:
    """'17/05/2026 (domingo)'."""
    dia = _DIAS_PT.get(data_alvo.strftime("%A"), data_alvo.strftime("%A"))
    return f"{data_alvo.strftime('%d/%m/%Y')} ({dia})"


def formatar_mensagem(pedidos, data_alvo: date, rotulo_data: str = "Pedidos") -> str:
    """Monta a mensagem de Telegram (Markdown v1) a partir dos pedidos.

    Args:
        pedidos: lista de dict-like (dict ou pandas Series).
        data_alvo: data dos pedidos.
        rotulo_data: prefixo do cabeçalho de data (ex.: 'Pedidos para amanhã').
    """
    data_fmt = formatar_data_extenso(data_alvo)

    if not pedidos:
        return (
            f"🍛 *Cantinho do Caruru*\n\n"
            f"📅 {rotulo_data}: {data_fmt}\n\n"
            f"📭 Nenhum pedido cadastrado para esta data."
        )

    total_caruru = sum(int(_num(p.get("Caruru"))) for p in pedidos)
    total_bobo   = sum(int(_num(p.get("Bobo"))) for p in pedidos)
    total_valor  = sum(_num(p.get("Valor")) for p in pedidos)
    total_pendente = sum(calcular_falta(p.get("Pagamento"), p.get("Valor")) for p in pedidos)

    linhas = []
    for p in pedidos:
        nome = str(p.get("Cliente", "?")).strip().title()
        qc = int(_num(p.get("Caruru")))
        qb = int(_num(p.get("Bobo")))

        itens = []
        if qc:
            itens.append(f"{qc} kg de Caruru")
        if qb:
            itens.append(f"{qb} kg de Bobó")

        hora = str(p.get("Hora", "")).strip()
        hora_fmt = hora[:5] if hora and hora != "nan" and len(hora) >= 5 else hora
        hora_str = f"  ⏰ {hora_fmt}" if hora_fmt and hora_fmt != "nan" else ""

        flags = []
        if campo_verdadeiro(p.get("Extra", "")):
            flags.append("⚡ Extra")
        if campo_verdadeiro(p.get("Vegano", "")):
            flags.append("🌿 Vegano")
        if campo_verdadeiro(p.get("Delivery", "")):
            flags.append("🛵 Delivery")

        falta = calcular_falta(p.get("Pagamento"), p.get("Valor"))
        if falta > 0:
            pag = str(p.get("Pagamento", "")).strip().upper()
            icone = "💸" if pag == "NÃO PAGO" else "🔸"
            pag_label = f"{icone} Falta {brl(falta)}"
        else:
            pag_label = "✅ Pedido pago"

        linha1 = f"• *{nome}*{hora_str}"
        linha2 = "  " + "  ".join(itens + flags + [pag_label])
        linhas.append(f"{linha1}\n{linha2}")

    return (
        f"🍛 *Cantinho do Caruru*\n\n"
        f"📅 {rotulo_data}: *{data_fmt}*\n\n"
        f"📦 *{len(pedidos)} pedido(s)*\n"
        f"🥘 Caruru: *{total_caruru} kg*  |  🦐 Bobó: *{total_bobo} kg*\n"
        f"💰 Total: *{brl(total_valor)}*\n"
        + (f"💸 A receber: *{brl(total_pendente)}*\n" if total_pendente > 0 else "")
        + f"\n👥 *Clientes:*\n" + "\n\n".join(linhas)
    )
