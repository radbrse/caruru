import streamlit as st
import pandas as pd
from datetime import date, time, timedelta

from config import logger, hoje_brasil, agora_brasil, OPCOES_STATUS, OPCOES_PAGAMENTO, obter_preco_base
from utils import formatar_valor_br, calcular_total
from pedidos import criar_pedido
from database import carregar_pedidos, carregar_clientes


def render():
    st.title("📝 Novo Pedido")

    # Botão para limpar o formulário
    col_titulo, col_limpar = st.columns([4, 1])
    with col_limpar:
        if st.button("🔄 Limpar", help="Limpar todos os campos do formulário", key="btn_limpar_novo_pedido"):
            # Remove todas as keys relacionadas ao formulário
            keys_to_delete = ['cliente_novo_index', 'sel_cliente_novo', 'resetar_cliente_novo']
            for key in keys_to_delete:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

    # Verifica se deve resetar o cliente (após salvar pedido)
    if st.session_state.get('resetar_cliente_novo', False):
        # Deleta as keys do selectbox para forçar reset
        if 'sel_cliente_novo' in st.session_state:
            del st.session_state['sel_cliente_novo']
        if 'cliente_novo_index' in st.session_state:
            del st.session_state['cliente_novo_index']
        st.session_state.resetar_cliente_novo = False
        logger.info("Formulário de novo pedido resetado com sucesso")

    # Inicializa índice do cliente (sempre volta para 0 = "-- Selecione --")
    if 'cliente_novo_index' not in st.session_state:
        st.session_state.cliente_novo_index = 0

    # Carrega lista de clientes
    try:
        clis = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
    except:
        clis = []

    lista_clientes = ["-- Selecione --"] + clis

    st.markdown("### 1️⃣ Cliente")

    # Selectbox do cliente FORA do form para poder buscar o contato
    c_sel = st.selectbox(
        "👤 Nome do Cliente",
        lista_clientes,
        index=st.session_state.cliente_novo_index,
        key="sel_cliente_novo"
    )

    # Busca o contato do cliente selecionado
    contato_cliente = ""
    if c_sel and c_sel != "-- Selecione --":
        try:
            res = st.session_state.clientes[st.session_state.clientes['Nome'] == c_sel]
            if not res.empty:
                contato_cliente = str(res.iloc[0]['Contato']) if pd.notna(res.iloc[0]['Contato']) else ""
        except:
            contato_cliente = ""
    else:
        c_sel = ""  # Reseta para vazio se for "-- Selecione --"

    if not c_sel:
        st.info("💡 Selecione um cliente cadastrado ou cadastre um novo em '👥 Cadastrar Clientes'")
    else:
        st.success(f"📱 Contato encontrado: **{contato_cliente}**" if contato_cliente else "⚠️ Cliente sem telefone cadastrado")

    st.markdown("### 2️⃣ Dados do Pedido")

    # Usar form com clear_on_submit para limpar automaticamente
    with st.form("form_novo_pedido", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            cont = st.text_input("📱 WhatsApp", value=contato_cliente, placeholder="79999999999")
        with c2:
            dt = st.date_input("📅 Data Entrega", min_value=hoje_brasil(), format="DD/MM/YYYY")
            # Mostra a data por extenso para confirmação visual
            meses = {
                1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
                5: "maio", 6: "junho", 7: "julho", 8: "agosto",
                9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
            }
            dias_semana = {
                0: "segunda-feira", 1: "terça-feira", 2: "quarta-feira",
                3: "quinta-feira", 4: "sexta-feira", 5: "sábado", 6: "domingo"
            }
            dia_semana = dias_semana[dt.weekday()]
            data_extenso = f"{dia_semana}, {dt.day} de {meses[dt.month]} de {dt.year}"
            st.caption(f"📆 **{data_extenso}**")
        with c3:
            h_ent = st.time_input("⏰ Hora Retirada", value=time(12, 0), help="Horário que o cliente vai retirar o pedido")

        st.markdown("### 3️⃣ Itens do Pedido")
        c3, c4, c5 = st.columns(3)
        with c3:
            qc = st.number_input("🥘 Caruru (qtd)", min_value=0, max_value=999, step=1, value=0)
        with c4:
            qb = st.number_input("🦐 Bobó (qtd)", min_value=0, max_value=999, step=1, value=0)
        with c5:
            dc = st.number_input("💸 Desconto %", min_value=0, max_value=100, step=5, value=0)

        # Preview do valor (dentro do form não atualiza em tempo real, mas mostra o cálculo)
        preco_atual = obter_preco_base()
        st.caption(f"💵 Preço unitário: R$ {preco_atual:.2f} | Cálculo: (Caruru + Bobó) × R$ {preco_atual:.2f} - Desconto%")

        obs = st.text_area("📝 Observações", placeholder="Ex: Sem pimenta, entregar na portaria...")

        c6, c7 = st.columns(2)
        with c6:
            pg = st.selectbox("💳 Pagamento", OPCOES_PAGAMENTO)
        with c7:
            stt = st.selectbox("📊 Status", OPCOES_STATUS)

        # Botão de salvar
        submitted = st.form_submit_button("💾 SALVAR PEDIDO", use_container_width=True, type="primary")

        if submitted:
            # Usa o cliente selecionado FORA do form
            cliente_final = c_sel if c_sel and c_sel != "-- Selecione --" else ""

            # Guarda os dados do pedido em session_state para o dialog
            st.session_state.pedido_pendente = {
                'cliente': cliente_final,
                'caruru': qc,
                'bobo': qb,
                'data': dt,
                'hora': h_ent,
                'status': stt,
                'pagamento': pg,
                'contato': cont,
                'desconto': dc,
                'observacoes': obs
            }
            st.rerun()

    # Mostra toast de sucesso se pedido foi salvo
    if 'pedido_salvo_id' in st.session_state:
        st.toast(f"✅ Pedido #{st.session_state.pedido_salvo_id} criado com sucesso!", icon="✅")
        st.balloons()
        del st.session_state.pedido_salvo_id

    # Abre dialog modal de confirmação se há pedido pendente
    if 'pedido_pendente' in st.session_state and st.session_state.pedido_pendente:
        from dialogs import confirmar_data_pedido
        confirmar_data_pedido()

    # Mostrar valor estimado fora do form (para referência)
    st.divider()
    st.markdown("### 💰 Calculadora de Valor")
    calc_c1, calc_c2, calc_c3, calc_c4 = st.columns(4)
    with calc_c1:
        calc_car = st.number_input("Caruru", min_value=0, max_value=999, step=1, value=0, key="calc_car")
    with calc_c2:
        calc_bob = st.number_input("Bobó", min_value=0, max_value=999, step=1, value=0, key="calc_bob")
    with calc_c3:
        calc_desc = st.number_input("Desc %", min_value=0, max_value=100, step=5, value=0, key="calc_desc")
    with calc_c4:
        valor_calc = calcular_total(calc_car, calc_bob, calc_desc)
        st.metric("Total", f"R$ {valor_calc:.2f}")
