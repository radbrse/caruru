import streamlit as st
import pandas as pd
import urllib.parse

from utils import limpar_telefone


def render():
    st.title("📢 Marketing & Promoções")

    st.subheader("1️⃣ Configurar Mensagem")
    c_img, c_txt = st.columns([1, 2])

    with c_img:
        up_img = st.file_uploader("🖼️ Banner (Visualização)", type=["jpg", "png", "jpeg"])
        if up_img:
            st.image(up_img, caption="Preview do Banner", use_column_width=True)
            st.info("💡 Anexe a imagem manualmente no WhatsApp.")

    with c_txt:
        txt_padrao = """Olá! 🦐

Hoje tem *Caruru Fresquinho* no Cantinho!

🥘 Caruru Tradicional - R$ 70,00
🦐 Bobó de Camarão - R$ 70,00

Peça já o seu! 😋
📲 Faça seu pedido!"""
        msg = st.text_area("✏️ Texto da Promoção", value=txt_padrao, height=200)

    st.divider()
    st.subheader("2️⃣ Enviar para Clientes")

    df_c = st.session_state.clientes
    if df_c.empty:
        st.warning("Nenhum cliente cadastrado.")
    else:
        filtro = st.text_input("🔍 Buscar cliente:")
        if filtro:
            df_c = df_c[
                df_c['Nome'].str.contains(filtro, case=False, na=False) |
                df_c['Contato'].str.contains(filtro, na=False)
            ]

        msg_enc = urllib.parse.quote(msg)
        df_show = df_c[['Nome', 'Contato']].copy()

        def link_zap(tel):
            t = limpar_telefone(tel)
            return f"https://wa.me/55{t}?text={msg_enc}" if len(t) >= 10 else None

        df_show['Link'] = df_show['Contato'].apply(link_zap)

        st.data_editor(
            df_show,
            column_config={
                "Link": st.column_config.LinkColumn("Ação", display_text="📱 Enviar"),
                "Nome": st.column_config.TextColumn(disabled=True),
                "Contato": st.column_config.TextColumn(disabled=True)
            },
            hide_index=True,
            use_container_width=True
        )
