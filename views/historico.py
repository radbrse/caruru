import streamlit as st
import pandas as pd
from datetime import time

from config import logger
from database import salvar_pedidos, carregar_pedidos, registrar_alteracao
from sheets import sincronizar_automaticamente
from utils import (
    formatar_valor_br,
    get_valor_destaque,
    get_status_badge,
    get_pagamento_badge,
    get_obs_icon,
    get_extra_badge,
    get_vegano_badge,
    get_delivery_badge,
    get_whatsapp_link,
    safe_html,
)


def render():
    st.title("📜 Histórico de Pedidos Entregues")

    df = st.session_state.pedidos

    # Filtrar apenas pedidos entregues
    df_entregues = df[df['Status'] == "✅ Entregue"].copy()

    if df_entregues.empty:
        st.info("📭 Nenhum pedido entregue ainda.")
    else:
        # ── Linha 1: tipo + ordenação ─────────────────────────────────────────
        col_ord1, col_ord2 = st.columns([3, 1])
        with col_ord1:
            tipo_filtro = st.radio(
                "📦 Tipo de Pedido",
                ["Todos", "⚡ Extra", "📦 Convencional"],
                horizontal=True,
                key="filtro_tipo_historico"
            )

        if 'Extra' in df_entregues.columns:
            if tipo_filtro == "⚡ Extra":
                df_entregues = df_entregues[df_entregues['Extra'] == True]
            elif tipo_filtro == "📦 Convencional":
                df_entregues = df_entregues[df_entregues['Extra'] != True]

        with col_ord2:
            ordem_hist = st.selectbox("Ordenar por", [
                "📅 Data (mais recente)",
                "📅 Data (mais antiga)",
                "💵 Valor (maior)",
                "💵 Valor (menor)",
                "👤 Cliente (A-Z)",
                "👤 Cliente (Z-A)",
                "🆔 ID (maior)",
                "🆔 ID (menor)"
            ], index=0, key="ordem_historico")

        # ── Linha 2: filtro de data ───────────────────────────────────────────
        datas_validas = df_entregues['Data'].dropna()
        _min_d = datas_validas.min() if not datas_validas.empty else None
        _max_d = datas_validas.max() if not datas_validas.empty else None

        col_f1, col_f2, col_f3 = st.columns([1, 1, 1])
        with col_f1:
            data_de = st.date_input(
                "📅 De",
                value=_min_d,
                key="hist_data_de",
                format="DD/MM/YYYY",
                help="Exibe pedidos entregues a partir desta data"
            )
        with col_f2:
            data_ate = st.date_input(
                "📅 Até",
                value=_max_d,
                key="hist_data_ate",
                format="DD/MM/YYYY",
                help="Exibe pedidos entregues até esta data"
            )
        with col_f3:
            st.markdown("<div style='padding-top:28px'>", unsafe_allow_html=True)
            if st.button("🔄 Todos os dias", key="hist_limpar_data", use_container_width=True,
                         help="Remove o filtro de data e mostra todo o histórico"):
                st.session_state.pop('hist_data_de', None)
                st.session_state.pop('hist_data_ate', None)
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

        # Aplica filtro de data (comparação type-safe via strftime)
        if data_de is not None and data_ate is not None:
            _de_str  = data_de.strftime('%Y-%m-%d')
            _ate_str = data_ate.strftime('%Y-%m-%d')

            def _data_no_intervalo(x):
                try:
                    if pd.isna(x):
                        return False
                except (TypeError, ValueError):
                    pass
                s = x.strftime('%Y-%m-%d') if hasattr(x, 'strftime') else str(x)[:10]
                return _de_str <= s <= _ate_str

            df_entregues = df_entregues[df_entregues['Data'].apply(_data_no_intervalo)]

        # ── Ordenação ─────────────────────────────────────────────────────────
        try:
            if ordem_hist == "📅 Data (mais recente)":
                df_entregues['sort_hora'] = df_entregues['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
                df_entregues = df_entregues.sort_values(['Data', 'sort_hora'], ascending=[False, True]).drop(columns=['sort_hora'])
            elif ordem_hist == "📅 Data (mais antiga)":
                df_entregues['sort_hora'] = df_entregues['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
                df_entregues = df_entregues.sort_values(['Data', 'sort_hora'], ascending=[True, True]).drop(columns=['sort_hora'])
            elif ordem_hist == "💵 Valor (maior)":
                df_entregues = df_entregues.sort_values('Valor', ascending=False)
            elif ordem_hist == "💵 Valor (menor)":
                df_entregues = df_entregues.sort_values('Valor', ascending=True)
            elif ordem_hist == "👤 Cliente (A-Z)":
                df_entregues = df_entregues.sort_values('Cliente', ascending=True)
            elif ordem_hist == "👤 Cliente (Z-A)":
                df_entregues = df_entregues.sort_values('Cliente', ascending=False)
            elif ordem_hist == "🆔 ID (maior)":
                df_entregues = df_entregues.sort_values('ID_Pedido', ascending=False)
            elif ordem_hist == "🆔 ID (menor)":
                df_entregues = df_entregues.sort_values('ID_Pedido', ascending=True)
        except Exception as e:
            logger.warning(f"Erro ao ordenar histórico: {e}")

        # IDs visíveis (após filtros + ordenação) — usados pelos callbacks de seleção
        ids_entregues = df_entregues['ID_Pedido'].tolist()

        def _sel_todos():
            for id_ in ids_entregues:
                st.session_state[f"sel_hist_{id_}"] = True

        def _limpar_sel():
            for id_ in ids_entregues:
                st.session_state[f"sel_hist_{id_}"] = False

        # ── Métricas (refletem filtro de data + tipo) ─────────────────────────
        st.markdown("### 📊 Resumo")
        col_m1, col_m2, col_m3, col_m4, col_m5, col_m6, col_m7 = st.columns([1, 1, 1, 1.6, 1, 1, 1.4])
        with col_m1:
            st.metric("📦 Entregas", len(df_entregues))
        with col_m2:
            st.metric("🥘 Caruru", int(df_entregues['Caruru'].sum()))
        with col_m3:
            st.metric("🦐 Bobó", int(df_entregues['Bobo'].sum()))
        with col_m4:
            valor_total = df_entregues['Valor'].sum()
            st.metric("💰 Total (R$)", formatar_valor_br(valor_total).replace("R$ ", ""))
        with col_m5:
            df_pagos = df_entregues[df_entregues['Pagamento'] == "PAGO"]
            st.metric("✅ Pagos", len(df_pagos))
        with col_m6:
            n_extras = int(df_entregues['Extra'].sum()) if 'Extra' in df_entregues.columns else 0
            st.metric("⚡ Extras", n_extras)
        with col_m7:
            if st.button("🗑️ Limpar Histórico", type="secondary", use_container_width=True):
                st.session_state['confirmar_limpar_historico'] = True
                st.rerun()

        # ── Barra de seleção ──────────────────────────────────────────────────
        selecionados = [id_ for id_ in ids_entregues if st.session_state.get(f"sel_hist_{id_}", False)]
        col_s1, col_s2, col_s3 = st.columns([1, 1, 3])
        with col_s1:
            st.button("☑️ Selecionar todos", key="btn_sel_todos_hist", on_click=_sel_todos, use_container_width=True)
        with col_s2:
            st.button("⬜ Limpar seleção", key="btn_limpar_sel_hist", on_click=_limpar_sel, use_container_width=True)
        with col_s3:
            if selecionados:
                if st.button(f"🗑️ Deletar {len(selecionados)} selecionado(s)", type="primary", key="btn_del_sel_hist", use_container_width=True):
                    st.session_state['confirmar_deletar_selecionados'] = True
                    st.rerun()
            else:
                # Quantidade de KG vendidos no período filtrado (Caruru + Bobó)
                kg_caruru = int(df_entregues['Caruru'].sum())
                kg_bobo = int(df_entregues['Bobo'].sum())
                kg_total = kg_caruru + kg_bobo
                st.markdown(
                    f"""<div style='padding:8px 14px; background:#fff7ed; border:1px solid #fdba74;
                    border-radius:10px; text-align:center; line-height:1.3;'>
                    <span style='font-size:0.8rem; color:#9a3412; font-weight:600;'>⚖️ KG vendidos</span><br>
                    <span style='font-size:1.15rem; color:#c2410c; font-weight:800;'>{kg_total} kg</span>
                    <span style='font-size:0.8rem; color:#9a3412;'>&nbsp;(🥘 {kg_caruru} · 🦐 {kg_bobo})</span>
                    </div>""",
                    unsafe_allow_html=True
                )

        # Confirmação de exclusão seletiva
        if st.session_state.get('confirmar_deletar_selecionados', False) and selecionados:
            st.warning(f"⚠️ Excluir permanentemente {len(selecionados)} pedido(s) entregue(s)?")
            st.error("⚠️ ESTA AÇÃO É IRREVERSÍVEL!")
            col_ds1, col_ds2 = st.columns(2)
            with col_ds1:
                if st.button("✅ Sim, excluir selecionados", key="confirmar_del_sel_hist", type="primary", use_container_width=True):
                    try:
                        df_atual = st.session_state.pedidos
                        df_atual = df_atual[~df_atual['ID_Pedido'].isin(selecionados)]
                        if not salvar_pedidos(df_atual):
                            st.error("❌ ERRO: Não foi possível excluir. Tente novamente.")
                        else:
                            st.session_state.pedidos = carregar_pedidos()
                            registrar_alteracao("DELETAR_SELETIVO", 0, "Historico", f"{len(selecionados)} pedidos", "excluídos")
                            sincronizar_automaticamente(operacao="excluir")
                            logger.info(f"🗑️ Deleção seletiva: {len(selecionados)} pedidos removidos")
                            _limpar_sel()
                        st.session_state['confirmar_deletar_selecionados'] = False
                        st.toast(f"🗑️ {len(selecionados)} pedido(s) excluído(s)!", icon="🗑️")
                        st.rerun()
                    except Exception as e:
                        logger.error(f"Erro na deleção seletiva: {e}", exc_info=True)
                        st.error(f"❌ Erro: {e}")
            with col_ds2:
                if st.button("❌ Cancelar", key="cancelar_del_sel_hist", use_container_width=True):
                    st.session_state['confirmar_deletar_selecionados'] = False
                    st.rerun()

        # Confirmação de limpeza de histórico
        if st.session_state.get('confirmar_limpar_historico', False):
            with st.container():
                st.warning("⚠️ Tem certeza que deseja limpar TODO o histórico de pedidos entregues?")
                st.error("⚠️ ESTA AÇÃO É IRREVERSÍVEL! Todos os pedidos entregues serão PERMANENTEMENTE EXCLUÍDOS.")

                col_limpar1, col_limpar2 = st.columns(2)
                with col_limpar1:
                    if st.button("✅ Sim, Limpar Tudo", key="confirmar_limpar_hist", type="primary", use_container_width=True):
                        try:
                            df_atual = st.session_state.pedidos
                            qtd_removidos = len(df_atual[df_atual['Status'] == "✅ Entregue"])

                            df_atual = df_atual[df_atual['Status'] != "✅ Entregue"]

                            if not salvar_pedidos(df_atual):
                                st.error("❌ ERRO: Não foi possível limpar o histórico. Tente novamente.")
                                st.session_state['confirmar_limpar_historico'] = False
                            else:
                                st.session_state.pedidos = carregar_pedidos()
                                registrar_alteracao("LIMPAR_HISTORICO", 0, "Historico", f"{qtd_removidos} pedidos", "0 pedidos")
                                sincronizar_automaticamente(operacao="excluir")
                                logger.info(f"🗑️ Histórico limpo: {qtd_removidos} pedidos removidos e sincronizados com Sheets")
                                st.session_state['confirmar_limpar_historico'] = False
                                st.toast("🗑️ Histórico limpo com sucesso!", icon="🗑️")
                                st.rerun()
                        except Exception as e:
                            logger.error(f"Erro ao limpar histórico: {e}", exc_info=True)
                            st.error(f"❌ Erro ao limpar histórico: {e}")
                with col_limpar2:
                    if st.button("❌ Cancelar", key="cancelar_limpar_hist", use_container_width=True):
                        st.session_state['confirmar_limpar_historico'] = False
                        st.rerun()

        st.divider()
        st.subheader("📋 Pedidos Entregues")

        # Lista de pedidos entregues
        linha_num = 0
        for idx, pedido in df_entregues.iterrows():
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

                col0, col1, col2, col3, col4, col5, col6, col7, col8, col9 = st.columns([0.25, 0.4, 1.5, 0.8, 0.7, 0.9, 0.9, 0.4, 0.4, 0.4])

                with col0:
                    st.checkbox("", key=f"sel_hist_{pedido['ID_Pedido']}", label_visibility="collapsed")
                with col1:
                    st.markdown(f"<div style='font-size:1.05rem; font-weight:700; color:#1f2937;'>#{int(pedido['ID_Pedido'])}</div>", unsafe_allow_html=True)
                with col2:
                    extra_tag = f" {get_extra_badge(pedido.get('Extra', False))}" if pedido.get('Extra', False) else ""
                    vegano_tag = f" {get_vegano_badge(pedido.get('Vegano', False))}" if pedido.get('Vegano', False) else ""
                    delivery_tag = f" {get_delivery_badge(pedido.get('Delivery', False))}" if pedido.get('Delivery', False) else ""
                    st.markdown(f"<div style='font-size:0.9rem; font-weight:700; color:#374151;'>👤 {safe_html(pedido['Cliente'])}{extra_tag}{vegano_tag}{delivery_tag}</div>", unsafe_allow_html=True)
                with col3:
                    data_str = pedido['Data'].strftime('%d/%m/%Y') if (hasattr(pedido['Data'], 'strftime') and pd.notna(pedido['Data'])) else str(pedido['Data'])
                    hora_str = pedido['Hora'].strftime('%H:%M') if (hasattr(pedido['Hora'], 'strftime') and pd.notna(pedido['Hora'])) else str(pedido['Hora'])

                    hora_entrega = pedido.get('Hora_Entrega', None)
                    if hora_entrega and pd.notna(hora_entrega):
                        hora_entrega_str = hora_entrega.strftime('%H:%M') if hasattr(hora_entrega, 'strftime') else str(hora_entrega)
                        st.markdown(f"<div style='font-size:0.9rem; font-weight:700; color:#374151;'>📅 {data_str}<br>⏰ {hora_str}<br>✅ {hora_entrega_str}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div style='font-size:0.9rem; font-weight:700; color:#374151;'>📅 {data_str}<br>⏰ {hora_str}</div>", unsafe_allow_html=True)
                with col4:
                    st.markdown(get_valor_destaque(pedido['Valor']), unsafe_allow_html=True)
                with col5:
                    st.markdown(get_status_badge(pedido['Status']), unsafe_allow_html=True)
                with col6:
                    st.markdown(get_pagamento_badge(pedido['Pagamento']), unsafe_allow_html=True)
                with col7:
                    st.markdown(get_obs_icon(pedido['Observacoes']), unsafe_allow_html=True)
                with col8:
                    if st.button("👁️", key=f"ver_hist_{pedido['ID_Pedido']}", help="Visualizar", use_container_width=True):
                        st.session_state[f"visualizar_hist_{pedido['ID_Pedido']}"] = not st.session_state.get(f"visualizar_hist_{pedido['ID_Pedido']}", False)
                        st.rerun()
                with col9:
                    if st.button("↩️", key=f"reverter_hist_{pedido['ID_Pedido']}", help="Reverter para Pendente", use_container_width=True):
                        st.session_state[f"confirmar_reverter_{pedido['ID_Pedido']}"] = True
                        st.rerun()

            # Visualização detalhada
            if st.session_state.get(f"visualizar_hist_{pedido['ID_Pedido']}", False):
                with st.expander("📋 Detalhes Completos", expanded=True):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        st.markdown(f"**👤 Cliente:** {pedido['Cliente']}")
                        st.markdown(f"**Contato:** {get_whatsapp_link(pedido['Contato'])}", unsafe_allow_html=True)
                        st.markdown(f"**📅 Data:** {data_str}")
                        st.markdown(f"**⏰ Agendado:** {hora_str}")

                        hora_entrega = pedido.get('Hora_Entrega', None)
                        if hora_entrega and pd.notna(hora_entrega):
                            hora_entrega_str = hora_entrega.strftime('%H:%M') if hasattr(hora_entrega, 'strftime') else str(hora_entrega)
                            st.markdown(f"**✅ Entregue às:** {hora_entrega_str}")
                    with col_b:
                        st.markdown(f"**🥘 Caruru:** {int(pedido['Caruru'])} potes")
                        st.markdown(f"**🦐 Bobó:** {int(pedido['Bobo'])} potes")
                        st.markdown(f"**💰 Valor:** {formatar_valor_br(pedido['Valor'])}")
                        if pedido.get('Desconto', 0) > 0:
                            st.markdown(f"**💸 Desconto:** {pedido['Desconto']}%")
                        _ent_h = float(pedido.get('Entrada', 0.0) or 0.0)
                        if _ent_h > 0:
                            _falta_h = max(0.0, float(pedido['Valor']) - _ent_h)
                            st.markdown(f"**💵 Entrada:** {formatar_valor_br(_ent_h)}")
                            if _falta_h > 0:
                                st.markdown(f"**📥 Falta receber:** {formatar_valor_br(_falta_h)}")
                    st.markdown(f"**📊 Status:** {pedido['Status']}")
                    st.markdown(f"**💳 Pagamento:** {pedido['Pagamento']}")
                    if pedido.get('Observacoes'):
                        st.markdown(f"**📝 Observações:**\n{pedido['Observacoes']}")

            # Confirmação de reversão
            if st.session_state.get(f"confirmar_reverter_{pedido['ID_Pedido']}", False):
                st.warning(f"⚠️ Reverter pedido #{int(pedido['ID_Pedido'])} de {pedido['Cliente']}?")
                st.info("O pedido será marcado como '🔴 Pendente' e voltará para as abas principais.")

                col_conf1, col_conf2 = st.columns(2)
                with col_conf1:
                    if st.button("✅ Sim, Reverter", key=f"sim_reverter_{pedido['ID_Pedido']}", use_container_width=True, type="primary"):
                        try:
                            df_atual = st.session_state.pedidos
                            df_atual['Status'] = df_atual['Status'].astype(object)
                            df_atual.loc[df_atual['ID_Pedido'] == pedido['ID_Pedido'], 'Status'] = "🔴 Pendente"

                            if not salvar_pedidos(df_atual):
                                st.error("❌ ERRO: Não foi possível reverter o pedido. Tente novamente.")
                                st.session_state[f"confirmar_reverter_{pedido['ID_Pedido']}"] = False
                            else:
                                st.session_state.pedidos = carregar_pedidos()
                                st.session_state[f"confirmar_reverter_{pedido['ID_Pedido']}"] = False
                                st.toast(f"↩️ Pedido #{int(pedido['ID_Pedido'])} revertido para Pendente!", icon="↩️")
                                st.rerun()
                        except Exception as e:
                            st.error(f"❌ Erro ao reverter: {e}")
                with col_conf2:
                    if st.button("❌ Cancelar", key=f"nao_reverter_{pedido['ID_Pedido']}", use_container_width=True):
                        st.session_state[f"confirmar_reverter_{pedido['ID_Pedido']}"] = False
                        st.rerun()

            linha_num += 1
