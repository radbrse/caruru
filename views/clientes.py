import streamlit as st
import pandas as pd

from config import logger
from utils import limpar_telefone, formatar_valor_br, validar_telefone, safe_html
from database import salvar_clientes, carregar_clientes, salvar_pedidos, carregar_pedidos, registrar_alteracao
from pedidos import sincronizar_dados_cliente, sincronizar_contatos_pedidos
from pdf import gerar_lista_clientes_pdf
from sheets import sincronizar_automaticamente
from storage import transacional
from database import restaurar_conjunto
from config import carregar_config


# ==============================================================================
# OPERAÇÕES RESILIENTES (mesma lógica que as antigas abas Lista/Excluir)
# ==============================================================================
@transacional
def _salvar_edicao_cliente(nome_antigo, nome_novo, contato_novo, obs_nova):
    nome_antigo, nome_novo = str(nome_antigo).strip(), (nome_novo or '').strip()
    if not nome_novo:
        return False, [('error', 'Nome é obrigatório.')]
    clientes, pedidos = carregar_clientes(), carregar_pedidos()
    mask = clientes.Nome.str.strip() == nome_antigo
    if not mask.any():
        return False, [('error', 'Cliente não encontrado. Recarregue os dados.')]
    if nome_novo.lower() != nome_antigo.lower() and nome_novo.lower() in clientes.loc[~mask, 'Nome'].str.strip().str.lower().tolist():
        return False, [('warning', 'Já existe um cliente com esse nome.')]
    clientes.loc[mask, ['Nome', 'Contato', 'Observacoes']] = [nome_novo, limpar_telefone(contato_novo), (obs_nova or '').strip()]
    mask_p = pedidos.Cliente == nome_antigo
    pedidos.loc[mask_p, ['Cliente', 'Contato']] = [nome_novo, limpar_telefone(contato_novo)]
    ok, msg = restaurar_conjunto(pedidos, clientes, carregar_config())
    if not ok:
        return False, [('error', msg)]
    st.session_state.pedidos, st.session_state.clientes = carregar_pedidos(), carregar_clientes()
    registrar_alteracao('EDITAR_CLIENTE', 0, 'Nome/Contato', nome_antigo, nome_novo)
    sincronizar_automaticamente('editar_cliente')
    return True, [('success', 'Cliente e pedidos atualizados.')]


@transacional
def _excluir_cliente(nome):
    """Exclui um cliente com a mesma trava da antiga aba Excluir.

    Bloqueia se houver pedido(s) ativo(s) (não entregue). Retorna (sucesso, msg).
    """
    nome = str(nome).strip()
    pedidos = carregar_pedidos()
    pedidos_cliente = pedidos[pedidos['Cliente'] == nome]
    if not pedidos_cliente.empty:
        ativos = pedidos_cliente[pedidos_cliente['Status'] != "✅ Entregue"]
        if not ativos.empty:
            return False, f"🚫 '{nome}' tem {len(ativos)} pedido(s) ativo(s). Não é possível excluir."

    clientes = carregar_clientes()
    df_atualizado = clientes[clientes['Nome'] != nome]
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

                        ok, mensagem, _ = sincronizar_dados_cliente(n.strip(), tel_limpo, observacoes=o.strip())
                        if not ok:
                            st.error(mensagem)
                        else:
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
                        if not salvar_clientes(df_c, substituir=True):
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
            df_ord = df_ord[df_ord['Nome'].str.lower().str.contains(termo, regex=False, na=False)]

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
