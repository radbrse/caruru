"""Regras financeiras compartilhadas por tela e documentos."""
import math
from telegram_format import calcular_falta


def resumo_pagamento(pedido):
    total = max(0.0, float(pedido.get('Valor', 0) or 0))
    saldo = max(0.0, calcular_falta(pedido.get('Pagamento'), total, pedido.get('Entrada', 0)))
    return round(total, 2), round(max(0, total - saldo), 2), round(saldo, 2)


def preco_contratado(pedido):
    """Reconstrói unitário histórico quando determinável, sem usar preço atual."""
    quantidade = float(pedido.get('Caruru', 0)) + float(pedido.get('Bobo', 0))
    fator = 1 - float(pedido.get('Desconto', 0)) / 100
    if quantidade <= 0 or fator <= 0:
        return None
    preco = float(pedido['Valor']) / (quantidade * fator)
    return preco if math.isfinite(preco) and preco >= 0 else None


def totais_financeiros(df):
    ativos = df[~df['Status'].str.contains('Cancelado', na=False)]
    valores = [resumo_pagamento(p) for p in ativos.to_dict('records')]
    return round(sum(v[0] for v in valores), 2), round(sum(v[2] for v in valores), 2)
