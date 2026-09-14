"""Transporte compartilhado, sem Markdown e com confirmação de todas as partes."""
import requests


def dividir_mensagem(texto, limite=4000):
    # Reserva espaço para o contador. Conta UTF-16, conservador também com emojis.
    capacidade = limite - 40
    if capacidade < 1:
        raise ValueError('Limite muito pequeno')
    partes, bloco, tamanho = [], '', 0
    for linha in texto.splitlines(keepends=True):
        unidades = len(linha.encode('utf-16-le')) // 2
        if tamanho and tamanho + unidades > capacidade:
            partes.append(bloco)
            bloco, tamanho = '', 0
        for char in linha:
            custo = len(char.encode('utf-16-le')) // 2
            if tamanho + custo > capacidade:
                partes.append(bloco)
                bloco, tamanho = '', 0
            bloco += char
            tamanho += custo
    if bloco:
        partes.append(bloco)
    if not partes:
        raise ValueError('Mensagem vazia')
    if len(partes) == 1:
        return partes
    return [f'Parte {i}/{len(partes)}\n\n{parte}' for i, parte in enumerate(partes, 1)]


class EnvioTelegramParcial(RuntimeError):
    pass


def enviar_mensagem(token, chat_id, texto):
    partes = dividir_mensagem(texto)
    resultado = None
    for i, parte in enumerate(partes):
        try:
            resp = requests.post(f'https://api.telegram.org/bot{token}/sendMessage',
                                 json={'chat_id': chat_id, 'text': parte}, timeout=15)
            if resp.status_code != 200:
                raise RuntimeError(f'Telegram retornou HTTP {resp.status_code}')
            resultado = resp.json()
            if not resultado.get('ok'):
                raise RuntimeError('Telegram não confirmou o envio')
        except Exception:
            # Não expõe URLs com token nem presume resultado de uma requisição incerta.
            raise EnvioTelegramParcial(
                f'{i}/{len(partes)} partes confirmadas. Falha ou resposta incerta na parte {i + 1}. '
                'Confira o Telegram antes de repetir; um novo envio pode duplicar partes já recebidas.'
            ) from None
    return resultado
