import streamlit as st
import pandas as pd

from config import logger
from utils import limpar_telefone, formatar_valor_br, validar_telefone, safe_html
from database import salvar_clientes, carregar_clientes, salvar_pedidos, carregar_pedidos, registrar_alteracao
from pedidos import sincronizar_dados_cliente, sincronizar_contatos_pedidos
from pdf import gerar_lista_clientes_pdf
from sheets import sincronizar_automaticamente


# ==============================================================================
# OPERAÇÕES RESILIENTES (mesma lógica que as antigas abas Lista/Excluir)
# ==============================================================================
def _salvar_edicao_cliente(nome_antigo, nome_novo, contato_novo, obs_nova):
    """Edita um cliente propagando renome/telefone para os pedidos, com rollback.

    Se a propagação para os pedidos falhar, NADA é salvo (recarrega os pedidos
    do disco) — evita estado inconsistente (cliente novo, pedidos com dado antigo).
    Retorna (sucesso: bool, mensagens: list[(tipo, texto)]).
    """
    nome_antigo = str(nome_antigo).strip()
    nome_novo = (nome_novo or "").strip()
    contato_novo = limpar_telefone(contato_novo)
    obs_nova = (obs_nova or "").strip()

    if not nome_novo:
        return False, [("error", "❌ Nome é obrigatório.")]

    df_cli = st.session_state.clientes.copy()
    mask_cli = df_cli['Nome'].astype(str).str.strip() == nome_antigo
    if not mask_cli.any():
        return False, [("error", f"❌ Cliente '{nome_antigo}' não encontrado.")]

    # Bloqueia renomear para um nome que já existe em OUTRO cliente
    if nome_novo.lower() != nome_antigo.lower():
        outros = df_cli[~mask_cli]['Nome'].astype(str).str.strip().str.lower().tolist()
        if nome_novo.lower() in outros:
            return False, [("warning", f"⚠️ Já existe um cliente chamado '{nome_novo}'.")]

    idx = df_cli[mask_cli].index[0]
    contato_antigo = limpar_telefone(df_cli.loc[idx, 'Contato'])

    msgs = []
    falha = False

    # Propaga renome para os pedidos existentes
    if nome_novo != nome_antigo:
        mask_nome = st.session_state.pedidos['Cliente'] == nome_antigo
        qtd = int(mask_nome.sum())
        if qtd > 0:
            st.session_state.pedidos.loc[mask_nome, 'Cliente'] = nome_novo
            if not salvar_pedidos(st.session_state.pedidos):
                falha = True
            else:
                registrar_alteracao("EDITAR", "CLIENTE", "Nome", nome_antigo, nome_novo)
                msgs.append(("info", f"✏️ Renomeado em {qtd} pedido(s)."))

    # Propaga telefone para os pedidos (já usando o nome novo)
    if not falha and contato_novo != contato_antigo:
        mask_ped = st.session_state.pedidos['Cliente'] == nome_novo
        qtd2 = int(mask_ped.sum())
        if qtd2 > 0:
            st.session_state.pedidos.loc[mask_ped, 'Contato'] = contato_novo
            if not salvar_pedidos(st.session_state.pedidos):
                falha = True
            else:
                msgs.append(("info", f"📱 Telefone atualizado em {qtd2} pedido(s)."))

    if falha:
        st.session_state.pedidos = carregar_pedidos()
        return False, [("error", "❌ Falha ao atualizar os pedidos. Alterações NÃO foram salvas.")]

    # Atualiza o cadastro do cliente
    df_cli.loc[idx, 'Nome'] = nome_novo
    df_cli.loc[idx, 'Contato'] = contato_novo
    df_cli.loc[idx, 'Observacoes'] = obs_nova
    if not salvar_clientes(df_cli):
        st.session_state.pedidos = carregar_pedidos()
        return False, [("error", "❌ Falha ao salvar o cliente. Tente novamente.")]

    st.session_state.clientes = carregar_clientes()
    sincronizar_automaticamente(operacao="editar_cliente")
    msgs.append(("success", "💾 Cliente atualizado!"))
    return True, msgs


def _excluir_cliente(nome):
    """Exclui um cliente com a mesma trava da antiga aba Excluir.

    Bloqueia se houver pedido(s) ativo(s) (não entregue). Retorna (sucesso, msg).
    """
    nome = str(nome).strip()
    pedidos_cliente = st.session_state.pedidos[st.session_state.pedidos['Cliente'] == nome]
    if not pedidos_cliente.empty:
        ativos = pedidos_cliente[pedidos_cliente['Status'] != "✅ Entregue"]
        if not ativos.empty:
            return False, f"🚫 '{nome}' tem {len(ativos)} pedido(s) ativo(s). Não é possível excluir."

    df_atualizado = st.session_state.clientes[st.session_state.clientes['Nome'] != nome]
    if not salvar_clientes(df_atualizado):
        return False, "❌ Não foi possível excluir. Tente novamente."

    registrar_alteracao("EXCLUIR", "CLIENTE", "Nome", nome, "")
    st.session_state.clientes = carregar_clientes()
    sincronizar_automaticamente(operacao="excluir_cliente")
    return True, f"🗑️ Cliente '{nome}' excluído!"


# ==============================================================================
# PÁGINA
# ==============================================================================
def render():
    st.title("👥 Gestão de Clientes")

    col_form, col_base = st.columns([1.2, 1], gap="large")

    # ── Coluna esquerda: formulário de cadastro ──────────────────────────────
    with col_form:
        st.markdown(
            "<div style='font-size:1.15rem; font-weight:800; color:#1f2937;'>"
            "<span style='color:#ea580c;'>●</span> Novo cliente</div>"
            "<div style='color:#6b7280; font-size:0.85rem; margin-bottom:10px;'>"
            "Cadastro e contatos da sua base.</div>",
            unsafe_allow_html=True
        )
        with st.form("cli_form", clear_on_submit=True):
            n = st.text_input("Nome*", placeholder="Ex: João Silva")
            z = st.text_input("WhatsApp", placeholder="79 99999-9999")
            o = st.text_area("Observações", placeholder="Ex: cliente VIP, prefere entrega à tarde...")

            if st.form_submit_button("Cadastrar cliente", use_container_width=True, type="primary"):
                if not n.strip():
                    st.error("❌ Nome é obrigatório!")
                else:
                    nomes = st.session_state.clientes['Nome'].str.lower().str.strip().tolist()
                    if n.lower().strip() in nomes:
                        st.warning(f"⚠️ Cliente '{n}' já cadastrado!")
                    else:
                        tel_limpo, msg_tel = validar_telefone(z)
                        if msg_tel:
                            st.warning(msg_tel)

                        novo = pd.DataFrame([{
                            "Nome": n.strip(),
                            "Contato": tel_limpo,
                            "Observacoes": o.strip()
                        }])
                        st.session_state.clientes = pd.concat([st.session_state.clientes, novo], ignore_index=True)

                        if not salvar_clientes(st.session_state.clientes):
                            st.error("❌ ERRO: Não foi possível cadastrar o cliente. Tente novamente.")
                        else:
                            st.session_state.clientes = carregar_clientes()
                            sincronizar_automaticamente(operacao="cadastrar_cliente")
                            st.toast(f"Cliente '{n}' cadastrado!", icon="✅")
                            st.rerun()

        # Ferramentas secundárias (antes na aba Lista): exportar / importar / sincronizar
        with st.expander("🔧 Importar · Exportar · Sincronizar", expanded=False):
            cexp1, cexp2 = st.columns(2)
            with cexp1:
                if st.button("📄 Exportar PDF", use_container_width=True, key="btn_exportar_pdf_clientes"):
                    pdf = gerar_lista_clientes_pdf(st.session_state.clientes)
                    if pdf:
                        st.download_button("⬇️ Baixar PDF", pdf, "Clientes.pdf", "application/pdf", key="btn_download_pdf_clientes")
            with cexp2:
                csv = st.session_state.clientes.to_csv(index=False).encode('utf-8')
                st.download_button("📊 Exportar CSV", csv, "clientes.csv", "text/csv", use_container_width=True)

            st.markdown("---")
            st.caption("Atualize todos os pedidos com os telefones mais recentes do cadastro.")
            if st.button("🔄 Sincronizar telefones nos pedidos", use_container_width=True, type="secondary", key="btn_sincronizar_contatos"):
                atualizados, total_clientes = sincronizar_contatos_pedidos()
                if atualizados:
                    st.success(f"✅ {atualizados} pedido(s) atualizado(s) com base em {total_clientes} cliente(s).")
                else:
                    st.info("Nenhum pedido precisava de atualização no telefone.")

            st.markdown("---")
            up_c = st.file_uploader("Importar CSV de clientes", type="csv", key="rest_cli")
            if up_c and st.button("⚠️ Importar (substitui a base)", key="btn_importar_clientes_csv"):
                try:
                    df_c = pd.read_csv(up_c)
                    colunas_esperadas = ["Nome", "Contato", "Observacoes"]
                    colunas_faltantes = set(colunas_esperadas) - set(df_c.columns.tolist())
                    if colunas_faltantes:
                        st.error(f"❌ CSV inválido! Colunas obrigatórias faltando: {', '.join(sorted(colunas_faltantes))}")
                    else:
                        df_c = df_c[colunas_esperadas]
                        if not salvar_clientes(df_c):
                            st.error("❌ ERRO: Não foi possível importar os clientes. Tente novamente.")
                        else:
                            st.session_state.clientes = carregar_clientes()
                            sincronizar_automaticamente(operacao="importar_clientes")
                            st.toast("Clientes importados!", icon="✅")
                            st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

    # ── Coluna direita: base de clientes com avatares + editar/excluir ───────
    with col_base:
        df_cli = st.session_state.clientes
        total = len(df_cli) if df_cli is not None else 0
        st.markdown(
            f"<div style='font-size:1.05rem; font-weight:800; color:#1f2937; margin-bottom:6px;'>"
            f"Base de clientes <span style='color:#9ca3af; font-weight:600;'>· {total}</span></div>",
            unsafe_allow_html=True
        )

        # Estilos dos avatares/linha
        st.markdown(
            """
            <style>
            .cli-av {
                width: 38px; height: 38px; border-radius: 50%;
                background: #fde4d3; color: #c2410c; font-weight: 800;
                display: flex; align-items: center; justify-content: center;
                font-size: 0.95rem; margin-top: 2px;
            }
            .cli-nome { font-weight: 700; color: #374151; font-size: 0.92rem; line-height: 1.2; }
            .cli-tel { color: #9ca3af; font-size: 0.78rem; line-height: 1.2; }
            </style>
            """,
            unsafe_allow_html=True
        )

        if total == 0:
            st.info("Nenhum cliente cadastrado ainda.")
            return

        busca_base = st.text_input(
            "Buscar cliente", key="busca_base_clientes",
            placeholder="🔎 Buscar cliente...", label_visibility="collapsed"
        )

        # ── Painel inline de EDIÇÃO ──────────────────────────────────────────
        if st.session_state.get('cli_editando'):
            nome_ed = st.session_state['cli_editando']
            m = df_cli[df_cli['Nome'].astype(str).str.strip() == str(nome_ed).strip()]
            if m.empty:
                st.session_state.pop('cli_editando', None)
            else:
                row = m.iloc[0]
                with st.container(border=True):
                    st.markdown(f"**✏️ Editar — {safe_html(str(nome_ed))}**")
                    with st.form("form_edit_cli_inline"):
                        e_nome = st.text_input("Nome*", value=str(row['Nome']))
                        e_tel = st.text_input("WhatsApp", value=str(row['Contato']) if pd.notna(row['Contato']) else "")
                        e_obs = st.text_area("Observações", value=str(row.get('Observacoes', '')) if pd.notna(row.get('Observacoes', '')) else "")
                        c_sv, c_cc = st.columns(2)
                        with c_sv:
                            salvar_ed = st.form_submit_button("💾 Salvar", type="primary", use_container_width=True)
                        with c_cc:
                            cancelar_ed = st.form_submit_button("Cancelar", use_container_width=True)

                    if salvar_ed:
                        ok, msgs = _salvar_edicao_cliente(nome_ed, e_nome, e_tel, e_obs)
                        for tipo, texto in msgs:
                            getattr(st, tipo, st.write)(texto)
                        if ok:
                            st.session_state.pop('cli_editando', None)
                            st.rerun()
                    if cancelar_ed:
                        st.session_state.pop('cli_editando', None)
                        st.rerun()

        # ── Painel inline de EXCLUSÃO ────────────────────────────────────────
        if st.session_state.get('cli_excluindo'):
            nome_ex = st.session_state['cli_excluindo']
            pedidos_cliente = st.session_state.pedidos[st.session_state.pedidos['Cliente'] == nome_ex]
            ativos = pedidos_cliente[pedidos_cliente['Status'] != "✅ Entregue"] if not pedidos_cliente.empty else pd.DataFrame()
            with st.container(border=True):
                if not ativos.empty:
                    st.error(f"🚫 '{nome_ex}' tem {len(ativos)} pedido(s) ativo(s) (não entregue). Não é possível excluir.")
                    st.caption("Finalize ou exclua os pedidos ativos antes de remover o cliente.")
                    if st.button("Fechar", key="fechar_excl_cli", use_container_width=True):
                        st.session_state.pop('cli_excluindo', None)
                        st.rerun()
                else:
                    if not pedidos_cliente.empty:
                        st.warning(f"⚠️ '{nome_ex}' tem {len(pedidos_cliente)} pedido(s) entregue(s) no histórico.")
                    st.markdown(f"Excluir **{safe_html(str(nome_ex))}**? Esta ação não pode ser desfeita.")
                    c_ok, c_no = st.columns(2)
                    with c_ok:
                        if st.button("🗑️ Sim, excluir", key="conf_excl_cli", type="primary", use_container_width=True):
                            ok, msg = _excluir_cliente(nome_ex)
                            if ok:
                                st.session_state.pop('cli_excluindo', None)
                                st.toast(msg, icon="🗑️")
                                st.rerun()
                            else:
                                st.error(msg)
                    with c_no:
                        if st.button("Cancelar", key="canc_excl_cli", use_container_width=True):
                            st.session_state.pop('cli_excluindo', None)
                            st.rerun()

        # ── Lista de clientes (avatar + nome/telefone + ✏️ + 🗑️) ─────────────
        df_ord = df_cli.copy()
        df_ord['Nome'] = df_ord['Nome'].fillna("").astype(str)
        df_ord = df_ord.sort_values('Nome', key=lambda s: s.str.lower())

        termo = (busca_base or "").strip().lower()
        if termo:
            df_ord = df_ord[df_ord['Nome'].str.lower().str.contains(termo, na=False)]

        df_ord = df_ord[df_ord['Nome'].str.strip() != ""]

        if df_ord.empty:
            st.caption("Nenhum cliente encontrado para a busca.")
            return

        # Teto de exibição para manter a tela rápida conforme a base cresce
        CAP = 100
        restantes = len(df_ord) - CAP
        df_show = df_ord.head(CAP) if restantes > 0 else df_ord

        for i, c in df_show.iterrows():
            nome = str(c['Nome']).strip()
            inicial = nome[:1].upper() if nome else "?"
            tel = limpar_telefone(c.get('Contato', ''))

            rc_av, rc_info, rc_e, rc_d = st.columns([0.55, 3.2, 0.7, 0.7])
            with rc_av:
                st.markdown(f"<div class='cli-av'>{safe_html(inicial)}</div>", unsafe_allow_html=True)
            with rc_info:
                tel_html = f"<div class='cli-tel'>{safe_html(tel)}</div>" if tel else ""
                st.markdown(f"<div class='cli-nome'>{safe_html(nome)}</div>{tel_html}", unsafe_allow_html=True)
            with rc_e:
                if st.button("✏️", key=f"edit_cli_{i}", help="Editar cliente"):
                    st.session_state['cli_editando'] = nome
                    st.session_state.pop('cli_excluindo', None)
                    st.rerun()
            with rc_d:
                if st.button("🗑️", key=f"del_cli_{i}", help="Excluir cliente"):
                    st.session_state['cli_excluindo'] = nome
                    st.session_state.pop('cli_editando', None)
                    st.rerun()

        if restantes > 0:
            st.caption(f"➕ Mais {restantes} cliente(s). Use a busca acima para encontrá-los.")
