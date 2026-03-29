import streamlit as st
import pandas as pd
from datetime import date, timedelta

from config import logger, hoje_brasil
from utils import formatar_valor_br
from pdf import gerar_relatorio_pdf, gerar_recibo_pdf
from database import carregar_pedidos


def render():
    st.title("🖨️ Impressão de Documentos")

    t1, t2 = st.tabs(["📄 Recibo Individual", "📊 Relatório Geral"])
    df = st.session_state.pedidos

    with t1:
        if df.empty:
            st.info("Sem pedidos cadastrados.")
        else:
            cli = st.selectbox("👤 Cliente:", sorted(df['Cliente'].unique()), key="rel_select_cliente")
            peds = df[df['Cliente'] == cli].sort_values("Data", ascending=False)

            if not peds.empty:
                opc = {
                    i: f"#{p['ID_Pedido']} | {p['Data'].strftime('%d/%m/%Y') if hasattr(p['Data'], 'strftime') else p['Data']} | {formatar_valor_br(p['Valor'])} | {p['Status']}"
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
