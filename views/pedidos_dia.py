"""Página de Pedidos do Dia."""

import streamlit as st
import pandas as pd
from datetime import time
import time as time_module

from config import logger, hoje_brasil, OPCOES_STATUS, OPCOES_PAGAMENTO
from utils import formatar_valor_br, get_status_badge, get_pagamento_badge, get_obs_icon, get_extra_badge, get_valor_destaque, get_whatsapp_link, calcular_total
from database import salvar_pedidos, carregar_pedidos, registrar_alteracao
from pedidos import atualizar_pedido, excluir_pedido
from sheets import sincronizar_automaticamente


def render():
    st.title("📅 Pedidos do Dia")
    df = st.session_state.pedidos

    if df.empty:
        st.info("Sem dados cadastrados.")
    else:
        dt_filter = st.date_input("📅 Data:", hoje_brasil(), format="DD/MM/YYYY")
        df_dia = df[df['Data'] == dt_filter].copy()
        df_dia = df_dia[df_dia['Status'] != "✅ Entregue"]

        col_busca, col_ord = st.columns([2, 1])
        with col_busca:
            busca = st.text_input(
                "🔍 Buscar por nome ou ID",
                placeholder="Digite o nome do cliente ou número do pedido...",
                key="busca_pedidos_dia"
            )

        if busca and busca.strip():
            termo = busca.strip().lower()
            df_dia = df_dia[
                df_dia['Cliente'].str.lower().str.contains(termo, na=False) |
                df_dia['ID_Pedido'].astype(str).str.contains(termo, na=False)
            ]

        with col_ord:
            ordem_dia = st.selectbox("Ordenar por", [
                "⏰ Hora (crescente)",
                "⏰ Hora (decrescente)",
                "💵 Valor (maior)",
                "💵 Valor (menor)",
                "👤 Cliente (A-Z)",
                "👤 Cliente (Z-A)",
                "📊 Status",
                "🆔 ID (maior)",
                "🆔 ID (menor)"
            ], index=0, key="ordem_pedidos_dia")

        try:
            if ordem_dia == "⏰ Hora (crescente)":
                df_dia['h_sort'] = df_dia['Hora'].apply(lambda x: x if isinstance(x, time) else time(23, 59))
                df_dia = df_dia.sort_values(['h_sort', 'Cliente'], ascending=[True, True]).drop(columns=['h_sort'])
            elif ordem_dia == "⏰ Hora (decrescente)":
                df_dia['h_sort'] = df_dia['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
                df_dia = df_dia.sort_values('h_sort', ascending=False).drop(columns=['h_sort'])
            elif ordem_dia == "💵 Valor (maior)":
                df_dia = df_dia.sort_values('Valor', ascending=False)
            elif ordem_dia == "💵 Valor (menor)":
                df_dia = df_dia.sort_values('Valor', ascending=True)
            elif ordem_dia == "👤 Cliente (A-Z)":
                df_dia = df_dia.sort_values('Cliente', ascending=True)
            elif ordem_dia == "👤 Cliente (Z-A)":
                df_dia = df_dia.sort_values('Cliente', ascending=False)
            elif ordem_dia == "📊 Status":
                df_dia = df_dia.sort_values('Status', ascending=True)
            elif ordem_dia == "🆔 ID (maior)":
                df_dia = df_dia.sort_values('ID_Pedido', ascending=False)
            elif ordem_dia == "🆔 ID (menor)":
                df_dia = df_dia.sort_values('ID_Pedido', ascending=True)
        except Exception as e:
            logger.warning(f"Erro ao ordenar pedidos do dia: {e}")
            pass

        total_dia = len(df[df['Data'] == dt_filter])

        c1, c2, c3, c4, c5, c6 = st.columns(6)

        pend = df_dia[
            (~df_dia['Status'].str.contains("Entregue", na=False)) &
            (~df_dia['Status'].str.contains("Cancelado", na=False))
        ]

        df_nao_cancelados = df_dia[~df_dia['Status'].str.contains("Cancelado", na=False)]
        faturamento = df_nao_cancelados['Valor'].sum()

        valor_nao_pago = df_nao_cancelados[df_nao_cancelados['Pagamento'] == 'NÃO PAGO']['Valor'].sum()
        valor_metade = df_nao_cancelados[df_nao_cancelados['Pagamento'] == 'METADE']['Valor'].sum() * 0.5
        a_receber = valor_nao_pago + valor_metade

        c1.metric("📦 Pedidos do dia", total_dia)
        c2.metric("⏳ Falta entregar", len(pend))
        c3.metric("🥘 Caruru (Pend)", int(pend['Caruru'].sum()))
        c4.metric("🦐 Bobó (Pend)", int(pend['Bobo'].sum()))
        c5.metric("💰 Faturamento", formatar_valor_br(faturamento))
        c6.metric("📥 A Receber", formatar_valor_br(a_receber), delta_color="inverse")

        st.divider()
        st.subheader("📋 Entregas do Dia")

        if not df_dia.empty:
            linha_num = 0
            for idx, pedido in df_dia.iterrows():
                with st.container():
                    st.markdown(f"""
                        <style>
                        div[data-testid="stVerticalBlock"] > div:nth-child({linha_num + 1}) {{
                            padding: 0px;
                            margin: 0px;
                            line-height: 1.2;
                        }}
                        </style>
                    """, unsafe_allow_html=True)

                    col1, col2, col3, col4, col5, col6, col7, col8, col9, col10, col11 = st.columns([0.4, 1.5, 0.7, 0.7, 0.7, 0.9, 0.9, 0.4, 0.3, 0.3, 0.4])

                    with col1:
                        st.markdown(f"<div style='font-size:1.05rem; font-weight:700; color:#1f2937;'>#{int(pedido['ID_Pedido'])}</div>", unsafe_allow_html=True)
                    with col2:
                        extra_tag = f" {get_extra_badge(pedido.get('Extra', False))}" if pedido.get('Extra', False) else ""
                        st.markdown(f"<div style='font-size:0.9rem; font-weight:700; color:#374151;'>👤 {pedido['Cliente']}{extra_tag}</div>", unsafe_allow_html=True)
                    with col3:
                        hora_str = pedido['Hora'].strftime('%H:%M') if isinstance(pedido['Hora'], time) else str(pedido['Hora'])[:5]
                        st.markdown(f"<div style='font-size:0.95rem; font-weight:700; color:#374151;'>⏰ {hora_str}</div>", unsafe_allow_html=True)
                    with col4:
                        st.markdown(f"<div style='font-size:0.95rem; font-weight:700; color:#374151;'>🥘 {int(pedido['Caruru'])} 🦐 {int(pedido['Bobo'])}</div>", unsafe_allow_html=True)
                    with col5:
                        st.markdown(get_valor_destaque(pedido['Valor']), unsafe_allow_html=True)
                    with col6:
                        st.markdown(get_status_badge(pedido['Status']), unsafe_allow_html=True)
                    with col7:
                        st.markdown(get_pagamento_badge(pedido['Pagamento']), unsafe_allow_html=True)
                    with col8:
                        st.markdown(get_obs_icon(pedido['Observacoes']), unsafe_allow_html=True)
                    with col9:
                        if st.button("👁️", key=f"ver_{pedido['ID_Pedido']}", help="Visualizar", use_container_width=True):
                            st.session_state[f"visualizar_{pedido['ID_Pedido']}"] = not st.session_state.get(f"visualizar_{pedido['ID_Pedido']}", False)
                            st.rerun()
                    with col10:
                        if st.button("✏️", key=f"edit_{pedido['ID_Pedido']}", help="Editar", use_container_width=True):
                            id_clicado = int(pedido['ID_Pedido'])
                            if st.session_state.get('pedido_em_edicao_dia_id') == id_clicado:
                                st.session_state['pedido_em_edicao_dia_id'] = None
                            else:
                                st.session_state['pedido_em_edicao_dia_id'] = id_clicado
                            st.rerun()
                    with col11:
                        if pedido['Status'] != "✅ Entregue":
                            if st.button("✅", key=f"entregue_{pedido['ID_Pedido']}", help="Marcar como Entregue e Pago", use_container_width=True, type="primary"):
                                st.session_state[f"confirmar_entregue_{pedido['ID_Pedido']}"] = True
                                st.rerun()

                    if st.session_state.get(f"confirmar_entregue_{pedido['ID_Pedido']}", False):
                        st.info(f"✅ Confirmar entrega e pagamento do pedido de **{pedido['Cliente']}** (#{int(pedido['ID_Pedido'])})?")
                        col_sim_ent, col_nao_ent = st.columns(2)
                        with col_sim_ent:
                            if st.button("✅ SIM, CONFIRMAR", key=f"sim_entregue_{pedido['ID_Pedido']}", use_container_width=True, type="primary"):
                                from config import agora_brasil
                                idx_original = st.session_state.pedidos[st.session_state.pedidos['ID_Pedido'] == pedido['ID_Pedido']].index[0]
                                status_antigo = st.session_state.pedidos.at[idx_original, 'Status']
                                pagamento_antigo = st.session_state.pedidos.at[idx_original, 'Pagamento']

                                st.session_state.pedidos.at[idx_original, 'Status'] = "✅ Entregue"
                                st.session_state.pedidos.at[idx_original, 'Pagamento'] = "PAGO"
                                st.session_state.pedidos.at[idx_original, 'Hora_Entrega'] = agora_brasil().time()

                                if salvar_pedidos(st.session_state.pedidos):
                                    registrar_alteracao("EDITAR", pedido['ID_Pedido'], "Status", status_antigo, "✅ Entregue")
                                    registrar_alteracao("EDITAR", pedido['ID_Pedido'], "Pagamento", pagamento_antigo, "PAGO")
                                    sincronizar_automaticamente('editar')
                                    del st.session_state[f"confirmar_entregue_{pedido['ID_Pedido']}"]
                                    st.toast(f"Pedido #{int(pedido['ID_Pedido'])} marcado como entregue e pago!", icon="✅")
                                    st.rerun()
                                else:
                                    st.error("Erro ao salvar alteração")
                        with col_nao_ent:
                            if st.button("❌ CANCELAR", key=f"nao_entregue_{pedido['ID_Pedido']}", use_container_width=True):
                                del st.session_state[f"confirmar_entregue_{pedido['ID_Pedido']}"]
                                st.rerun()

                    if st.session_state.get(f"visualizar_{pedido['ID_Pedido']}", False):
                        with st.expander("📋 Detalhes Completos", expanded=True):
                            col_det1, col_det2 = st.columns(2)
                            with col_det1:
                                # Mostrar hora de entrega se existir
                                hora_entrega = pedido.get('Hora_Entrega', None)
                                if hora_entrega and pd.notna(hora_entrega):
                                    hora_entrega_str = hora_entrega.strftime('%H:%M') if hasattr(hora_entrega, 'strftime') else str(hora_entrega)
                                    st.markdown(f"""
                                    **🆔 ID:** {int(pedido['ID_Pedido'])}
                                    **👤 Cliente:** {pedido['Cliente']}
                                    **📅 Data:** {pedido['Data'].strftime('%d/%m/%Y') if hasattr(pedido['Data'], 'strftime') else pedido['Data']}
                                    **⏰ Agendado:** {hora_str}
                                    **✅ Entregue às:** {hora_entrega_str}
                                    """)
                                else:
                                    st.markdown(f"""
                                    **🆔 ID:** {int(pedido['ID_Pedido'])}
                                    **👤 Cliente:** {pedido['Cliente']}
                                    **📅 Data:** {pedido['Data'].strftime('%d/%m/%Y') if hasattr(pedido['Data'], 'strftime') else pedido['Data']}
                                    **⏰ Hora:** {hora_str}
                                    """)
                                st.markdown(f"**Contato:** {get_whatsapp_link(pedido['Contato'])}", unsafe_allow_html=True)
                            with col_det2:
                                st.markdown(f"""
                                **🥘 Caruru:** {int(pedido['Caruru'])}
                                **🦐 Bobó:** {int(pedido['Bobo'])}
                                **💸 Desconto:** {pedido['Desconto']:.0f}%
                                **💰 Valor Total:** {formatar_valor_br(pedido['Valor'])}
                                **📊 Status:** {pedido['Status']}
                                **💳 Pagamento:** {pedido['Pagamento']}
                                """)
                            if pedido['Observacoes']:
                                st.markdown(f"**📝 Observações:**")
                                st.info(pedido['Observacoes'])

                            if st.button("✖️ Fechar", key=f"fechar_vis_{pedido['ID_Pedido']}", use_container_width=True):
                                st.session_state[f"visualizar_{pedido['ID_Pedido']}"] = False
                                st.rerun()

                    if st.session_state.get('pedido_em_edicao_dia_id') == int(pedido['ID_Pedido']):
                        with st.expander("✏️ Editar Pedido", expanded=True):
                            id_em_edicao_dia = st.session_state['pedido_em_edicao_dia_id']
                            pedido_atual = st.session_state.pedidos[st.session_state.pedidos['ID_Pedido'] == id_em_edicao_dia].iloc[0]

                            with st.form(f"form_edit_{id_em_edicao_dia}"):
                                edit_col1, edit_col2, edit_col3 = st.columns(3)
                                with edit_col1:
                                    novo_status = st.selectbox("📊 Status", OPCOES_STATUS,
                                                              index=OPCOES_STATUS.index(pedido_atual['Status']) if pedido_atual['Status'] in OPCOES_STATUS else 0,
                                                              key=f"status_{pedido['ID_Pedido']}")
                                with edit_col2:
                                    novo_pagamento = st.selectbox("💳 Pagamento", OPCOES_PAGAMENTO,
                                                                 index=OPCOES_PAGAMENTO.index(pedido_atual['Pagamento']) if pedido_atual['Pagamento'] in OPCOES_PAGAMENTO else 1,
                                                                 key=f"pag_{pedido['ID_Pedido']}")
                                with edit_col3:
                                    novo_desconto = st.number_input("💸 Desconto %", min_value=0, max_value=100, value=int(pedido_atual['Desconto']),
                                                                   key=f"desc_{pedido['ID_Pedido']}")

                                edit_col4, edit_col5 = st.columns(2)
                                with edit_col4:
                                    novo_caruru = st.number_input("🥘 Caruru", min_value=0, max_value=999, value=int(pedido_atual['Caruru']),
                                                                 key=f"car_{pedido['ID_Pedido']}")
                                with edit_col5:
                                    novo_bobo = st.number_input("🦐 Bobó", min_value=0, max_value=999, value=int(pedido_atual['Bobo']),
                                                               key=f"bob_{pedido['ID_Pedido']}")

                                novas_obs = st.text_area("📝 Observações", value=pedido_atual['Observacoes'], height=150,
                                                        key=f"obs_{pedido['ID_Pedido']}")

                                col_he1, col_he2 = st.columns(2)
                                with col_he1:
                                    alterar_hora_ent = st.checkbox(
                                        "⏱️ Alterar hora de entrega",
                                        key=f"alt_hora_ent_{pedido['ID_Pedido']}"
                                    )
                                    if alterar_hora_ent:
                                        hora_ent_atual = pedido_atual.get('Hora_Entrega', None)
                                        val_hora_ent = hora_ent_atual if isinstance(hora_ent_atual, time) else time(12, 0)
                                        nova_hora_ent = st.time_input(
                                            "✅ Hora Entrega",
                                            value=val_hora_ent,
                                            key=f"hora_ent_{pedido['ID_Pedido']}"
                                        )
                                    else:
                                        nova_hora_ent = None
                                with col_he2:
                                    novo_extra = st.checkbox(
                                        "⚡ Pedido Extra",
                                        value=bool(pedido_atual.get('Extra', False)),
                                        key=f"extra_edit_{pedido['ID_Pedido']}"
                                    )

                                col_save, col_cancel, col_delete = st.columns([2, 2, 1])
                                with col_save:
                                    salvar = st.form_submit_button("💾 Salvar", use_container_width=True, type="primary")
                                with col_cancel:
                                    cancelar = st.form_submit_button("❌ Cancelar", use_container_width=True)
                                with col_delete:
                                    excluir = st.form_submit_button("🗑️", use_container_width=True)

                                if salvar:
                                    if novo_caruru == 0 and novo_bobo == 0:
                                        st.error("❌ Pedido deve ter pelo menos 1 item")
                                    else:
                                        campos = {
                                            "Status": novo_status,
                                            "Pagamento": novo_pagamento,
                                            "Caruru": novo_caruru,
                                            "Bobo": novo_bobo,
                                            "Desconto": novo_desconto,
                                            "Observacoes": novas_obs,
                                            "Extra": novo_extra
                                        }
                                        if alterar_hora_ent:
                                            campos["Hora_Entrega"] = nova_hora_ent
                                        sucesso, msg = atualizar_pedido(id_em_edicao_dia, campos)
                                        if sucesso:
                                            st.toast(f"✅ Pedido #{id_em_edicao_dia} atualizado!", icon="✅")
                                            st.session_state['pedido_em_edicao_dia_id'] = None
                                            st.rerun()
                                        else:
                                            st.error(msg)

                                if cancelar:
                                    st.session_state['pedido_em_edicao_dia_id'] = None
                                    st.rerun()

                                if excluir:
                                    st.session_state[f"confirmar_exclusao_{id_em_edicao_dia}"] = True
                                    st.rerun()

                        if st.session_state.get(f"confirmar_exclusao_{pedido['ID_Pedido']}", False):
                            st.warning(f"⚠️ **ATENÇÃO:** Você tem certeza que deseja excluir o pedido #{int(pedido['ID_Pedido'])} de {pedido['Cliente']}?")
                            st.markdown("**Esta ação não pode ser desfeita!**")

                            col_conf_del1, col_conf_del2 = st.columns(2)

                            with col_conf_del1:
                                if st.button("✅ SIM, EXCLUIR", key=f"confirmar_sim_{pedido['ID_Pedido']}", use_container_width=True, type="primary"):
                                    id_para_excluir = int(pedido['ID_Pedido'])
                                    sucesso, msg = excluir_pedido(id_para_excluir, "Excluído via interface")
                                    if sucesso:
                                        keys_to_delete = [
                                            f"editando_{id_para_excluir}",
                                            f"visualizar_{id_para_excluir}",
                                            f"confirmar_exclusao_{id_para_excluir}",
                                            f"form_edit_{id_para_excluir}"
                                        ]
                                        for key in keys_to_delete:
                                            if key in st.session_state:
                                                del st.session_state[key]

                                        time_module.sleep(0.5)

                                        st.session_state.pedidos = carregar_pedidos()

                                        st.toast(f"🗑️ Pedido #{id_para_excluir} excluído com sucesso!", icon="✅")
                                        logger.info(f"✅ Pedido {id_para_excluir} excluído via Pedidos do Dia - Total restante: {len(st.session_state.pedidos)}")
                                        st.rerun()
                                    else:
                                        st.error(msg)
                                        logger.error(f"❌ Falha ao excluir pedido {id_para_excluir}: {msg}")
                                        del st.session_state[f"confirmar_exclusao_{id_para_excluir}"]
                                        st.rerun()

                            with col_conf_del2:
                                if st.button("❌ CANCELAR", key=f"confirmar_nao_{pedido['ID_Pedido']}", use_container_width=True):
                                    del st.session_state[f"confirmar_exclusao_{pedido['ID_Pedido']}"]
                                    st.rerun()

                    linha_num += 1
        else:
            st.info(f"Nenhum pedido para {dt_filter.strftime('%d/%m/%Y')}")
