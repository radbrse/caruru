"""Página de Gerenciamento de Todos os Pedidos."""

import streamlit as st
import pandas as pd
import os
import io
import zipfile
import urllib.parse
from datetime import time, timedelta
import time as time_module

from config import (
    logger, hoje_brasil, OPCOES_STATUS, OPCOES_PAGAMENTO,
    CHAVE_PIX, ARQUIVO_HISTORICO
)
from utils import (
    formatar_valor_br, get_status_badge, get_pagamento_badge,
    get_obs_icon, get_valor_destaque, get_whatsapp_link,
    calcular_total, gerar_link_whatsapp, limpar_telefone
)
from database import salvar_pedidos, carregar_pedidos, registrar_alteracao
from pedidos import sincronizar_dados_cliente
from sheets import sincronizar_automaticamente


def render():
    st.title("📦 Todos os Pedidos")

    df = st.session_state.pedidos

    if not df.empty:
        # Busca rápida por cliente
        st.markdown("### 🔍 Busca Rápida")
        busca_cliente = st.text_input(
            "Digite o nome do cliente para filtrar:",
            placeholder="Ex: João, Maria, etc...",
            help="A lista será filtrada conforme você digita",
            key="busca_cliente_todos"
        )

        st.divider()

        # Filtros e Ordenação
        with st.expander("🔍 Filtros e Ordenação", expanded=False):
            col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns(5)
            with col_f1:
                f_status = st.multiselect("Status", OPCOES_STATUS, default=OPCOES_STATUS)
            with col_f2:
                f_pagto = st.multiselect("Pagamento", OPCOES_PAGAMENTO, default=OPCOES_PAGAMENTO)
            with col_f3:
                f_periodo = st.selectbox("Período", ["Todos", "Hoje", "Esta Semana", "Este Mês", "Data Específica"], key="ger_periodo")
            with col_f4:
                # Filtro de data específica (só aparece se selecionado)
                if f_periodo == "Data Específica":
                    f_data_especifica = st.date_input("📅 Selecione a Data", value=hoje_brasil(), format="DD/MM/YYYY", key="ger_data_especifica")
                else:
                    f_data_especifica = None
            with col_f5:
                f_ordem = st.selectbox("Ordenar por", [
                    "📅 Data (mais recente)",
                    "📅 Data (mais antiga)",
                    "💵 Valor (maior)",
                    "💵 Valor (menor)",
                    "👤 Cliente (A-Z)",
                    "👤 Cliente (Z-A)",
                    "📊 Status",
                    "🆔 ID (maior)",
                    "🆔 ID (menor)"
                ], index=1, key="ger_ordem")

        # Aplica filtros
        df_view = df.copy()
        # Excluir pedidos entregues (aparecem apenas no Histórico)
        df_view = df_view[df_view['Status'] != "✅ Entregue"]
        df_view = df_view[df_view['Status'].isin(f_status)]
        df_view = df_view[df_view['Pagamento'].isin(f_pagto)]

        # Filtro de busca por cliente (case insensitive)
        if busca_cliente:
            df_view = df_view[df_view['Cliente'].str.contains(busca_cliente, case=False, na=False)]

        if f_periodo == "Hoje":
            df_view = df_view[df_view['Data'] == hoje_brasil()]
        elif f_periodo == "Esta Semana":
            inicio_semana = hoje_brasil() - timedelta(days=hoje_brasil().weekday())
            df_view = df_view[df_view['Data'] >= inicio_semana]
        elif f_periodo == "Este Mês":
            inicio_mes = hoje_brasil().replace(day=1)
            df_view = df_view[df_view['Data'] >= inicio_mes]
        elif f_periodo == "Data Específica" and f_data_especifica:
            df_view = df_view[df_view['Data'] == f_data_especifica]

        # Aplica ordenação escolhida
        try:
            if f_ordem == "📅 Data (mais recente)":
                df_view['sort_hora'] = df_view['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
                df_view = df_view.sort_values(['Data', 'sort_hora'], ascending=[False, True]).drop(columns=['sort_hora'])
            elif f_ordem == "📅 Data (mais antiga)":
                df_view['sort_hora'] = df_view['Hora'].apply(lambda x: x if isinstance(x, time) else time(0, 0))
                df_view = df_view.sort_values(['Data', 'sort_hora'], ascending=[True, True]).drop(columns=['sort_hora'])
            elif f_ordem == "💵 Valor (maior)":
                df_view = df_view.sort_values('Valor', ascending=False)
            elif f_ordem == "💵 Valor (menor)":
                df_view = df_view.sort_values('Valor', ascending=True)
            elif f_ordem == "👤 Cliente (A-Z)":
                df_view = df_view.sort_values('Cliente', ascending=True)
            elif f_ordem == "👤 Cliente (Z-A)":
                df_view = df_view.sort_values('Cliente', ascending=False)
            elif f_ordem == "📊 Status":
                df_view = df_view.sort_values('Status', ascending=True)
            elif f_ordem == "🆔 ID (maior)":
                df_view = df_view.sort_values('ID_Pedido', ascending=False)
            elif f_ordem == "🆔 ID (menor)":
                df_view = df_view.sort_values('ID_Pedido', ascending=True)
        except Exception as e:
            logger.warning(f"Erro ao ordenar: {e}")
            pass

        # Métricas com totais de caruru e bobó
        total_caruru = df_view['Caruru'].sum()
        total_bobo = df_view['Bobo'].sum()
        total_valor = df_view['Valor'].sum()

        # Exibe métricas em destaque
        st.divider()
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1:
            st.metric("📦 Pedidos", len(df_view))
        with col_m2:
            st.metric("🥘 Caruru", f"{int(total_caruru)} kg")
        with col_m3:
            st.metric("🦐 Bobó", f"{int(total_bobo)} kg")
        with col_m4:
            st.metric("💰 Total", formatar_valor_br(total_valor))
        st.divider()

        # Lista de pedidos com visualização e edição inline
        if df_view.empty:
            st.info("Nenhum pedido encontrado com os filtros aplicados.")
        else:
            # Lista de pedidos compacta com bordas sutis
            linha_num = 0
            for idx, pedido in df_view.iterrows():
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

                    col1, col2, col3, col4, col5, col6, col7, col8, col9 = st.columns([0.4, 1.5, 0.8, 0.7, 0.9, 0.9, 0.4, 0.3, 0.3])

                    with col1:
                        st.markdown(f"<div style='font-size:1.05rem; font-weight:700; color:#1f2937;'>#{int(pedido['ID_Pedido'])}</div>", unsafe_allow_html=True)
                    with col2:
                        st.markdown(f"<div style='font-size:0.9rem; font-weight:700; color:#374151;'>👤 {pedido['Cliente']}</div>", unsafe_allow_html=True)
                    with col3:
                        data_str = pedido['Data'].strftime('%d/%m/%Y') if hasattr(pedido['Data'], 'strftime') else str(pedido['Data'])
                        hora_str = pedido['Hora'].strftime('%H:%M') if hasattr(pedido['Hora'], 'strftime') else str(pedido['Hora'])
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
                        if st.button("👁️", key=f"ver_all_{pedido['ID_Pedido']}", help="Visualizar", use_container_width=True):
                            st.session_state[f"visualizar_all_{pedido['ID_Pedido']}"] = not st.session_state.get(f"visualizar_all_{pedido['ID_Pedido']}", False)
                            st.rerun()
                    with col9:
                        if st.button("✏️", key=f"edit_all_{pedido['ID_Pedido']}", help="Editar", use_container_width=True):
                            # NOVA ABORDAGEM: Usar uma única variável com o ID do pedido em edição
                            id_clicado = int(pedido['ID_Pedido'])
                            if st.session_state.get('pedido_em_edicao_id') == id_clicado:
                                # Se já está editando este pedido, fecha
                                st.session_state['pedido_em_edicao_id'] = None
                            else:
                                # Abre este pedido para edição
                                st.session_state['pedido_em_edicao_id'] = id_clicado
                            st.rerun()

                # Expander para visualização
                if st.session_state.get(f"visualizar_all_{pedido['ID_Pedido']}", False):
                    with st.expander("📋 Detalhes Completos", expanded=True):
                        col_a, col_b = st.columns(2)
                        with col_a:
                            st.markdown(f"**👤 Cliente:** {pedido['Cliente']}")
                            st.markdown(f"**Contato:** {get_whatsapp_link(pedido['Contato'])}", unsafe_allow_html=True)
                            st.markdown(f"**📅 Data Entrega:** {pedido['Data'].strftime('%d/%m/%Y') if hasattr(pedido['Data'], 'strftime') else pedido['Data']}")
                            st.markdown(f"**⏰ Hora Retirada:** {pedido['Hora'].strftime('%H:%M') if hasattr(pedido['Hora'], 'strftime') else pedido['Hora']}")
                        with col_b:
                            st.markdown(f"**🥘 Caruru:** {int(pedido['Caruru'])} un.")
                            st.markdown(f"**🦐 Bobó:** {int(pedido['Bobo'])} un.")
                            st.markdown(f"**💸 Desconto:** {int(pedido['Desconto'])}%")
                            st.markdown(f"**💵 Valor Total:** {formatar_valor_br(pedido['Valor'])}")

                        st.markdown("---")
                        col_c, col_d = st.columns(2)
                        with col_c:
                            st.markdown(f"**💳 Pagamento:** {pedido['Pagamento']}")
                        with col_d:
                            st.markdown(f"**📊 Status:** {pedido['Status']}")

                        if pedido['Observacoes']:
                            st.markdown("**📝 Observações:**")
                            st.info(pedido['Observacoes'])

                        if st.button("✖️ Fechar", key=f"fechar_vis_all_{pedido['ID_Pedido']}"):
                            st.session_state[f"visualizar_all_{pedido['ID_Pedido']}"] = False
                            st.rerun()

                # Expander para edição - NOVA ABORDAGEM com ID único
                if st.session_state.get('pedido_em_edicao_id') == int(pedido['ID_Pedido']):
                    with st.expander("✏️ Editar Pedido", expanded=True):
                        # Busca o pedido específico pelo ID armazenado (não pela variável do loop)
                        id_em_edicao = st.session_state['pedido_em_edicao_id']
                        pedido_atual = st.session_state.pedidos[st.session_state.pedidos['ID_Pedido'] == id_em_edicao].iloc[0]

                        with st.form(f"form_edit_all_{id_em_edicao}"):
                            st.markdown("### 📝 Dados do Pedido")

                            # Cliente e contato
                            col_e1, col_e2 = st.columns(2)
                            with col_e1:
                                clientes_lista = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
                                try:
                                    idx_cliente = clientes_lista.index(pedido_atual['Cliente']) if pedido_atual['Cliente'] in clientes_lista else 0
                                except:
                                    idx_cliente = 0
                                novo_cliente = st.selectbox("👤 Cliente", clientes_lista, index=idx_cliente)
                            with col_e2:
                                novo_contato = st.text_input("📱 Contato", value=str(pedido_atual['Contato']))

                            # Data e hora
                            col_e3, col_e4 = st.columns(2)
                            with col_e3:
                                nova_data = st.date_input("📅 Data Entrega", value=pedido_atual['Data'], format="DD/MM/YYYY")
                            with col_e4:
                                nova_hora = st.time_input("⏰ Hora Retirada", value=pedido_atual['Hora'])

                            # Quantidades
                            col_e5, col_e6, col_e7 = st.columns(3)
                            with col_e5:
                                novo_caruru = st.number_input("🥘 Caruru", min_value=0, max_value=999, value=int(pedido_atual['Caruru']))
                            with col_e6:
                                novo_bobo = st.number_input("🦐 Bobó", min_value=0, max_value=999, value=int(pedido_atual['Bobo']))
                            with col_e7:
                                novo_desconto = st.number_input("💸 Desconto %", min_value=0, max_value=100, value=int(pedido_atual['Desconto']))

                            # Pagamento e status
                            col_e8, col_e9 = st.columns(2)
                            with col_e8:
                                novo_pagamento = st.selectbox("💳 Pagamento", OPCOES_PAGAMENTO, index=OPCOES_PAGAMENTO.index(pedido_atual['Pagamento']) if pedido_atual['Pagamento'] in OPCOES_PAGAMENTO else 0)
                            with col_e9:
                                novo_status = st.selectbox("📊 Status", OPCOES_STATUS, index=OPCOES_STATUS.index(pedido_atual['Status']) if pedido_atual['Status'] in OPCOES_STATUS else 0)

                            # Observações com mais espaço
                            novas_obs = st.text_area("📝 Observações", value=str(pedido_atual['Observacoes']) if pd.notna(pedido_atual['Observacoes']) else "", height=150)

                            # Botões
                            col_e10, col_e11, col_e12 = st.columns([2, 2, 1])
                            with col_e10:
                                salvar = st.form_submit_button("💾 Salvar Alterações", use_container_width=True, type="primary")
                            with col_e11:
                                cancelar = st.form_submit_button("↩️ Cancelar", use_container_width=True)
                            with col_e12:
                                st.markdown("")  # Espaço

                            # Botão de exclusão
                            excluir = st.form_submit_button("🗑️ Excluir Pedido", use_container_width=True, type="secondary")

                            if salvar:
                                # Captura dados antigos ANTES de atualizar (para sincronização)
                                pedido_antigo = st.session_state.pedidos[st.session_state.pedidos['ID_Pedido'] == id_em_edicao].iloc[0]
                                cliente_antigo = pedido_antigo['Cliente']
                                contato_antigo = pedido_antigo['Contato']

                                # Atualiza o pedido usando o ID correto
                                novo_valor = calcular_total(novo_caruru, novo_bobo, novo_desconto)
                                df_atualizado = st.session_state.pedidos.copy()
                                mask = df_atualizado['ID_Pedido'] == id_em_edicao

                                df_atualizado.loc[mask, 'Cliente'] = novo_cliente
                                df_atualizado.loc[mask, 'Contato'] = novo_contato
                                df_atualizado.loc[mask, 'Data'] = nova_data
                                df_atualizado.loc[mask, 'Hora'] = nova_hora
                                df_atualizado.loc[mask, 'Caruru'] = novo_caruru
                                df_atualizado.loc[mask, 'Bobo'] = novo_bobo
                                df_atualizado.loc[mask, 'Desconto'] = novo_desconto
                                df_atualizado.loc[mask, 'Valor'] = novo_valor
                                df_atualizado.loc[mask, 'Pagamento'] = novo_pagamento
                                df_atualizado.loc[mask, 'Status'] = novo_status
                                df_atualizado.loc[mask, 'Observacoes'] = novas_obs

                                # Capturar hora de entrega se marcou como Entregue
                                if novo_status == "✅ Entregue" and pedido_atual['Status'] != "✅ Entregue":
                                    from config import agora_brasil
                                    df_atualizado.loc[mask, 'Hora_Entrega'] = agora_brasil().time()

                                if salvar_pedidos(df_atualizado):
                                    # Recarrega do arquivo para garantir sincronização entre abas
                                    st.session_state.pedidos = carregar_pedidos()

                                    # SINCRONIZAÇÃO AUTOMÁTICA COM GOOGLE SHEETS
                                    # IMPORTANTE: Sincroniza SEMPRE que houver edição, independente do campo alterado
                                    sincronizar_automaticamente(operacao="editar")
                                    logger.info(f"🔄 Sincronização automática disparada após edição do pedido #{id_em_edicao}")

                                    # SINCRONIZAÇÃO AUTOMÁTICA DE DADOS DO CLIENTE
                                    # Se nome ou contato mudaram, sincroniza com banco de clientes
                                    cliente_mudou = str(novo_cliente).strip() != str(cliente_antigo).strip()
                                    contato_mudou = str(novo_contato).strip() != str(contato_antigo).strip()

                                    if cliente_mudou or contato_mudou:
                                        logger.info(f"🔍 Detectada mudança - Cliente: {cliente_mudou} ('{cliente_antigo}' → '{novo_cliente}'), Contato: {contato_mudou} ('{contato_antigo}' → '{novo_contato}')")

                                        sucesso_sync, msg_sync, tipo_op = sincronizar_dados_cliente(
                                            nome_cliente=novo_cliente,
                                            contato=novo_contato,
                                            nome_cliente_antigo=cliente_antigo if cliente_mudou else None,
                                            observacoes=""
                                        )

                                        logger.info(f"📊 Resultado sincronização - Sucesso: {sucesso_sync}, Tipo: {tipo_op}, Msg: {msg_sync}")

                                        if sucesso_sync and tipo_op != "sem_alteracao":
                                            st.toast(f"🔄 {msg_sync}", icon="🔄")
                                            logger.info(f"🔄 Sincronização automática: {msg_sync}")

                                    st.session_state['pedido_em_edicao_id'] = None  # Fecha edição
                                    st.toast(f"✅ Pedido #{id_em_edicao} atualizado!", icon="✅")
                                    logger.info(f"Pedido {id_em_edicao} editado via Gerenciar Tudo")
                                    time_module.sleep(0.5)
                                    st.rerun()
                                else:
                                    st.error("❌ Erro ao salvar as alterações.")

                            if cancelar:
                                st.session_state['pedido_em_edicao_id'] = None  # Fecha edição
                                st.rerun()

                            if excluir:
                                # Define flag para mostrar confirmação FORA do form
                                st.session_state[f"confirmar_exclusao_all_{id_em_edicao}"] = True
                                st.rerun()

                    # Confirmação de exclusão - FORA do form
                    if st.session_state.get(f"confirmar_exclusao_all_{pedido['ID_Pedido']}", False):
                        st.warning(f"⚠️ **ATENÇÃO:** Você tem certeza que deseja excluir o pedido #{int(pedido['ID_Pedido'])} de {pedido['Cliente']}?")
                        st.markdown("**Esta ação não pode ser desfeita!**")

                        col_conf_del_all1, col_conf_del_all2 = st.columns(2)

                        with col_conf_del_all1:
                            if st.button("✅ SIM, EXCLUIR", key=f"confirmar_sim_all_{pedido['ID_Pedido']}", use_container_width=True, type="primary"):
                                id_para_excluir = int(pedido['ID_Pedido'])
                                df_atualizado = st.session_state.pedidos[st.session_state.pedidos['ID_Pedido'] != id_para_excluir].reset_index(drop=True)
                                if salvar_pedidos(df_atualizado):
                                    # Limpa TODOS os estados relacionados ao pedido
                                    keys_to_delete = [
                                        f"editando_all_{id_para_excluir}",
                                        f"visualizar_all_{id_para_excluir}",
                                        f"confirmar_exclusao_all_{id_para_excluir}",
                                        f"form_edit_all_{id_para_excluir}"
                                    ]
                                    for key in keys_to_delete:
                                        if key in st.session_state:
                                            del st.session_state[key]

                                    # Força delay para sync de arquivo
                                    time_module.sleep(0.5)

                                    # Recarrega dados do arquivo
                                    st.session_state.pedidos = carregar_pedidos()

                                    # SINCRONIZAÇÃO AUTOMÁTICA COM GOOGLE SHEETS
                                    sincronizar_automaticamente(operacao="excluir")
                                    logger.info(f"🔄 Sincronização automática disparada após exclusão do pedido #{id_para_excluir}")

                                    st.toast(f"🗑️ Pedido #{id_para_excluir} excluído com sucesso!", icon="✅")
                                    logger.info(f"✅ Pedido {id_para_excluir} excluído via Gerenciar Tudo - Total restante: {len(st.session_state.pedidos)}")
                                    st.rerun()
                                else:
                                    st.error("❌ Erro ao excluir o pedido.")
                                    # Remove flag de confirmação
                                    del st.session_state[f"confirmar_exclusao_all_{id_para_excluir}"]
                                    st.rerun()

                        with col_conf_del_all2:
                            if st.button("❌ CANCELAR", key=f"confirmar_nao_all_{pedido['ID_Pedido']}", use_container_width=True):
                                # Remove flag de confirmação
                                del st.session_state[f"confirmar_exclusao_all_{pedido['ID_Pedido']}"]
                                st.rerun()

                # Incrementa contador para zebra stripes
                linha_num += 1

        st.divider()

        # WhatsApp rápido
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("💬 WhatsApp Rápido")
            if not df_view.empty:
                sel_cli = st.selectbox("Cliente:", sorted(df_view['Cliente'].unique()), key="zap_cli")
                if sel_cli:
                    d = df_view[df_view['Cliente'] == sel_cli].iloc[-1]
                    msg = f"Olá {sel_cli}! 🦐\n\nSeu pedido:\n"
                    if d['Caruru'] > 0:
                        msg += f"• {int(d['Caruru'])}x Caruru\n"
                    if d['Bobo'] > 0:
                        msg += f"• {int(d['Bobo'])}x Bobó\n"
                    msg += f"\n💵 Total: {formatar_valor_br(d['Valor'])}"
                    if d['Pagamento'] in ["NÃO PAGO", "METADE"]:
                        msg += f"\n\n📲 Pix: {CHAVE_PIX}"

                    link = gerar_link_whatsapp(d['Contato'], msg)
                    if link:
                        st.link_button("📱 Enviar WhatsApp", link, use_container_width=True)
                    else:
                        st.warning("Contato inválido ou não cadastrado.")
    else:
        st.info("Nenhum pedido cadastrado.")

    st.divider()

    # Backup
    with st.expander("💾 Backup & Restauração"):
        st.write("### 📥 Fazer Backup")
        try:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "a", zipfile.ZIP_DEFLATED, False) as z:
                z.writestr("pedidos.csv", st.session_state.pedidos.to_csv(index=False))
                z.writestr("clientes.csv", st.session_state.clientes.to_csv(index=False))
                if os.path.exists(ARQUIVO_HISTORICO):
                    with open(ARQUIVO_HISTORICO, 'r') as f:
                        z.writestr("historico.csv", f.read())
            st.download_button(
                "📥 Baixar Backup Completo (ZIP)",
                buf.getvalue(),
                f"backup_caruru_{hoje_brasil()}.zip",
                "application/zip"
            )
        except Exception as e:
            st.error(f"Erro backup: {e}")

        st.write("### 📤 Restaurar Pedidos")
        up = st.file_uploader("Arquivo Pedidos (CSV)", type="csv", key="rest_ped")
        if up and st.button("⚠️ Restaurar Pedidos"):
            try:
                df_n = pd.read_csv(up)

                # Valida schema
                colunas_obrigatorias = ["ID_Pedido", "Cliente", "Caruru", "Bobo", "Valor", "Data", "Hora", "Status", "Pagamento", "Contato", "Desconto", "Observacoes"]
                colunas_faltantes = set(colunas_obrigatorias) - set(df_n.columns.tolist())
                if colunas_faltantes:
                    st.error(f"❌ CSV inválido! Colunas obrigatórias faltando: {', '.join(sorted(colunas_faltantes))}")
                else:
                    # Adiciona Hora_Entrega se não existir (retrocompatibilidade)
                    if 'Hora_Entrega' not in df_n.columns:
                        df_n['Hora_Entrega'] = ""

                    # Reordena para manter colunas esperadas
                    todas_colunas = colunas_obrigatorias + ["Hora_Entrega"]
                    df_n = df_n[[c for c in todas_colunas if c in df_n.columns]]

                    if not salvar_pedidos(df_n):
                        st.error("❌ ERRO: Não foi possível restaurar os pedidos. Tente novamente.")
                    else:
                        st.session_state.pedidos = carregar_pedidos()
                        st.toast("Backup restaurado!", icon="✅")
                        st.rerun()
            except Exception as e:
                st.error(f"Erro: {e}")
