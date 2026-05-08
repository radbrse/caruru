"""
Sistema de autenticação do Cantinho do Caruru.
"""

import time
import streamlit as st


def check_password():
    MAX_TENTATIVAS = 5

    def password_entered():
        # Rate-limit: aplica delay crescente após tentativas falhas (mitigação anti brute-force)
        tentativas = st.session_state.get("auth_tentativas", 0)
        if tentativas > 0:
            time.sleep(min(2 ** tentativas, 30))  # 2s, 4s, 8s, 16s, 30s (cap)

        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            st.session_state["auth_tentativas"] = 0
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False
            st.session_state["auth_tentativas"] = tentativas + 1

    if st.session_state.get("password_correct", False):
        return True

    tentativas = st.session_state.get("auth_tentativas", 0)
    bloqueado = tentativas >= MAX_TENTATIVAS

    st.title("🔒 Acesso Restrito")

    if bloqueado:
        st.error(f"🚫 Muitas tentativas falhas ({tentativas}). Recarregue a página para tentar novamente.")
        return False

    st.text_input("Digite a senha:", type="password", key="password", on_change=password_entered)
    if "password_correct" in st.session_state and not st.session_state["password_correct"]:
        st.error(f"Senha incorreta. ({tentativas}/{MAX_TENTATIVAS} tentativas)")
    return False
