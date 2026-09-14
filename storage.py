"""Serialização entre sessões/processos e revisões dos arquivos locais."""
import hashlib
import json
import os
from functools import lru_cache, wraps
from pathlib import Path

from filelock import FileLock


@lru_cache(maxsize=8)
def _lock(diretorio):
    # Uma instância por diretório; reentrante na mesma thread.
    return FileLock(str(Path(diretorio) / '.caruru-transacao.lock'), timeout=60)


def transacao_dados():
    return _lock(str(Path.cwd().resolve()))


def transacional(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with transacao_dados():
            return func(*args, **kwargs)
    return wrapped


def revisao(arquivo):
    path = Path(arquivo)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def com_revisao(df, arquivo):
    df.attrs['revisao_arquivo'] = revisao(arquivo)
    return df


def conferir_revisao(df, arquivo, substituir=False):
    if substituir:
        return
    atual = revisao(arquivo)
    if (('revisao_arquivo' in df.attrs and df.attrs['revisao_arquivo'] != atual)
            or (atual is not None and 'revisao_arquivo' not in df.attrs)):
        raise ValueError('Os dados mudaram em outra sessão. Recarregue os dados e repita a alteração.')


def escrever_json(arquivo, dados):
    temp = str(arquivo) + '.tmp'
    with open(temp, 'w', encoding='utf-8') as handle:
        json.dump(dados, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, arquivo)


@transacional
def assinatura_dados():
    from config import ARQUIVO_PEDIDOS, ARQUIVO_CLIENTES, ARQUIVO_CONFIG
    partes = [revisao(p) for p in (ARQUIVO_PEDIDOS, ARQUIVO_CLIENTES, ARQUIVO_CONFIG, '.config-recuperar')]
    return hashlib.sha256(json.dumps(partes).encode()).hexdigest()


@transacional
def registrar_resultado_backup(sucesso, erro=None):
    from config import agora_brasil
    escrever_json('.backup-confirmado.json', {
        'sucesso': bool(sucesso), 'assinatura': assinatura_dados() if sucesso else None,
        'data': agora_brasil().strftime('%d/%m/%Y %H:%M:%S'), 'erro': erro,
    })


@transacional
def estado_backup(habilitado=True):
    if not habilitado:
        return 'warning', 'Backup automático desativado. Faça um backup manual.'
    try:
        estado = json.loads(Path('.backup-confirmado.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return 'warning', 'Backup ainda não confirmado nesta execução.'
    if not estado.get('sucesso'):
        return 'error', 'Falha no último backup. Consulte o diagnóstico e tente novamente.'
    if estado.get('assinatura') != assinatura_dados():
        return 'warning', 'Há alterações locais aguardando confirmação de backup.'
    return 'success', f"Backup confirmado em {estado['data']}."
