import sys
from pathlib import Path
from datetime import date, timedelta
import pytest
import pandas as pd
import streamlit as st
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(st, 'secrets', {})
    monkeypatch.setattr(st, 'session_state', State(sync_automatico_habilitado=False))
    monkeypatch.setattr(st, 'toast', lambda *a, **k: None)
    def sem_rede(*a, **k):
        raise AssertionError('Rede real proibida nos testes')
    monkeypatch.setattr(requests.sessions.Session, 'request', sem_rede)
    import config, database, sheets
    monkeypatch.setattr(sheets, 'conectar_google_sheets', lambda: None)
    assert config.salvar_config({'preco_base': 70.0})
    row = dict(ID_Pedido=1, Cliente='Cliente Teste', Caruru=1., Bobo=0., Valor=70.,
               Data=date.today()+timedelta(days=7), Hora='12:00', Hora_Entrega='',
               Status='🔴 Pendente', Pagamento='NÃO PAGO', Contato='', Desconto=0.,
               Entrada=0., Observacoes='', Extra=False, Vegano=False, Delivery=False)
    assert database.salvar_pedidos(pd.DataFrame([row]), substituir=True)
    assert database.salvar_clientes(pd.DataFrame([dict(Nome='Cliente Teste', Contato='', Observacoes='')]), substituir=True)
    st.session_state.pedidos = database.carregar_pedidos()
    st.session_state.clientes = database.carregar_clientes()
    return tmp_path, row
