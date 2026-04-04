import streamlit as st
import pandas as pd
from datetime import date, timedelta

from config import logger, hoje_brasil, obter_preco_base
from utils import formatar_valor_br, calcular_total
from pdf import gerar_relatorio_pdf, gerar_recibo_pdf, gerar_orcamento_pdf
from database import carregar_pedidos


def render():
    st.title("🖨️ Impressão de Documentos")

    t1, t2, t3 = st.tabs(["📄 Recibo Individual", "📊 Relatório Geral", "📋 Orçamento"])
    df = st.session_state.pedidos

    with t1:
        if df.empty:
            st.info("Sem pedidos cadastrados.")
        else:
            cli = st.selectbox("👤 Cliente:", sorted(df['Cliente'].unique()), key="rel_select_cliente")
            peds = df[df['Cliente'] == cli].sort_values("Data", ascending=False)

            if not peds.empty:
                opc = {
                    i: f"#{p['ID_Pedido']} | {p['Data'].strftime('%d/%m/%Y') if (hasattr(p['Data'], 'strftime') and pd.notna(p['Data'])) else p['Data']} | {formatar_valor_br(p['Valor'])} | {p['Status']}"
                    for i, p in peds.iterrows()
                }
                sid = st.selectbox("📋 Selecione o pedido:", options=opc.keys(), format_func=lambda x: opc[x], key="rel_select_pedido")

                if st.button("📄 Gerar Recibo PDF", use_container_width=True, type="primary", key="btn_gerar_recibo"):
                    pdf = gerar_recibo_pdf(peds.loc[sid].to_dict())
                    if pdf:
                        st.download_button(
                            "⬇️ Baixar Recibo",
                            pdf,
                            f"Recibo_{cli}_{peds.loc[sid]['ID_Pedido']}.pdf",
                            "application/pdf"
                        )
                    else:
                        st.error("Erro ao gerar PDF.")

    with t2:
        tipo = st.radio("📅 Filtro:", ["Dia Específico", "Período", "Tudo"], horizontal=True, key="rel_tipo_filtro")

        if tipo == "Dia Específico":
            dt = st.date_input("Data:", hoje_brasil(), format="DD/MM/YYYY", key="rel_data")
            df_rel = df[df['Data'] == dt]
            nome = f"Relatorio_{dt.strftime('%d-%m-%Y')}.pdf"
        elif tipo == "Período":
            c1, c2 = st.columns(2)
            with c1:
                dt_ini = st.date_input("De:", hoje_brasil() - timedelta(days=7), format="DD/MM/YYYY")
            with c2:
                dt_fim = st.date_input("Até:", hoje_brasil(), format="DD/MM/YYYY")
            df_rel = df[(df['Data'] >= dt_ini) & (df['Data'] <= dt_fim)]
            nome = f"Relatorio_{dt_ini.strftime('%d-%m')}_{dt_fim.strftime('%d-%m-%Y')}.pdf"
        else:
            df_rel = df
            nome = "Relatorio_Geral.pdf"

        # Calcula totais
        total_caruru = int(df_rel['Caruru'].sum()) if not df_rel.empty else 0
        total_bobo = int(df_rel['Bobo'].sum()) if not df_rel.empty else 0
        total_valor = df_rel['Valor'].sum() if not df_rel.empty else 0

        st.write(f"📊 **{len(df_rel)}** pedidos | 🥘 **{total_caruru}** kg Caruru | 🦐 **{total_bobo}** kg Bobó | 💰 **Total:** {formatar_valor_br(total_valor)}")

        if not df_rel.empty:
            if st.button("📊 Gerar Relatório PDF", use_container_width=True, type="primary", key="btn_gerar_relatorio"):
                # Ordena por Data e Hora antes de gerar o PDF
                df_rel_ordenado = df_rel.sort_values(['Data', 'Hora'], ascending=[True, True])
                pdf = gerar_relatorio_pdf(df_rel_ordenado, nome.replace(".pdf", ""))
                if pdf:
                    st.download_button("⬇️ Baixar Relatório", pdf, nome, "application/pdf")
                else:
                    st.error("Erro ao gerar PDF.")

    with t3:
        st.markdown("### 📋 Gerar Orçamento")
        st.caption("Preencha os dados abaixo para gerar uma proposta comercial em PDF.")

        # --- Seleção do cliente ---
        st.markdown("#### 1️⃣ Cliente")
        col_cli, col_novo = st.columns([4, 1])
        with col_novo:
            orc_eh_novo = st.toggle("✍️ Novo", key="orc_toggle_novo", help="Ativar para digitar um nome que não está cadastrado")

        contato_orc = ""
        if orc_eh_novo:
            with col_cli:
                orc_cliente = st.text_input(
                    "👤 Nome do Cliente",
                    placeholder="Digite o nome completo...",
                    key="orc_input_novo_cliente"
                ).strip()
            orc_contato_input = st.text_input("📱 WhatsApp", placeholder="79999999999", key="orc_contato_novo")
        else:
            try:
                clis_orc = sorted(st.session_state.clientes['Nome'].astype(str).unique().tolist())
            except Exception:
                clis_orc = []

            with col_cli:
                orc_cliente_sel = st.selectbox(
                    "👤 Cliente cadastrado",
                    ["-- Selecione --"] + clis_orc,
                    key="orc_select_cliente"
                )
            orc_cliente = "" if orc_cliente_sel == "-- Selecione --" else orc_cliente_sel

            # Busca contato automaticamente
            if orc_cliente:
                try:
                    res = st.session_state.clientes[st.session_state.clientes['Nome'] == orc_cliente]
                    if not res.empty:
                        contato_orc = str(res.iloc[0]['Contato']) if pd.notna(res.iloc[0]['Contato']) else ""
                except Exception:
                    contato_orc = ""
                st.success(f"📱 Contato: **{contato_orc}**" if contato_orc else "⚠️ Cliente sem telefone cadastrado")

            orc_contato_input = st.text_input("📱 WhatsApp", value=contato_orc, placeholder="79999999999", key="orc_contato")

        # --- Itens e valores ---
        st.markdown("#### 2️⃣ Itens e Valores")
        preco_atual = obter_preco_base()
        st.caption(f"💵 Preço unitário atual: **R$ {preco_atual:.2f}/kg**")

        col_c, col_b, col_d = st.columns(3)
        with col_c:
            orc_caruru = st.number_input("🥘 Caruru (kg)", min_value=0, max_value=999, step=1, value=0, key="orc_caruru")
        with col_b:
            orc_bobo = st.number_input("🦐 Bobó (kg)", min_value=0, max_value=999, step=1, value=0, key="orc_bobo")
        with col_d:
            orc_desconto = st.number_input("💸 Desconto %", min_value=0, max_value=100, step=5, value=0, key="orc_desconto")

        # Preview de valores em tempo real
        if orc_caruru > 0 or orc_bobo > 0:
            subtotal_bruto = (orc_caruru + orc_bobo) * preco_atual
            desconto_valor = subtotal_bruto * orc_desconto / 100
            total_orc = subtotal_bruto - desconto_valor
            col_prev1, col_prev2, col_prev3 = st.columns(3)
            with col_prev1:
                st.metric("Subtotal", formatar_valor_br(subtotal_bruto))
            with col_prev2:
                st.metric("Desconto", f"- {formatar_valor_br(desconto_valor)}" if orc_desconto > 0 else "—")
            with col_prev3:
                st.metric("**Total**", formatar_valor_br(total_orc))

        # --- Validade e observações ---
        st.markdown("#### 3️⃣ Complemento")
        col_v, col_obs = st.columns([1, 2])
        with col_v:
            orc_validade = st.date_input(
                "📅 Validade do orçamento",
                value=hoje_brasil() + timedelta(days=7),
                format="DD/MM/YYYY",
                key="orc_validade"
            )
        with col_obs:
            orc_obs = st.text_area("📝 Observações", placeholder="Ex: Retirada no local, embalagem inclusa...", key="orc_obs")

        # --- Geração do PDF ---
        st.divider()
        pode_gerar = bool(orc_cliente) and (orc_caruru > 0 or orc_bobo > 0)
        if not pode_gerar:
            st.info("💡 Preencha o nome do cliente e ao menos um item para gerar o orçamento.")

        if st.button("📋 Gerar Orçamento PDF", use_container_width=True, type="primary",
                     key="btn_gerar_orcamento", disabled=not pode_gerar):
            dados_orc = {
                'Cliente':    orc_cliente,
                'Contato':    orc_contato_input,
                'Caruru':     orc_caruru,
                'Bobo':       orc_bobo,
                'Desconto':   orc_desconto,
                'Validade':   orc_validade,
                'Observacoes': orc_obs,
            }
            pdf = gerar_orcamento_pdf(dados_orc)
            if pdf:
                nome_arquivo = f"Orcamento_{orc_cliente.replace(' ', '_')}.pdf"
                st.download_button("⬇️ Baixar Orçamento", pdf, nome_arquivo, "application/pdf",
                                   use_container_width=True)
            else:
                st.error("Erro ao gerar PDF do orçamento.")
