import streamlit as st
import pandas as pd

from config import logger
from utils import limpar_telefone, formatar_valor_br, validar_telefone, safe_html
from database import salvar_clientes, carregar_clientes, salvar_pedidos, carregar_pedidos, registrar_alteracao
from pedidos import sincronizar_dados_cliente, sincronizar_contatos_pedidos
from pdf import gerar_lista_clientes_pdf
from sheets import sincronizar_automaticamente


def render():
    st.title("👥 Gestão de Clientes")

    t1, t2, t3 = st.tabs(["➕ Cadastrar", "📋 Lista", "🗑️ Excluir"])

    with t1:
        col_form, col_base = st.columns([1.2, 1], gap="large")

        # ── Coluna esquerda: formulário de cadastro ───────────────────────────
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
                        # Verifica duplicado
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

                            # Tenta salvar no disco
                            if not salvar_clientes(st.session_state.clientes):
                                st.error("❌ ERRO: Não foi possível cadastrar o cliente. Tente novamente.")
                            else:
                                # Recarrega do arquivo para garantir sincronização
                                st.session_state.clientes = carregar_clientes()

                                # Sincronização automática com Google Sheets (se habilitada)
                                sincronizar_automaticamente(operacao="cadastrar_cliente")

                                st.toast(f"Cliente '{n}' cadastrado!", icon="✅")
                                st.rerun()

        # ── Coluna direita: base de clientes com avatares (somente leitura) ───
        with col_base:
            df_cli = st.session_state.clientes
            total = len(df_cli) if df_cli is not None else 0
            st.markdown(
                f"<div style='font-size:1.05rem; font-weight:800; color:#1f2937; margin-bottom:6px;'>"
                f"Base de clientes <span style='color:#9ca3af; font-weight:600;'>· {total}</span></div>",
                unsafe_allow_html=True
            )
            busca_base = st.text_input(
                "Buscar cliente", key="busca_base_clientes",
                placeholder="🔎 Buscar cliente...", label_visibility="collapsed"
            )

            # Estilos do cartão da base (escopados pela classe .cli-base)
            estilo_base = """
            <style>
            .cli-base {
                max-height: 540px; overflow-y: auto; padding: 6px 4px;
                border: 1px solid #f0e3da; border-radius: 14px; background: #fffdfb;
            }
            .cli-row {
                display: flex; align-items: center; gap: 12px;
                padding: 9px 12px; border-bottom: 1px solid #f5eee8;
            }
            .cli-row:last-child { border-bottom: none; }
            .cli-av {
                flex: 0 0 auto; width: 38px; height: 38px; border-radius: 50%;
                background: #fde4d3; color: #c2410c; font-weight: 800;
                display: flex; align-items: center; justify-content: center;
                font-size: 0.95rem;
            }
            .cli-info { display: flex; flex-direction: column; line-height: 1.2; }
            .cli-nome { font-weight: 700; color: #374151; font-size: 0.92rem; }
            .cli-tel { color: #9ca3af; font-size: 0.78rem; }
            </style>
            """

            if total == 0:
                st.info("Nenhum cliente cadastrado ainda.")
            else:
                df_ord = df_cli.copy()
                df_ord['Nome'] = df_ord['Nome'].fillna("").astype(str)
                df_ord = df_ord.sort_values('Nome', key=lambda s: s.str.lower())

                termo = (busca_base or "").strip().lower()
                if termo:
                    df_ord = df_ord[df_ord['Nome'].str.lower().str.contains(termo, na=False)]

                linhas = []
                for _, c in df_ord.iterrows():
                    nome = c['Nome'].strip()
                    if not nome:
                        continue
                    inicial = nome[:1].upper()
                    tel = limpar_telefone(c.get('Contato', ''))
                    tel_html = f"<span class='cli-tel'>{safe_html(tel)}</span>" if tel else ""
                    linhas.append(
                        f"<div class='cli-row'><div class='cli-av'>{safe_html(inicial)}</div>"
                        f"<div class='cli-info'><span class='cli-nome'>{safe_html(nome)}</span>"
                        f"{tel_html}</div></div>"
                    )

                if linhas:
                    st.markdown(estilo_base + f"<div class='cli-base'>{''.join(linhas)}</div>", unsafe_allow_html=True)
                else:
                    st.caption("Nenhum cliente encontrado para a busca.")

    with t2:
        st.subheader("Lista de Clientes")
        if not st.session_state.clientes.empty:
            clientes_antes = st.session_state.clientes.copy()
            edited = st.data_editor(
                st.session_state.clientes,
                num_rows="fixed",
                use_container_width=True,
                hide_index=True
            )
            if not edited.equals(st.session_state.clientes):
                # Normaliza dados e limpa formatação dos telefones
                edited_limpo = edited.copy()
                edited_limpo['Nome'] = edited_limpo['Nome'].fillna("").astype(str).str.strip()
                edited_limpo['Contato'] = edited_limpo['Contato'].fillna("").astype(str).apply(limpar_telefone)
                edited_limpo['Observacoes'] = edited_limpo['Observacoes'].fillna("").astype(str).str.strip()

                # Detecta mudanças de nome e telefone e sincroniza com pedidos.
                # Se a propagação para os pedidos falhar, NÃO salva os clientes —
                # evita estado inconsistente (cliente com dado novo, pedidos com dado antigo).
                falha_propagacao = False
                for idx in edited_limpo.index:
                    nome_novo = edited_limpo.loc[idx, 'Nome']
                    contato_novo = edited_limpo.loc[idx, 'Contato']

                    if idx in clientes_antes.index:
                        nome_antigo = str(clientes_antes.loc[idx, 'Nome']).strip()

                        # Verifica se o nome mudou — propaga para pedidos existentes
                        if nome_novo and nome_novo != nome_antigo and nome_antigo:
                            mask_nome = st.session_state.pedidos['Cliente'] == nome_antigo
                            qtd_rename = mask_nome.sum()
                            if qtd_rename > 0:
                                st.session_state.pedidos.loc[mask_nome, 'Cliente'] = nome_novo
                                if not salvar_pedidos(st.session_state.pedidos):
                                    st.error(f"❌ ERRO: Não foi possível renomear '{nome_antigo}' nos pedidos.")
                                    falha_propagacao = True
                                else:
                                    registrar_alteracao("EDITAR", "CLIENTE", "Nome", nome_antigo, nome_novo)
                                    st.info(f"✏️ Cliente '{nome_antigo}' renomeado para '{nome_novo}' em {qtd_rename} pedido(s)")

                        # Verifica se o telefone mudou
                        contato_antigo = limpar_telefone(clientes_antes.loc[idx, 'Contato'])
                        if contato_novo != contato_antigo:
                            # Atualiza telefone em todos os pedidos deste cliente
                            mask_pedidos = st.session_state.pedidos['Cliente'] == nome_novo
                            qtd_pedidos = mask_pedidos.sum()

                            if qtd_pedidos > 0:
                                st.session_state.pedidos.loc[mask_pedidos, 'Contato'] = contato_novo
                                if not salvar_pedidos(st.session_state.pedidos):
                                    st.error("❌ ERRO: Não foi possível atualizar telefones nos pedidos.")
                                    falha_propagacao = True
                                else:
                                    st.info(f"📱 Telefone de '{nome_novo}' atualizado em {qtd_pedidos} pedido(s)")

                if falha_propagacao:
                    st.error("❌ As alterações dos clientes NÃO foram salvas porque a atualização dos pedidos falhou. Tente novamente.")
                    st.session_state.pedidos = carregar_pedidos()
                    st.stop()

                st.session_state.clientes = edited_limpo

                # Tenta salvar clientes
                if not salvar_clientes(edited_limpo):
                    st.error("❌ ERRO: Não foi possível salvar as alterações nos clientes. Tente novamente.")
                else:
                    # Recarrega clientes do arquivo
                    st.session_state.clientes = carregar_clientes()

                    # Sincroniza todos os pedidos com a base de clientes
                    atualizados, total_clientes = sincronizar_contatos_pedidos()
                    if atualizados:
                        st.success(f"🔄 Telefones sincronizados em {atualizados} pedido(s) com base em {total_clientes} cliente(s)")

                    # Sincronização automática com Google Sheets (se habilitada)
                    sincronizar_automaticamente(operacao="editar_cliente")

                    st.toast("💾 Salvo!")
                    st.rerun()

            st.divider()
            c1, c2 = st.columns(2)
            with c1:
                if st.button("📄 Exportar Lista PDF", use_container_width=True, key="btn_exportar_pdf_clientes"):
                    pdf = gerar_lista_clientes_pdf(st.session_state.clientes)
                    if pdf:
                        st.download_button("⬇️ Baixar PDF", pdf, "Clientes.pdf", "application/pdf", key="btn_download_pdf_clientes")
            with c2:
                csv = st.session_state.clientes.to_csv(index=False).encode('utf-8')
                st.download_button("📊 Exportar CSV", csv, "clientes.csv", "text/csv", use_container_width=True)
        else:
            st.info("Nenhum cliente cadastrado.")

        st.markdown("---")
        st.subheader("🔄 Sincronizar Telefones nos Pedidos")
        st.caption("Atualize todos os pedidos com os telefones mais recentes do cadastro de clientes.")
        if st.button("🔄 Sincronizar agora", use_container_width=True, type="secondary", key="btn_sincronizar_contatos"):
            atualizados, total_clientes = sincronizar_contatos_pedidos()
            if atualizados:
                st.success(f"✅ {atualizados} pedido(s) atualizado(s) com base em {total_clientes} cliente(s) cadastrado(s)")
            else:
                st.info("Nenhum pedido precisava de atualização no telefone.")

        with st.expander("📤 Importar Clientes"):
            up_c = st.file_uploader("Arquivo CSV", type="csv", key="rest_cli")
            if up_c and st.button("⚠️ Importar", key="btn_importar_clientes_csv"):
                try:
                    df_c = pd.read_csv(up_c)

                    # Valida schema
                    colunas_esperadas = ["Nome", "Contato", "Observacoes"]
                    colunas_faltantes = set(colunas_esperadas) - set(df_c.columns.tolist())
                    if colunas_faltantes:
                        st.error(f"❌ CSV inválido! Colunas obrigatórias faltando: {', '.join(sorted(colunas_faltantes))}")
                    else:
                        # Reordena para manter apenas colunas esperadas
                        df_c = df_c[colunas_esperadas]

                        # Tenta salvar no disco
                        if not salvar_clientes(df_c):
                            st.error("❌ ERRO: Não foi possível importar os clientes. Tente novamente.")
                        else:
                            st.session_state.clientes = carregar_clientes()

                        # Sincronização automática com Google Sheets (se habilitada)
                        sincronizar_automaticamente(operacao="importar_clientes")

                        st.toast("Clientes importados!", icon="✅")
                        st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

    with t3:
        st.subheader("Excluir Cliente")
        if not st.session_state.clientes.empty:
            lista_cli = st.session_state.clientes['Nome'].unique().tolist()
            d = st.selectbox("👤 Selecione o cliente:", lista_cli, key="cli_select_excluir")

            # Verifica se tem pedidos ativos (não entregues)
            pedidos_cliente = st.session_state.pedidos[st.session_state.pedidos['Cliente'] == d]
            pedidos_ativos = pedidos_cliente[pedidos_cliente['Status'] != "✅ Entregue"] if not pedidos_cliente.empty else pd.DataFrame()

            tem_pedidos_ativos = not pedidos_ativos.empty
            if tem_pedidos_ativos:
                st.error(f"🚫 Este cliente tem {len(pedidos_ativos)} pedido(s) ativo(s) (não entregue). Não é possível excluir.")
                st.info("Finalize ou exclua os pedidos ativos antes de remover o cliente.")
            elif not pedidos_cliente.empty:
                st.warning(f"⚠️ Este cliente tem {len(pedidos_cliente)} pedido(s) já entregue(s) no histórico.")

            confirma = st.checkbox(f"✅ Confirmo a exclusão de '{d}'", disabled=tem_pedidos_ativos, key="cli_confirma_excluir")

            if st.button("🗑️ Excluir Cliente", type="primary", disabled=(not confirma or tem_pedidos_ativos), use_container_width=True, key="btn_excluir_cliente"):
                df_atualizado = st.session_state.clientes[st.session_state.clientes['Nome'] != d]

                # Tenta salvar no disco
                if not salvar_clientes(df_atualizado):
                    st.error("❌ ERRO: Não foi possível excluir o cliente. Tente novamente.")
                else:
                    registrar_alteracao("EXCLUIR", "CLIENTE", "Nome", d, "")

                    # Recarrega do arquivo para garantir sincronização
                    st.session_state.clientes = carregar_clientes()

                    # Sincronização automática com Google Sheets (se habilitada)
                    sincronizar_automaticamente(operacao="excluir_cliente")

                    st.toast(f"Cliente '{d}' excluído!", icon="🗑️")
                    st.rerun()
        else:
            st.info("Nenhum cliente cadastrado.")
