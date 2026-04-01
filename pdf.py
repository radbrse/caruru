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
        except:
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


def gerar_orcamento_pdf(dados):
    """Gera orçamento/proposta comercial em PDF."""
    try:
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=A4)
        desenhar_cabecalho(p, "ORÇAMENTO")

        agora = agora_brasil()
        num_orc = agora.strftime("%Y%m%d%H%M")
        y = 700

        # Número e datas
        p.setFont("Helvetica", 9)
        p.setFillColor(colors.grey)
        p.drawString(30, y, f"Nº {num_orc}")
        p.drawString(300, y, f"Emitido em: {agora.strftime('%d/%m/%Y %H:%M')}")
        validade = dados.get('Validade')
        if validade:
            val_s = validade.strftime('%d/%m/%Y') if hasattr(validade, 'strftime') else str(validade)
            p.drawString(300, y - 14, f"Válido até: {val_s}")
            y -= 14
        p.setFillColor(colors.black)
        y -= 28

        # Dados do cliente
        p.setFont("Helvetica-Bold", 12)
        p.drawString(30, y, "DADOS DO CLIENTE")
        y -= 18
        p.setFont("Helvetica", 11)
        p.drawString(30, y, f"Nome: {dados.get('Cliente', '')}")
        contato = dados.get('Contato', '')
        if contato:
            p.drawString(300, y, f"WhatsApp: {contato}")
        y -= 35

        # Cabeçalho da tabela de itens
        p.setFillColor(colors.HexColor('#2c3e50'))
        p.rect(30, y - 5, 535, 22, fill=1, stroke=0)
        p.setFillColor(colors.white)
        p.setFont("Helvetica-Bold", 10)
        p.drawString(40, y, "ITEM")
        p.drawString(310, y, "QTD")
        p.drawString(390, y, "UNIT.")
        p.drawString(480, y, "SUBTOTAL")
        p.setFillColor(colors.black)
        y -= 28

        # Cálculos
        preco_atual = obter_preco_base()
        preco_fmt = f"R$ {preco_atual:.2f}".replace(".", ",")
        caruru = float(dados.get('Caruru', 0))
        bobo = float(dados.get('Bobo', 0))
        desconto = float(dados.get('Desconto', 0))
        subtotal_bruto = (caruru + bobo) * preco_atual
        desconto_valor = subtotal_bruto * desconto / 100
        total = subtotal_bruto - desconto_valor

        # Linhas de itens com zebra
        linha_par = True
        p.setFont("Helvetica", 10)
        if caruru > 0:
            if linha_par:
                p.setFillColor(colors.HexColor('#f2f3f4'))
                p.rect(30, y - 4, 535, 17, fill=1, stroke=0)
                p.setFillColor(colors.black)
            sub_fmt = f"R$ {caruru * preco_atual:.2f}".replace(".", ",")
            p.drawString(40, y, "Caruru Tradicional")
            p.drawString(310, y, f"{int(caruru)} kg")
            p.drawString(390, y, preco_fmt)
            p.drawString(480, y, sub_fmt)
            y -= 18
            linha_par = not linha_par

        if bobo > 0:
            if linha_par:
                p.setFillColor(colors.HexColor('#f2f3f4'))
                p.rect(30, y - 4, 535, 17, fill=1, stroke=0)
                p.setFillColor(colors.black)
            sub_fmt = f"R$ {bobo * preco_atual:.2f}".replace(".", ",")
            p.drawString(40, y, "Bobó de Camarão")
            p.drawString(310, y, f"{int(bobo)} kg")
            p.drawString(390, y, preco_fmt)
            p.drawString(480, y, sub_fmt)
            y -= 18

        p.setLineWidth(1)
        p.line(30, y - 8, 565, y - 8)
        y -= 28

        # Subtotal
        p.setFont("Helvetica", 11)
        p.drawString(380, y, "Subtotal:")
        p.drawRightString(565, y, f"R$ {subtotal_bruto:.2f}".replace(".", ","))
        y -= 18

        # Desconto (se houver)
        if desconto > 0:
            p.setFont("Helvetica-Oblique", 10)
            p.setFillColor(colors.red)
            p.drawString(380, y, f"Desconto ({desconto:.0f}%):")
            p.drawRightString(565, y, f"- R$ {desconto_valor:.2f}".replace(".", ","))
            p.setFillColor(colors.black)
            y -= 18

        # Box de total destacado
        y -= 8
        p.setFillColor(colors.HexColor('#eaf4fb'))
        p.rect(330, y - 8, 235, 26, fill=1, stroke=0)
        p.setFillColor(colors.HexColor('#1a5276'))
        p.setFont("Helvetica-Bold", 14)
        p.drawString(345, y, "TOTAL:")
        p.drawRightString(558, y, f"R$ {total:.2f}".replace(".", ","))
        p.setFillColor(colors.black)
        y -= 45

        # Pagamento
        p.setFont("Helvetica-Bold", 11)
        p.drawString(30, y, "PAGAMENTO")
        y -= 18
        p.setFont("Helvetica", 10)
        p.drawString(30, y, f"Chave PIX: {CHAVE_PIX}")
        y -= 30

        # Observações
        obs = dados.get('Observacoes', '')
        if obs:
            p.setFont("Helvetica-Bold", 11)
            p.drawString(30, y, "OBSERVAÇÕES")
            y -= 16
            p.setFont("Helvetica-Oblique", 9)
            for line in _quebrar_texto(p, obs, "Helvetica-Oblique", 9, 535):
                p.drawString(30, y, line)
                y -= 12
            y -= 10

        # Linhas de assinatura
        y_ass = max(y - 40, 110)
        p.setFont("Helvetica", 9)
        p.setFillColor(colors.grey)
        p.drawString(30, y_ass + 20, "Para confirmar este orçamento, assine abaixo e realize o pagamento via PIX.")
        p.setFillColor(colors.black)
        p.setLineWidth(0.8)
        p.line(30, y_ass, 250, y_ass)
        p.drawCentredString(140, y_ass - 14, "Assinatura do Cliente")
        p.line(310, y_ass, 565, y_ass)
        p.drawCentredString(437, y_ass - 14, "Data de Aceite")

        p.setFont("Helvetica-Oblique", 8)
        p.setFillColor(colors.grey)
        p.drawCentredString(300, 30, f"Cantinho do Caruru | Orçamento Nº {num_orc} | {agora.strftime('%d/%m/%Y %H:%M')}")

        p.showPage()
        p.save()
        buffer.seek(0)
        return buffer
    except Exception as e:
        logger.error(f"Erro gerar orçamento PDF: {e}", exc_info=True)
        return None
