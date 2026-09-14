import ast
import io
from pathlib import Path
from datetime import date, timedelta
from concurrent.futures import ProcessPoolExecutor
import multiprocessing
import pandas as pd
import pytest
import streamlit as st
from pypdf import PdfReader


@pytest.mark.parametrize('pagamento,entrada,recebido,saldo', [
    ('PAGO',0,70,0), ('NÃO PAGO',0,0,70), ('NÃO PAGO',30,30,40), ('METADE',0,35,35), ('METADE',20,20,50),
])
def test_recibo_valores_e_quitacao(ambiente,pagamento,entrada,recebido,saldo):
    from pdf import gerar_recibo_pdf
    from config import salvar_config
    row={**ambiente[1], 'Pagamento':pagamento,'Entrada':entrada}
    salvar_config({'preco_base':90})
    pdf=gerar_recibo_pdf(row)
    assert pdf is not None
    text=' '.join(p.extract_text() for p in PdfReader(pdf).pages)
    assert f'Valor recebido: R$ {recebido:.2f}'.replace('.',',') in text
    assert f'Saldo a pagar: R$ {saldo:.2f}'.replace('.',',') in text
    assert ('dando plena quitação' in text) == (saldo==0)
    assert 'R$ 90,00' not in text


def test_editar_observacao_preserva_preco_historico(ambiente):
    import pedidos,config,database
    config.salvar_config({'preco_base':90})
    ok,msg=pedidos.atualizar_pedido(1,{'Caruru':1,'Bobo':0,'Desconto':0,'Observacoes':'Alterado'})
    assert ok,msg
    assert database.carregar_pedidos().iloc[0]['Valor']==70
    ok,msg=pedidos.atualizar_pedido(1,{'Caruru':2})
    assert ok,msg
    assert database.carregar_pedidos().iloc[0]['Valor']==140


def test_sessao_antiga_nao_apaga_pedido_novo(ambiente):
    import database,pedidos
    disk=database.carregar_pedidos()
    newer=pd.concat([disk,pd.DataFrame([{**ambiente[1],'ID_Pedido':2}])],ignore_index=True)
    newer.attrs=disk.attrs.copy()
    assert database.salvar_pedidos(newer)
    ok,msg=pedidos.atualizar_pedido(1,{'Pagamento':'PAGO'})
    assert ok,msg
    assert set(database.carregar_pedidos().ID_Pedido)=={1,2}
    assert pedidos.excluir_pedido(1)[0]
    assert list(database.carregar_pedidos().ID_Pedido)==[2]


def test_gravacao_direta_obsoleta_e_rejeitada(ambiente):
    import database
    old=database.carregar_pedidos();new=old.copy()
    new.loc[0,'Observacoes']='Outra sessão'
    assert database.salvar_pedidos(new)
    old.loc[0,'Pagamento']='PAGO'
    assert not database.salvar_pedidos(old)
    atual=database.carregar_pedidos().iloc[0]
    assert atual.Observacoes=='Outra sessão' and atual.Pagamento=='NÃO PAGO'


def test_falha_salvar_nao_muda_memoria_nem_historico(ambiente,monkeypatch):
    import pedidos,database
    antes=st.session_state.pedidos.copy(deep=True)
    monkeypatch.setattr(pedidos,'salvar_pedidos',lambda *a,**k:False)
    ok,msg=pedidos.atualizar_pedido(1,{'Pagamento':'PAGO'})
    assert not ok
    pd.testing.assert_frame_equal(antes,st.session_state.pedidos)
    assert not Path('historico_alteracoes.csv').exists()
    assert database.carregar_pedidos().iloc[0].Pagamento=='NÃO PAGO'


def test_financeiro_inclui_entregue_e_exclui_cancelado(ambiente):
    from financeiro import totais_financeiros
    df=pd.DataFrame([{**ambiente[1],'Status':'✅ Entregue','Valor':100,'Entrada':30},
                     {**ambiente[1],'Status':'🚫 Cancelado','Valor':500}])
    assert totais_financeiros(df)==(100,70)


def test_todas_buscas_textuais_sao_literais(ambiente):
    root=Path(__file__).resolve().parents[1]
    count=0
    for file in ['pedidos_dia','gerenciar','clientes','promocoes']:
        tree=ast.parse((root/'views'/f'{file}.py').read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='contains':
                if node.args and isinstance(node.args[0],ast.Name) and node.args[0].id in ['termo','busca_cliente','filtro']:
                    assert any(k.arg=='regex' and isinstance(k.value,ast.Constant) and k.value.value is False for k in node.keywords)
                    count+=1
    assert count==6
    assert pd.Series(['Cliente [VIP]']).str.contains('[',regex=False).tolist()==[True]


def test_restore_download_parcial_nao_grava(ambiente,monkeypatch):
    import sheets
    antes=Path('banco_de_dados_caruru.csv').read_bytes()
    monkeypatch.setattr(sheets,'conectar_google_sheets',lambda:object())
    monkeypatch.setattr(sheets,'carregar_do_sheets',lambda c,a:(pd.DataFrame([ambiente[1]]),'ok') if a=='Pedidos' else (None,'falha'))
    ok,msg=sheets.sincronizar_com_sheets('receber')
    assert not ok
    assert Path('banco_de_dados_caruru.csv').read_bytes()==antes


@pytest.mark.parametrize('alvo',['clientes','config'])
def test_restore_falha_segunda_gravacao_rollback(ambiente,monkeypatch,alvo):
    import database,config
    arquivos=['banco_de_dados_caruru.csv','banco_de_dados_clientes.csv','config.json']
    antes={f:Path(f).read_bytes() for f in arquivos}
    if alvo=='clientes':monkeypatch.setattr(database,'salvar_clientes',lambda *a,**k:False)
    else:monkeypatch.setattr(config,'salvar_config',lambda *a,**k:False)
    ok,msg=database.restaurar_conjunto(pd.DataFrame([{**ambiente[1],'ID_Pedido':99}]),
                                     pd.DataFrame([dict(Nome='Novo',Contato='',Observacoes='')]),{'preco_base':90})
    assert not ok
    assert antes=={f:Path(f).read_bytes() for f in arquivos}


def test_restore_vazio_com_cabecalhos_e_config(ambiente):
    import database,config
    dp=database.carregar_pedidos().iloc[:0];dc=database.carregar_clientes().iloc[:0]
    assert database.restaurar_conjunto(dp,dc,{'preco_base':90})[0]
    assert database.carregar_pedidos().empty and database.carregar_clientes().empty
    assert config.obter_preco_base()==90


def test_preco_recuperado_sem_default(ambiente,monkeypatch):
    import config,sheets
    Path('config.json').unlink()
    monkeypatch.setattr(sheets,'conectar_google_sheets',lambda:object())
    monkeypatch.setattr(sheets,'ler_config_negocio',lambda c:{'preco_base':95})
    assert config.obter_preco_base()==95


def test_preco_ausente_ou_rede_nao_cria_70(ambiente,monkeypatch):
    import config,sheets
    Path('config.json').unlink()
    with pytest.raises(RuntimeError):config.carregar_config()
    assert not Path('config.json').exists()
    monkeypatch.setattr(sheets,'conectar_google_sheets',lambda:object())
    monkeypatch.setattr(sheets,'ler_config_negocio',lambda c:None)
    with pytest.raises(config.PrecoNaoConfigurado):config.carregar_config()
    assert not Path('config.json').exists()


def test_preco_so_muda_apos_confirmacao_remota(ambiente,monkeypatch):
    import config,sheets
    monkeypatch.setattr(sheets,'conectar_google_sheets',lambda:object())
    def falha(*a):raise RuntimeError('rede')
    monkeypatch.setattr(sheets,'salvar_config_negocio',falha)
    antes=Path('config.json').read_bytes()
    assert not config.atualizar_preco_base(99)[0]
    assert Path('config.json').read_bytes()==antes
    monkeypatch.setattr(sheets,'salvar_config_negocio',lambda *a:None)
    assert config.atualizar_preco_base(99)[0]
    assert config.obter_preco_base()==99


def test_backup_indicador_exige_assinatura_confirmada(ambiente):
    from storage import estado_backup,registrar_resultado_backup
    import config
    assert estado_backup()[0]=='warning'
    registrar_resultado_backup(True)
    assert estado_backup()[0]=='success'
    Path('.config-recuperar').touch()
    assert estado_backup()[0]=='warning'
    Path('.config-recuperar').unlink()
    config.salvar_config({'preco_base':99})
    assert estado_backup()[0]=='warning'
    registrar_resultado_backup(False,'erro')
    assert estado_backup()[0]=='error'
    assert estado_backup(False)[0]=='warning'


def test_sync_publica_disco_e_config_nao_sessao(ambiente,monkeypatch):
    import database,sheets
    df=database.carregar_pedidos();df.loc[0,'Observacoes']='Revisão atual'
    assert database.salvar_pedidos(df)
    uploads={}
    monkeypatch.setattr(sheets,'conectar_google_sheets',lambda:object())
    monkeypatch.setattr(sheets,'salvar_no_sheets',lambda c,a,d:uploads.setdefault(a,d) is not None and (True,'ok'))
    monkeypatch.setattr(sheets,'salvar_config_negocio',lambda c,d:uploads.update(Config=d))
    assert sheets.sincronizar_com_sheets('enviar')[0]
    assert uploads['Pedidos'].iloc[0].Observacoes=='Revisão atual'
    assert uploads['Config']=={'preco_base':70}


def test_telegram_grande_unicode_sem_perda(ambiente):
    from telegram_envio import dividir_mensagem
    from telegram_format import formatar_mensagem
    rows=[{**ambiente[1],'Cliente':f'Cliente [especial]_* {i} 🦐','Delivery':True,'Extra':True} for i in range(100)]
    text=formatar_mensagem(rows,date.today())
    parts=dividir_mensagem(text)
    assert len(parts)>1
    assert all(len(p.encode('utf-16-le'))//2<=4096 for p in parts)
    assert ''.join(p.split('\n\n',1)[1] for p in parts)==text
    assert '[Especial]_*' in text


def test_telegram_so_sucesso_apos_todas_partes(ambiente,monkeypatch):
    import telegram_envio
    payloads=[]
    class Resp:
        status_code=200
        def json(self):return {'ok':True,'result':{'message_id':1}}
    def post(*a,**k):payloads.append(k['json']);return Resp()
    monkeypatch.setattr(telegram_envio.requests,'post',post)
    assert telegram_envio.enviar_mensagem('FAKE','FAKE','a'*9000)['ok']
    assert len(payloads)==3 and all('parse_mode' not in p for p in payloads)
    payloads.clear()
    def parcial(*a,**k):
        if payloads:raise TimeoutError()
        payloads.append(k['json']);return Resp()
    monkeypatch.setattr(telegram_envio.requests,'post',parcial)
    with pytest.raises(telegram_envio.EnvioTelegramParcial,match='1/3 partes confirmadas'):
        telegram_envio.enviar_mensagem('FAKE','FAKE','a'*9000)


def _criar_em_processo(args):
    pasta,numero=args
    import os
    os.chdir(pasta)
    st.secrets={}
    from conftest import State
    st.session_state=State(sync_automatico_habilitado=False)
    import database,pedidos
    st.session_state.pedidos=database.carregar_pedidos()
    st.session_state.clientes=database.carregar_clientes()
    return pedidos.criar_pedido(f'Processo {numero}',1,0,date.today()+timedelta(days=7),
                               '12:00','🔴 Pendente','NÃO PAGO','',0,'')[0]


def test_duas_criacoes_processos_preservam_ids(ambiente):
    import database
    with ProcessPoolExecutor(2,mp_context=multiprocessing.get_context('spawn')) as pool:
        ids=list(pool.map(_criar_em_processo,[(str(ambiente[0]),1),(str(ambiente[0]),2)]))
    assert set(ids)=={2,3}
    assert set(database.carregar_pedidos().ID_Pedido)=={1,2,3}


def test_conflito_no_mesmo_pedido_e_explicito(ambiente):
    import database,pedidos
    outro=database.carregar_pedidos()
    outro.loc[0,'Observacoes']='Alteração da outra sessão'
    assert database.salvar_pedidos(outro)
    ok,msg=pedidos.atualizar_pedido(1,{'Observacoes':'Meu formulário antigo'})
    assert not ok and 'outra sessão' in msg
    assert database.carregar_pedidos().iloc[0].Observacoes=='Alteração da outra sessão'


def test_backup_zip_inclui_preco_e_disco_atual(ambiente):
    import database,zipfile,json
    df=database.carregar_pedidos();df.loc[0,'Observacoes']='Snapshot atualizado'
    assert database.salvar_pedidos(df)
    with zipfile.ZipFile(io.BytesIO(database.exportar_backup_zip())) as z:
        assert json.loads(z.read('config.json'))=={'preco_base':70}
        assert 'Snapshot atualizado' in z.read('pedidos.csv').decode()


def test_edicao_cliente_rollback_antes_de_publicar_sessao(ambiente,monkeypatch):
    import database
    from views.clientes import _salvar_edicao_cliente
    antes=Path('banco_de_dados_caruru.csv').read_bytes()
    sessao=st.session_state.pedidos.copy(deep=True)
    monkeypatch.setattr(database,'salvar_clientes',lambda *a,**k:False)
    ok,msg=_salvar_edicao_cliente('Cliente Teste','Novo nome','', 'obs')
    assert not ok
    assert Path('banco_de_dados_caruru.csv').read_bytes()==antes
    pd.testing.assert_frame_equal(sessao,st.session_state.pedidos)


def test_config_sheets_preserva_horario_e_data_envio(ambiente,monkeypatch):
    import sheets
    class WS:
        def __init__(self):
            self.rows=[{'Chave':'notification_hour','Valor':'9'},
                       {'Chave':'last_notification_date','Valor':'2026-09-12'}]
        def get_all_records(self):return self.rows
        def append_row(self,row):self.rows.append(dict(Chave=row[0],Valor=row[1]))
        def update_cell(self,row,col,value):self.rows[row-2]['Valor']=value
    ws=WS()
    class Book:
        def worksheet(self,name):return ws
    monkeypatch.setattr(sheets,'obter_ou_criar_planilha',lambda *a:Book())
    sheets.salvar_config_negocio(object(),{'preco_base':95})
    sheets.salvar_config_negocio(object(),{'preco_base':99})
    assert sheets.ler_config_negocio(object())=={'preco_base':99}
    assert ws.rows[:2]==[{'Chave':'notification_hour','Valor':'9'},
                         {'Chave':'last_notification_date','Valor':'2026-09-12'}]
    assert len(ws.rows)==3


def test_falha_limpeza_remota_nao_confirma_backup(ambiente,monkeypatch):
    import sheets
    class WS:
        row_count=100
        def update(self,**kwargs):pass
        def batch_clear(self,*a):raise RuntimeError('falha simulada')
    class Book:
        def worksheet(self,name):return WS()
    monkeypatch.setattr(sheets,'obter_ou_criar_planilha',lambda *a:Book())
    assert not sheets.salvar_no_sheets(object(),'Pedidos',st.session_state.pedidos)[0]


def test_corrupto_nao_vira_base_vazia(ambiente):
    import database
    Path('banco_de_dados_caruru.csv').write_text('"CSV sem fechar',encoding='utf-8')
    with pytest.raises(RuntimeError):database.carregar_pedidos()


def test_roundtrip_preserva_17_colunas_e_flags(ambiente):
    import database,config
    df=database.carregar_pedidos()
    df.loc[0,['Entrada','Extra','Vegano','Delivery']]=[30,True,True,True]
    assert database.salvar_pedidos(df)
    result=database.carregar_pedidos()
    assert list(result.columns)==config.COLUNAS_PEDIDOS and len(result.columns)==17
    assert result.iloc[0].Entrada==30
    assert all(bool(result.iloc[0][c]) for c in ['Extra','Vegano','Delivery'])


def test_preco_indisponivel_nao_salva_pedido_gratis(ambiente,monkeypatch):
    import utils,pedidos
    def falha():raise RuntimeError('Preço não recuperado')
    monkeypatch.setattr(utils,'obter_preco_base',falha)
    antes=Path('banco_de_dados_caruru.csv').read_bytes()
    nid,erros,_=pedidos.criar_pedido('Teste',1,0,date.today()+timedelta(days=1),
                                   '12:00','🔴 Pendente','NÃO PAGO','',0,'')
    assert nid is None and erros
    assert Path('banco_de_dados_caruru.csv').read_bytes()==antes


def test_notificador_nao_marca_dia_em_envio_parcial(ambiente,monkeypatch):
    import notificador
    from telegram_envio import EnvioTelegramParcial
    monkeypatch.setenv('GITHUB_EVENT_NAME','schedule')
    monkeypatch.setattr(notificador,'validar_secrets',lambda:('FAKE','FAKE','FAKE'))
    monkeypatch.setattr(notificador,'conectar_sheets',lambda c:object())
    monkeypatch.setattr(notificador,'obter_hora_notificacao',lambda c:0)
    monkeypatch.setattr(notificador,'obter_ultima_data_envio',lambda c:'')
    monkeypatch.setattr(notificador,'carregar_pedidos_amanha',lambda *a:[ambiente[1]])
    marcacoes=[]
    monkeypatch.setattr(notificador,'salvar_ultima_data_envio',lambda *a:marcacoes.append(a))
    def falha(*a):raise EnvioTelegramParcial('1/3 partes confirmadas')
    monkeypatch.setattr(notificador,'enviar_telegram',falha)
    with pytest.raises(EnvioTelegramParcial):notificador.main()
    assert marcacoes==[]
