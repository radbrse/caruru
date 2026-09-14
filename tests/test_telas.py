"""Smoke test do app real com dados locais fictícios, sem serviços externos."""
from pathlib import Path
import json
from datetime import date
import pandas as pd
from streamlit.testing.v1 import AppTest


def test_navegacao_e_busca_literal(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path/'config.json').write_text(json.dumps({'preco_base':70}),encoding='utf-8')
    row=dict(ID_Pedido=1,Cliente='Teste [VIP]',Caruru=1,Bobo=0,Valor=70,Data=str(date.today()),
             Hora='12:00',Hora_Entrega='',Status='🔴 Pendente',Pagamento='NÃO PAGO',Contato='',
             Desconto=0,Entrada=20,Observacoes='',Extra=False,Vegano=False,Delivery=False)
    pd.DataFrame([row]).to_csv('banco_de_dados_caruru.csv',index=False)
    pd.DataFrame([dict(Nome='Teste [VIP]',Contato='',Observacoes='')]).to_csv('banco_de_dados_clientes.csv',index=False)
    import sheets,requests
    def sem_rede(*a,**k):raise AssertionError('Rede real proibida')
    monkeypatch.setattr(requests.sessions.Session,'request',sem_rede)
    monkeypatch.setattr(sheets,'verificar_status_sheets',lambda:(False,'Ambiente de teste'))
    monkeypatch.setattr(sheets,'conectar_google_sheets',lambda:None)
    at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=15)
    at.secrets['password']='teste-local'
    at.session_state['password_correct']=True
    at.run()
    assert not at.exception
    assert any('não confirmado' in v.value for v in at.warning)
    at.text_input(key='busca_pedidos_dia').input('[').run()
    assert not at.exception
    for page in ['Novo Pedido','Gerenciar Tudo','📜 Histórico','🖨️ Relatórios & Recibos','📢 Promoções','👥 Cadastrar Clientes','🛠️ Manutenção']:
        at.radio(key='menu_navegacao_principal').set_value(page).run()
        assert not at.exception, (page,[e.message for e in at.exception])
    import views.manutencao as manutencao
    chamadas=[]
    monkeypatch.setattr(manutencao,'verificar_status_sheets',lambda:(True,'Sheets fictício'))
    monkeypatch.setattr(manutencao,'sincronizar_com_sheets',lambda modo:chamadas.append(modo) or (False,'Falha simulada de restauração'))
    at.run()
    at.button(key='preparar_restore').click().run()
    assert not at.exception
    at.checkbox(key='aceitar_restore').check().run()
    assert at.button(key='confirmar_restore_exec').disabled is False
    at.button(key='confirmar_restore_exec').click().run()
    assert chamadas==['receber']
    assert any('Falha simulada' in v.value for v in at.error)
