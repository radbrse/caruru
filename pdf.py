"""
Geração de PDFs: recibos, relatórios, lista de clientes.
"""

import os
import io
from datetime import time
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors

from config import logger, agora_brasil, CHAVE_PIX, obter_preco_base
from utils import formatar_valor_br

# ==============================================================================
# PDF GENERATOR
# ==============================================================================
def desenhar_cabecalho(p, titulo):
    """Desenha cabeçalho padrão no PDF."""
    if os.path.exists("logo.png"):
        try:
            p.drawImage("logo.png", 20, 750, width=100, height=50, mask='auto', preserveAspectRatio=True)
        except Exception:
            pass
    p.setFont("Helvetica-Bold", 16)
    p.drawString(150, 775, "Cantinho do Caruru")
    p.setFont("Helvetica", 10)
    p.drawString(150, 760, "Comprovante / Relatório")
    p.setFont("Helvetica-Bold", 14)
    p.drawRightString(570, 765, titulo)
    p.setLineWidth(1)
    p.line(20, 740, 570, 740)

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

        preco_atual = obter_preco_base()
        preco_formatado = f"{preco_atual:.2f}".replace(".", ",")
        if float(dados.get('Caruru', 0)) > 0:
            p.drawString(40, y, "Caruru Tradicional")
            p.drawString(350, y, f"{int(float(dados.get('Caruru')))} kg")
            p.drawString(450, y, f"R$ {preco_formatado}")
            y -= 15
        if float(dados.get('Bobo', 0)) > 0:
            p.drawString(40, y, "Bobó de Camarão")
            p.drawString(350, y, f"{int(float(dados.get('Bobo')))} kg")
            p.drawString(450, y, f"R$ {preco_formatado}")
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
        valor_total_formatado = f"{float(dados.get('Valor', 0)):.2f}".replace(".", ",")
        p.drawString(350, y, f"{lbl}: R$ {valor_total_formatado}")

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

        # Declaração de recebimento
        y -= 50
        p.setFont("Helvetica-Bold", 11)
        p.drawString(30, y, "DECLARAÇÃO DE RECEBIMENTO")
        y -= 20

        p.setFont("Helvetica", 9)
        produtos = []
        caruru_qtd = 0
        bobo_qtd = 0

        try:
            caruru_qtd = int(float(dados.get('Caruru', 0)))
            if caruru_qtd > 0:
                produtos.append(f"{caruru_qtd} kg de Caruru Tradicional")
        except (ValueError, TypeError):
            pass

        try:
            bobo_qtd = int(float(dados.get('Bobo', 0)))
            if bobo_qtd > 0:
                produtos.append(f"{bobo_qtd} kg de Bobó de Camarão")
        except (ValueError, TypeError):
            pass

        produtos_texto = " e ".join(produtos) if len(produtos) == 2 else produtos[0] if produtos else "produtos"
        total_unidades = caruru_qtd + bobo_qtd

        try:
            valor_num = float(dados.get('Valor', 0))
        except (ValueError, TypeError):
            valor_num = 0.0

        valor_br = f"{valor_num:.2f}".replace(".", ",")
        cliente_nome = str(dados.get('Cliente', '')).strip() or "o cliente"

        texto = f"Declaramos que recebemos de {cliente_nome} o valor total de R$ {valor_br}, "
        texto += f"referente à compra de {produtos_texto}, "
        texto += "conforme discriminado neste comprovante."

        width = 535
        lines = []
        words = texto.split()
        line = ""

        for word in words:
            test_line = f"{line} {word}".strip()
            if p.stringWidth(test_line, "Helvetica", 9) < width:
                line = test_line
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)

        for line in lines:
            p.drawString(30, y, line)
            y -= 12

        y -= 8
        texto2 = "O pagamento foi realizado e devidamente confirmado na data informada, "
        texto2 += "dando plena quitação do valor acima."

        lines2 = []
        words2 = texto2.split()
        line2 = ""

        for word in words2:
            test_line2 = f"{line2} {word}".strip()
            if p.stringWidth(test_line2, "Helvetica", 9) < width:
                line2 = test_line2
            else:
                lines2.append(line2)
                line2 = word
        if line2:
            lines2.append(line2)

        for line in lines2:
            p.drawString(30, y, line)
            y -= 12

        if dados.get('Observacoes'):
            y -= 15
            p.setFont("Helvetica-Oblique", 9)

            obs_texto = f"Obs: {dados.get('Observacoes')}"
            obs_lines = []
            obs_words = obs_texto.split()
            obs_line = ""

            for word in obs_words:
                test_line = f"{obs_line} {word}".strip()
                if p.stringWidth(test_line, "Helvetica-Oblique", 9) < width:
                    obs_line = test_line
                else:
                    obs_lines.append(obs_line)
                    obs_line = word
            if obs_line:
                obs_lines.append(obs_line)

            for obs_l in obs_lines:
                p.drawString(30, y, obs_l)
                y -= 12

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
        cols = [20, 45, 85, 235, 270, 310, 370, 440, 515]
        hdrs = ["ID", "Data", "Cliente", "Car", "Bob", "Valor", "Status", "Pagto", "Hora"]
        for x, h in zip(cols, hdrs):
            p.drawString(x, y, h)
        y -= 20
        p.setFont("Helvetica", 8)
        total = 0
        total_caruru = 0
        total_bobo = 0

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

            p.drawString(20, y, str(row.get('ID_Pedido', '')))
            p.drawString(45, y, d_s)
            p.drawString(85, y, str(row.get('Cliente', ''))[:24])
            p.drawString(235, y, f"{int(row.get('Caruru', 0))}kg")
            p.drawString(270, y, f"{int(row.get('Bobo', 0))}kg")
            valor_formatado = f"{row.get('Valor', 0):.2f}".replace(".", ",")
            p.drawString(310, y, valor_formatado)
            p.drawString(370, y, st_cl)
            p.drawString(440, y, str(row.get('Pagamento', ''))[:10])
            p.drawString(515, y, h_s)

            total += row.get('Valor', 0)
            total_caruru += row.get('Caruru', 0)
            total_bobo += row.get('Bobo', 0)
            y -= 12

        p.line(20, y, 570, y)
        p.setFont("Helvetica-Bold", 11)
        total_formatado = f"{total:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        p.drawString(310, y - 20, f"TOTAL GERAL: R$ {total_formatado}")
        p.setFont("Helvetica-Bold", 9)
        p.drawString(20, y - 20, f"Pedidos: {len(df_filtrado)}")
        p.drawString(20, y - 35, f"Caruru: {int(total_caruru)} kg")
        p.drawString(20, y - 50, f"Bobó: {int(total_bobo)} kg")

        p.setFont("Helvetica-Oblique", 8)
        p.drawString(20, 30, f"Gerado em: {agora_brasil().strftime('%d/%m/%Y %H:%M')}")

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
# ORÇAMENTO
# ==============================================================================
def _quebrar_texto(p, texto, fonte, tamanho, largura):
    """Quebra texto em linhas que caibam na largura dada."""
    lines = []
    words = texto.split()
    line = ""
    for word in words:
        test = f"{line} {word}".strip()
        if p.stringWidth(test, fonte, tamanho) < largura:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _valor_por_extenso(valor: float) -> str:
    """Converte valor em reais para texto por extenso (até R$ 999.999,99)."""
    _UNI = ["", "UM", "DOIS", "TRÊS", "QUATRO", "CINCO", "SEIS", "SETE", "OITO", "NOVE",
            "DEZ", "ONZE", "DOZE", "TREZE", "QUATORZE", "QUINZE", "DEZESSEIS",
            "DEZESSETE", "DEZOITO", "DEZENOVE"]
    _DEZ = ["", "", "VINTE", "TRINTA", "QUARENTA", "CINQUENTA", "SESSENTA", "SETENTA", "OITENTA", "NOVENTA"]
    _CEN = ["", "CENTO", "DUZENTOS", "TREZENTOS", "QUATROCENTOS", "QUINHENTOS",
            "SEISCENTOS", "SETECENTOS", "OITOCENTOS", "NOVECENTOS"]

    def _grupo(n):
        """Converte 0-999 em lista de palavras."""
        if n == 0:
            return []
        partes = []
        if n >= 100:
            c = n // 100
            partes.append("CEM" if n == 100 else _CEN[c])
            n %= 100
        if n >= 20:
            partes.append(_DEZ[n // 10])
            n %= 10
        if n > 0:
            partes.append(_UNI[n])
        return partes

    try:
        reais = int(round(valor))
        centavos = round((valor - int(valor)) * 100)
    except Exception:
        return ""

    if reais == 0 and centavos == 0:
        return "ZERO REAIS"

    partes = []
    if reais >= 1000:
        m = reais // 1000
        g = _grupo(m)
        partes.append("MIL" if m == 1 else f"{' E '.join(g)} MIL")
        reais %= 1000
    if reais > 0:
        partes.extend(_grupo(reais))

    total_int = int(round(valor))
    result = f"{' E '.join(partes)} {'REAL' if total_int == 1 else 'REAIS'}"

    if centavos > 0:
        g_c = _grupo(centavos)
        result += f" E {' E '.join(g_c)} {'CENTAVO' if centavos == 1 else 'CENTAVOS'}"

    return result


def _brl(v: float) -> str:
    """Formata float em padrão brasileiro sem símbolo (ex.: 1.050,00)."""
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def gerar_orcamento_pdf(dados):
    """Gera orçamento em PDF no modelo Cantinho do Caruru."""
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        W, H = A4  # 595 × 842

        CORAL = colors.HexColor('#E55740')
        CINZA_SEP = colors.HexColor('#CCCCCC')
        CINZA_ZEBRA = colors.HexColor('#F8F8F8')
        MARG = 25
        LARG = W - 2 * MARG  # 545

        # ── LOGO ──────────────────────────────────────────────────────
        logo_h = 67
        logo_w = 70
        logo_x = (W - logo_w) / 2
        logo_y = H - 25 - logo_h  # bottom-left of logo image
        if os.path.exists("logo.png"):
            try:
                p.drawImage("logo.png", logo_x, logo_y, width=logo_w, height=logo_h,
                            mask='auto', preserveAspectRatio=True)
            except Exception:
                pass

        # ── BANNER ────────────────────────────────────────────────────
        ban_y = logo_y - 2         # top of banner = bottom of logo gap
        ban_h = 24
        p.setFillColor(CORAL)
        p.rect(MARG, ban_y - ban_h, LARG, ban_h, fill=1, stroke=0)
        p.setFillColor(colors.white)
        p.setFont("Helvetica-Bold", 18)
        p.drawCentredString(W / 2, ban_y - ban_h + 5, "P  E  D  I  D  O")

        # ── EMPRESA (esquerda) / CLIENTE (direita) ────────────────────
        bloco_y = ban_y - ban_h - 14  # first text line

        p.setFillColor(CORAL)
        p.setFont("Helvetica-Bold", 10)
        p.drawString(MARG, bloco_y, "CANTINHO DO CARURU")

        p.setFillColor(colors.black)
        p.setFont("Helvetica", 9)
        p.drawString(MARG, bloco_y - 14, "(79) 99929-6722")
        p.drawString(MARG, bloco_y - 27, "@cantinhodocaruru")

        cli_x = W / 2 + 15
        p.setFillColor(CORAL)
        p.setFont("Helvetica-Bold", 10)
        p.drawRightString(W - MARG, bloco_y, "CLIENTE:")

        cliente_nome = str(dados.get('Cliente', '')).strip().title()
        p.setFillColor(colors.black)
        p.setFont("Helvetica-Bold", 13)
        p.drawString(cli_x, bloco_y - 14, cliente_nome)

        p.setFont("Helvetica", 9)
        contato = str(dados.get('Contato', '')).strip()
        if contato:
            p.drawString(cli_x, bloco_y - 28, contato)

        endereco = str(dados.get('Endereco', '')).strip()
        if endereco:
            # wrap if long
            end_lines = _quebrar_texto(p, endereco, "Helvetica", 9, W - MARG - cli_x - 5)
            for i, ln in enumerate(end_lines[:2]):
                p.drawString(cli_x, bloco_y - 41 - i * 12, ln)

        # ── SEPARADOR ─────────────────────────────────────────────────
        sep_y = bloco_y - 56
        p.setStrokeColor(CINZA_SEP)
        p.setLineWidth(0.5)
        p.line(MARG, sep_y, W - MARG, sep_y)

        # ── TABELA PRODUTOS ───────────────────────────────────────────
        # Colunas (x): PRODUTO | QUANTIDADE | VALOR KG | TOTAL
        PC2 = 228   # início QUANTIDADE
        PC3 = 370   # início VALOR KG
        PC4 = 480   # início TOTAL

        HDR_H = 22
        ROW_H = 20

        tbl_top = sep_y - 8

        p.setFillColor(CORAL)
        p.rect(MARG, tbl_top - HDR_H, LARG, HDR_H, fill=1, stroke=0)
        p.setFillColor(colors.white)
        p.setFont("Helvetica-Bold", 9)
        hy = tbl_top - HDR_H + 7
        p.drawString(MARG + 10, hy, "PRODUTO")
        p.drawCentredString((PC2 + PC3) / 2, hy, "QUANTIDADE")
        p.drawCentredString((PC3 + PC4) / 2, hy, "VALOR KG")
        p.drawCentredString((PC4 + W - MARG) / 2, hy, "TOTAL")

        preco_atual = obter_preco_base()
        caruru = float(dados.get('Caruru', 0))
        bobo = float(dados.get('Bobo', 0))
        desconto = float(dados.get('Desconto', 0))

        itens = []
        if caruru > 0:
            itens.append(("CARURU", f"{int(caruru)} KG", preco_atual, caruru * preco_atual))
        if bobo > 0:
            itens.append(("BOBÓ DE CAMARÃO", f"{int(bobo)} KG", preco_atual, bobo * preco_atual))

        row_y = tbl_top - HDR_H
        for i, (nome, qtd, preco_kg, total_item) in enumerate(itens):
            row_y -= ROW_H
            p.setFillColor(CINZA_ZEBRA if i % 2 == 0 else colors.white)
            p.rect(MARG, row_y, LARG, ROW_H, fill=1, stroke=0)
            p.setFillColor(colors.black)
            p.setFont("Helvetica", 10)
            ty = row_y + 6
            p.drawString(MARG + 10, ty, nome)
            p.drawCentredString((PC2 + PC3) / 2, ty, qtd)
            p.drawCentredString((PC3 + PC4) / 2, ty, _brl(preco_kg))
            p.drawCentredString((PC4 + W - MARG) / 2, ty, _brl(total_item))
            # separadores verticais internos
            p.setStrokeColor(CINZA_SEP)
            p.setLineWidth(0.3)
            for cx in [PC2, PC3, PC4]:
                p.line(cx, row_y, cx, row_y + ROW_H)

        # borda da tabela
        p.setStrokeColor(CINZA_SEP)
        p.setLineWidth(0.5)
        p.rect(MARG, row_y, LARG, tbl_top - row_y, fill=0, stroke=1)

        # ── TABELA ENTREGA ────────────────────────────────────────────
        DC2 = 165   # início LOCAL
        DC3 = 415   # início HORÁRIO

        del_top = row_y - 10

        p.setFillColor(CORAL)
        p.rect(MARG, del_top - HDR_H, LARG, HDR_H, fill=1, stroke=0)
        p.setFillColor(colors.white)
        p.setFont("Helvetica-Bold", 9)
        dhy = del_top - HDR_H + 7
        p.drawCentredString((MARG + DC2) / 2, dhy, "DATA")
        p.drawCentredString((DC2 + DC3) / 2, dhy, "LOCAL")
        p.drawCentredString((DC3 + W - MARG) / 2, dhy, "HORÁRIO")

        del_row_y = del_top - HDR_H - ROW_H
        p.setFillColor(colors.white)
        p.rect(MARG, del_row_y, LARG, ROW_H, fill=1, stroke=0)
        p.setFillColor(colors.black)
        p.setFont("Helvetica", 10)
        dty = del_row_y + 6

        data = dados.get('Data')
        data_s = data.strftime('%d/%m/%Y') if hasattr(data, 'strftime') else str(data) if data else ""
        local_s = str(dados.get('Local', '')).strip()
        hora_s = str(dados.get('Hora', '')).strip()

        p.drawCentredString((MARG + DC2) / 2, dty, data_s)
        p.drawCentredString((DC2 + DC3) / 2, dty, local_s)
        p.drawCentredString((DC3 + W - MARG) / 2, dty, hora_s)

        p.setStrokeColor(CINZA_SEP)
        p.setLineWidth(0.3)
        for cx in [DC2, DC3]:
            p.line(cx, del_row_y, cx, del_row_y + ROW_H)
        p.setLineWidth(0.5)
        p.rect(MARG, del_row_y, LARG, del_top - del_row_y, fill=0, stroke=1)

        # ── SEÇÃO INFERIOR: OBS (esq) | TOTAL + PAGAMENTO (dir) ──────
        bot_top = del_row_y - 15
        subtotal_bruto = (caruru + bobo) * preco_atual
        desconto_valor = subtotal_bruto * desconto / 100
        total = subtotal_bruto - desconto_valor

        # Coluna direita
        rx = W / 2 + 10       # x início coluna direita
        rw = W - MARG - rx    # largura coluna direita (~238)

        # Caixa TOTAL
        tot_h = 42
        tot_y = bot_top - tot_h
        p.setStrokeColor(CINZA_SEP)
        p.setLineWidth(0.8)
        p.rect(rx, tot_y, rw, tot_h, fill=0, stroke=1)
        p.setFillColor(colors.black)
        p.setFont("Helvetica-Bold", 12)
        total_txt = f"TOTAL: {_brl(total)}"
        p.drawCentredString(rx + rw / 2, tot_y + tot_h / 2 - 4, total_txt)

        # Extenso abaixo da caixa
        extenso = _valor_por_extenso(total)
        ext_lines = _quebrar_texto(p, f"({extenso}).", "Helvetica-Oblique", 7, rw)
        ext_y = tot_y - 10
        p.setFont("Helvetica-Oblique", 7)
        p.setFillColor(colors.HexColor('#555555'))
        for ln in ext_lines:
            p.drawCentredString(rx + rw / 2, ext_y, ln)
            ext_y -= 9

        # Caixa FORMA DE PAGAMENTO
        forma_pag = str(dados.get('FormaPagamento', '')).strip()
        fpag_lines = _quebrar_texto(p, forma_pag, "Helvetica", 8.5, rw - 10) if forma_pag else []
        fpag_h = max(40, 18 + len(fpag_lines) * 11 + 8)
        fpag_y = ext_y - 8 - fpag_h
        p.setStrokeColor(CINZA_SEP)
        p.setLineWidth(0.8)
        p.rect(rx, fpag_y, rw, fpag_h, fill=0, stroke=1)
        # título
        p.setFillColor(CORAL)
        p.rect(rx, fpag_y + fpag_h - 16, rw, 16, fill=1, stroke=0)
        p.setFillColor(colors.white)
        p.setFont("Helvetica-Bold", 8)
        p.drawCentredString(rx + rw / 2, fpag_y + fpag_h - 11, "FORMA DE PAGAMENTO")
        # texto
        p.setFillColor(colors.black)
        p.setFont("Helvetica", 8.5)
        fpag_ty = fpag_y + fpag_h - 28
        for ln in fpag_lines:
            p.drawString(rx + 7, fpag_ty, ln)
            fpag_ty -= 11

        # Coluna esquerda: OBSERVAÇÕES
        obs = str(dados.get('Observacoes', '')).strip()
        if obs:
            p.setFillColor(CORAL)
            p.setFont("Helvetica-Bold", 10)
            p.drawString(MARG, bot_top, "OBSERVAÇÕES:")
            obs_y = bot_top - 15
            p.setFillColor(colors.black)
            p.setFont("Helvetica", 8.5)
            obs_lines = _quebrar_texto(p, obs, "Helvetica", 8.5, rx - MARG - 15)
            for ln in obs_lines:
                if obs_y < 35:
                    break
                p.drawString(MARG, obs_y, ln)
                obs_y -= 11

        # ── RODAPÉ ────────────────────────────────────────────────────
        p.setFont("Helvetica", 7)
        p.setFillColor(colors.grey)
        p.drawCentredString(W / 2, 18,
            f"Cantinho do Caruru  |  Emitido em: {agora_brasil().strftime('%d/%m/%Y %H:%M')}")

        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.error(f"Erro gerar orçamento PDF: {e}", exc_info=True)
        return None
