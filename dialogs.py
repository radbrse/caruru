"""
Módulo de Diálogos Modais
Contém funções de diálogo reutilizáveis para confirmações e interações.
"""

import streamlit as st
from config import logger, hoje_brasil
from utils import formatar_valor_br, calcular_total, get_whatsapp_link
from pedidos import criar_pedido


@st.dialog("⚠️ CONFIRMAR DATA DO PEDIDO", width="large")
def confirmar_data_pedido():
    """Dialog modal para confirmação de data antes de salvar pedido."""
    if 'pedido_pendente' not in st.session_state or not st.session_state.pedido_pendente:
        st.error("Erro: Nenhum pedido pendente")
        return

    pedido_temp = st.session_state.pedido_pendente
    dt_temp = pedido_temp['data']

    # Formata a data por extenso
    meses_nome = {
        1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
        5: "maio", 6: "junho", 7: "julho", 8: "agosto",
        9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro"
    }
    dias_semana = {
        0: "segunda-feira", 1: "terça-feira", 2: "quarta-feira",
        3: "quinta-feira", 4: "sexta-feira", 5: "sábado", 6: "domingo"
    }
    dia_semana = dias_semana[dt_temp.weekday()]
    data_formatada = f"{dia_semana}, {dt_temp.day} de {meses_nome[dt_temp.month]} de {dt_temp.year}"

    # Mensagem destacada baseada na data
    if dt_temp == hoje_brasil():
        st.success(f"### 📅 Data selecionada: **HOJE**")
        st.markdown(f"**{data_formatada}**")
    else:
        dias_diferenca = (dt_temp - hoje_brasil()).days
        if dias_diferenca == 1:
            st.warning(f"### 📅 Data selecionada: **AMANHÃ**")
        else:
            st.warning(f"### 📅 Data selecionada: **DAQUI A {dias_diferenca} DIAS**")
        st.markdown(f"**{data_formatada}**")

    st.divider()

    # Resumo do pedido
    st.markdown("### 📋 Resumo do Pedido")
    col_resumo1, col_resumo2 = st.columns(2)

    with col_resumo1:
        st.markdown(f"""
        **👤 Cliente:** {pedido_temp['cliente']}
        **⏰ Hora:** {pedido_temp['hora'].strftime('%H:%M')}
        """)
        st.markdown(f"**Contato:** {get_whatsapp_link(pedido_temp['contato'])}", unsafe_allow_html=True)

    with col_resumo2:
        valor_total = calcular_total(pedido_temp['caruru'], pedido_temp['bobo'], pedido_temp['desconto'])
        st.markdown(f"""
        **🥘 Caruru:** {pedido_temp['caruru']} un.
        **🦐 Bobó:** {pedido_temp['bobo']} un.
        **💰 Valor:** {formatar_valor_br(valor_total)}
        """)

    if pedido_temp['desconto'] > 0:
        st.info(f"💸 Desconto aplicado: {pedido_temp['desconto']}%")

    if pedido_temp['observacoes']:
        st.markdown(f"**📝 Obs:** {pedido_temp['observacoes']}")

    st.divider()
    st.markdown("### ⚠️ A data está correta?")

    col_confirma, col_cancela = st.columns(2)

    with col_confirma:
        if st.button("✅ SIM, SALVAR PEDIDO", use_container_width=True, type="primary", key="btn_confirmar_data_pedido"):
            # Salva o pedido
            id_criado, erros, avisos = criar_pedido(
                cliente=pedido_temp['cliente'],
                caruru=pedido_temp['caruru'],
                bobo=pedido_temp['bobo'],
                data=pedido_temp['data'],
                hora=pedido_temp['hora'],
                status=pedido_temp['status'],
                pagamento=pedido_temp['pagamento'],
                contato=pedido_temp['contato'],
                desconto=pedido_temp['desconto'],
                observacoes=pedido_temp['observacoes']
            )

            if erros:
                for erro in erros:
                    st.error(erro)
            else:
                # Limpa o pedido pendente
                del st.session_state.pedido_pendente
                # Seta flag para resetar o cliente na próxima execução
                st.session_state.resetar_cliente_novo = True
                st.session_state.pedido_salvo_id = id_criado  # Guarda ID para toast
                st.rerun()

    with col_cancela:
        if st.button("❌ CORRIGIR DATA", use_container_width=True, key="btn_corrigir_data_pedido"):
            # Remove o pedido pendente e volta para o formulário
            del st.session_state.pedido_pendente
            st.rerun()
