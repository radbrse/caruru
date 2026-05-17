"""
View de Manutenção do Sistema.
Logs, Histórico, Backups, Google Sheets e Configurações.
"""

import streamlit as st
import pandas as pd
import os
import time as time_module
import requests
from datetime import timedelta

from config import (
    logger, VERSAO, CHAVE_PIX, agora_brasil, hoje_brasil,
    ARQUIVO_LOG, ARQUIVO_PEDIDOS, ARQUIVO_CLIENTES, ARQUIVO_HISTORICO,
    obter_preco_base, atualizar_preco_base
)
from database import (
    carregar_pedidos, carregar_clientes,
    salvar_pedidos, salvar_clientes,
    listar_backups, restaurar_backup, limpar_backups_por_data,
    importar_csv_externo
)
from sheets import (
    GSPREAD_AVAILABLE,
    conectar_google_sheets, obter_ou_criar_planilha,
    sincronizar_com_sheets, verificar_status_sheets,
    carregar_do_sheets, salvar_no_sheets,
    ler_hora_notificacao, salvar_hora_notificacao,
)


def render():
    """Renderiza a página de Manutenção."""
    st.title("🛠️ Manutenção do Sistema")

    t1, t2, t3, t4, t5, t6 = st.tabs(["📋 Logs", "📜 Histórico", "💾 Backups", "☁️ Google Sheets", "📱 Telegram", "⚙️ Config"])

    # ===== ABA 1: LOGS =====
    with t1:
        st.subheader("📋 Logs de Erro")
        if os.path.exists(ARQUIVO_LOG):
            with open(ARQUIVO_LOG, "r") as f:
                log = f.read()
            if log.strip():
                st.text_area("", log, height=300)
                if st.button("🗑️ Limpar Logs"):
                    with open(ARQUIVO_LOG, 'w') as f:
                        pass  # Apenas limpa o arquivo
                    st.success("✅ Logs limpos!")
                    st.rerun()
            else:
                st.success("✅ Sem erros registrados!")
        else:
            st.success("✅ Sem erros registrados!")

    # ===== ABA 2: HISTÓRICO =====
    with t2:
        st.subheader("📜 Histórico de Alterações")
        if os.path.exists(ARQUIVO_HISTORICO):
            try:
                df_hist = pd.read_csv(ARQUIVO_HISTORICO)
                df_hist = df_hist.sort_values('Timestamp', ascending=False)
                st.dataframe(df_hist, use_container_width=True, hide_index=True)

                csv_hist = df_hist.to_csv(index=False).encode('utf-8')
                st.download_button("📥 Exportar Histórico", csv_hist, "historico.csv", "text/csv")

                if st.button("🗑️ Limpar Histórico"):
                    os.remove(ARQUIVO_HISTORICO)
                    st.success("✅ Histórico limpo!")
                    st.rerun()
            except Exception as e:
                logger.warning(f"Erro ao carregar histórico de alterações: {e}")
                st.info("Histórico vazio ou corrompido.")
        else:
            st.info("Nenhuma alteração registrada ainda.")

    # ===== ABA 3: BACKUPS =====
    with t3:
        st.subheader("💾 Gerenciamento de Backups")

        # Informações sobre backups
        st.info("📂 **Localização dos Backups:** Mesma pasta do sistema (arquivos .bak)")

        # Abas internas para organizar funcionalidades
        tab_lista, tab_restaurar, tab_limpar, tab_importar = st.tabs([
            "📊 Listar", "🔄 Restaurar", "🧹 Limpar", "📤 Importar CSV"
        ])

        with tab_lista:
            st.markdown("### 📊 Backups Disponíveis")

            df_backups = listar_backups()

            if not df_backups.empty:
                # Formata para exibição
                df_display = df_backups.copy()
                df_display['Data/Hora'] = df_display['Data/Hora'].dt.strftime('%d/%m/%Y %H:%M:%S')
                df_display['Tamanho'] = df_display['Tamanho_KB'].apply(lambda x: f"{x:.1f} KB")

                st.dataframe(
                    df_display[['Arquivo', 'Origem', 'Data/Hora', 'Tamanho']],
                    use_container_width=True,
                    hide_index=True
                )

                st.caption(f"**Total:** {len(df_backups)} backup(s) | **Espaço:** {df_backups['Tamanho_KB'].sum():.1f} KB")
            else:
                st.info("Nenhum backup encontrado.")

        with tab_restaurar:
            st.markdown("### 🔄 Restaurar Backup")
            st.warning("⚠️ **Atenção:** Restaurar um backup substituirá os dados atuais!")

            df_backups = listar_backups()

            if not df_backups.empty:
                # Agrupa por arquivo de origem
                origens = df_backups['Origem'].unique().tolist()

                origem_selecionada = st.selectbox(
                    "1️⃣ Selecione o arquivo a restaurar:",
                    origens,
                    key="restaurar_origem"
                )

                if origem_selecionada:
                    # Filtra backups da origem selecionada
                    backups_origem = df_backups[df_backups['Origem'] == origem_selecionada]

                    # Formata opções
                    opcoes_backup = {}
                    for _, row in backups_origem.iterrows():
                        label = f"{row['Data/Hora'].strftime('%d/%m/%Y %H:%M:%S')} ({row['Tamanho_KB']:.1f} KB)"
                        opcoes_backup[label] = row['Caminho']

                    backup_selecionado_label = st.selectbox(
                        "2️⃣ Selecione a versão:",
                        opcoes_backup.keys(),
                        key="restaurar_versao"
                    )

                    if backup_selecionado_label:
                        backup_caminho = opcoes_backup[backup_selecionado_label]

                        st.divider()

                        st.markdown("**Resumo da Restauração:**")
                        st.write(f"- **Arquivo:** {origem_selecionada}")
                        st.write(f"- **Versão:** {backup_selecionado_label}")
                        st.write(f"- **Ação:** Um backup de segurança do arquivo atual será criado antes da restauração")

                        confirmar = st.checkbox(
                            "✅ Confirmo que desejo restaurar este backup",
                            key="confirmar_restaurar"
                        )

                        if st.button(
                            "🔄 RESTAURAR BACKUP",
                            type="primary",
                            disabled=not confirmar,
                            use_container_width=True
                        ):
                            sucesso, msg = restaurar_backup(backup_caminho, origem_selecionada)

                            if sucesso:
                                st.success(msg)
                                st.info("💡 Clique em 'Recarregar Dados' na aba Config para aplicar as mudanças")

                                # Botão para recarregar
                                if st.button("🔄 Recarregar Dados Agora", use_container_width=True):
                                    st.session_state.pedidos = carregar_pedidos()
                                    st.session_state.clientes = carregar_clientes()
                                    st.toast("Dados recarregados!", icon="✅")
                                    st.rerun()
                            else:
                                st.error(msg)
            else:
                st.info("Nenhum backup disponível para restaurar.")

        with tab_limpar:
            st.markdown("### 🧹 Limpeza de Backups Antigos")

            df_backups = listar_backups()

            if not df_backups.empty:
                st.write(f"**Backups atuais:** {len(df_backups)} arquivo(s)")

                dias = st.slider(
                    "Remover backups com mais de quantos dias?",
                    min_value=1,
                    max_value=90,
                    value=30,
                    help="Backups mais antigos que este período serão removidos"
                )

                # Calcula quantos seriam removidos
                limite = agora_brasil() - timedelta(days=dias)
                a_remover = df_backups[df_backups['Data/Hora'] < limite]

                st.info(f"📊 Serão removidos **{len(a_remover)}** backup(s) com mais de {dias} dia(s)")

                if len(a_remover) > 0:
                    st.dataframe(
                        a_remover[['Arquivo', 'Data/Hora', 'Tamanho_KB']],
                        use_container_width=True,
                        hide_index=True
                    )

                    confirmar_limpar = st.checkbox(
                        f"✅ Confirmo a remoção de {len(a_remover)} backup(s)",
                        key="confirmar_limpar"
                    )

                    if st.button(
                        "🧹 LIMPAR BACKUPS ANTIGOS",
                        type="primary",
                        disabled=not confirmar_limpar,
                        use_container_width=True
                    ):
                        sucesso, msg = limpar_backups_por_data(dias)
                        if sucesso:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)
                else:
                    st.success("✅ Nenhum backup antigo para remover!")
            else:
                st.info("Nenhum backup encontrado.")

        with tab_importar:
            st.markdown("### 📤 Importar CSV Externo")
            st.info("💡 Importe arquivos CSV de outras fontes para substituir os dados do sistema")

            destino = st.selectbox(
                "1️⃣ Selecione qual arquivo deseja substituir:",
                ["Pedidos", "Clientes", "Histórico"],
                key="importar_destino"
            )

            arquivo_upload = st.file_uploader(
                "2️⃣ Envie o arquivo CSV:",
                type="csv",
                key="importar_arquivo"
            )

            if arquivo_upload:
                try:
                    # Limite de tamanho: 5 MB
                    if getattr(arquivo_upload, 'size', 0) > 5 * 1024 * 1024:
                        st.error(f"❌ Arquivo muito grande ({arquivo_upload.size/1024/1024:.1f} MB). Limite: 5 MB.")
                        st.stop()

                    # Lê para preview
                    df_preview = pd.read_csv(arquivo_upload)
                    if len(df_preview) > 10_000:
                        st.error(f"❌ CSV com {len(df_preview):,} linhas excede o limite de 10.000.")
                        st.stop()

                    st.markdown("**📋 Preview do Arquivo:**")
                    st.write(f"- **Linhas:** {len(df_preview)}")
                    st.write(f"- **Colunas:** {', '.join(df_preview.columns.tolist())}")

                    st.dataframe(df_preview.head(10), use_container_width=True)

                    st.divider()

                    st.warning(f"⚠️ **Atenção:** O arquivo **{destino}** será substituído!")
                    st.info("✅ Um backup do arquivo atual será criado automaticamente")

                    confirmar_import = st.checkbox(
                        f"✅ Confirmo a importação de {len(df_preview)} registro(s)",
                        key="confirmar_importar"
                    )

                    if st.button(
                        "📤 IMPORTAR CSV",
                        type="primary",
                        disabled=not confirmar_import,
                        use_container_width=True
                    ):
                        # Reseta o ponteiro do arquivo
                        arquivo_upload.seek(0)

                        sucesso, msg, df_importado = importar_csv_externo(arquivo_upload, destino)

                        if sucesso:
                            st.success(msg)
                            st.info("💡 Clique em 'Recarregar Dados' para aplicar as mudanças")

                            # Botão para recarregar
                            if st.button("🔄 Recarregar Dados Agora", use_container_width=True, key="reload_import"):
                                st.session_state.pedidos = carregar_pedidos()
                                st.session_state.clientes = carregar_clientes()
                                st.toast("Dados recarregados!", icon="✅")
                                st.rerun()
                        else:
                            st.error(msg)

                except Exception as e:
                    st.error(f"❌ Erro ao ler arquivo: {e}")

    # ===== ABA 4: GOOGLE SHEETS =====
    with t4:
        st.subheader("☁️ Integração Google Sheets")

        st.info("""
        💡 **Por que usar Google Sheets?**
        - ✅ Seus dados ficam seguros na nuvem do Google
        - ✅ Não perde dados quando o Streamlit reinicia
        - ✅ Backup automático do Google (30 dias de histórico)
        - ✅ Acesse e edite dados direto no Google Sheets
        - ✅ Gratuito e confiável
        """)

        # Verifica status
        status_ok, status_msg = verificar_status_sheets()

        if status_ok:
            st.success(status_msg)
        else:
            st.warning(status_msg)

        st.divider()

        # Abas de funcionalidades
        tab_sync, tab_manual, tab_config = st.tabs(["🔄 Sincronização", "📤 Manual", "⚙️ Configurar"])

        with tab_sync:
            st.markdown("### 🔄 Sincronização - Backup para Nuvem")

            if not status_ok:
                st.error("❌ Configure as credenciais primeiro na aba '⚙️ Configurar'")
            else:
                st.info("""
                💡 **Recomendação:** Use apenas **Enviar para Sheets** para fazer backup.

                ⚠️ **Evite usar "Baixar" ou "Ambos"** para não perder dados locais.
                """)

                col1, col2 = st.columns(2)

                with col1:
                    if st.button("📤 Enviar para Sheets (Backup)", use_container_width=True, type="primary"):
                        with st.spinner("Enviando dados..."):
                            sucesso, msg = sincronizar_com_sheets(modo="enviar")
                            if sucesso:
                                st.toast("Backup realizado com sucesso!", icon="☁️")
                                st.success(msg)
                            else:
                                st.error(msg)

                with col2:
                    if st.button("📥 Baixar do Sheets ⚠️", use_container_width=True):
                        st.warning("⚠️ **ATENÇÃO:** Isso substituirá seus dados locais!")
                        confirmar_download = st.checkbox("Confirmo que quero sobrescrever dados locais")

                        if confirmar_download and st.button("✅ CONFIRMAR DOWNLOAD"):
                            with st.spinner("Baixando dados..."):
                                sucesso, msg = sincronizar_com_sheets(modo="receber")
                                if sucesso:
                                    st.toast("Dados restaurados do Google Sheets!", icon="☁️")
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)

                st.divider()

                st.markdown("**💡 Quando usar:**")
                st.write("- **📤 Enviar:** Após fazer mudanças importantes (RECOMENDADO)")
                st.write("- **📥 Baixar:** Apenas para restaurar em caso de problema local")

        with tab_manual:
            st.markdown("### 📤 Operações Manuais")

            if not status_ok:
                st.error("❌ Configure as credenciais primeiro")
            else:
                st.markdown("#### Enviar Dados Específicos")

                tipo_envio = st.selectbox(
                    "Selecione o que deseja enviar:",
                    ["Pedidos", "Clientes", "Ambos"]
                )

                if st.button("📤 Enviar Selecionado", use_container_width=True):
                    try:
                        client = conectar_google_sheets()
                        if client:
                            if tipo_envio in ["Pedidos", "Ambos"]:
                                sucesso, msg = salvar_no_sheets(client, "Pedidos", st.session_state.pedidos)
                                st.info(msg)

                            if tipo_envio in ["Clientes", "Ambos"]:
                                sucesso, msg = salvar_no_sheets(client, "Clientes", st.session_state.clientes)
                                st.info(msg)

                            st.success("✅ Operação concluída!")
                        else:
                            st.error("❌ Erro ao conectar")
                    except Exception as e:
                        st.error(f"❌ Erro: {e}")

                st.divider()

                st.markdown("#### Baixar Dados Específicos")

                tipo_download = st.selectbox(
                    "Selecione o que deseja baixar:",
                    ["Pedidos", "Clientes"],
                    key="download_tipo"
                )

                if st.button("📥 Baixar Selecionado", use_container_width=True):
                    try:
                        client = conectar_google_sheets()
                        if client:
                            if tipo_download == "Pedidos":
                                df, msg = carregar_do_sheets(client, "Pedidos")
                                if df is not None and not df.empty:
                                    st.dataframe(df.head(10), use_container_width=True)
                                    st.info(msg)

                                    if st.button("✅ Confirmar e Aplicar"):
                                        if not salvar_pedidos(df):
                                            st.error("❌ ERRO: Não foi possível restaurar pedidos. Tente novamente.")
                                        else:
                                            st.session_state.pedidos = carregar_pedidos()
                                            st.success("✅ Pedidos restaurados!")
                                            st.rerun()

                            elif tipo_download == "Clientes":
                                df, msg = carregar_do_sheets(client, "Clientes")
                                if df is not None and not df.empty:
                                    st.dataframe(df.head(10), use_container_width=True)
                                    st.info(msg)

                                    if st.button("✅ Confirmar e Aplicar", key="aplicar_clientes"):
                                        if not salvar_clientes(df):
                                            st.error("❌ ERRO: Não foi possível restaurar clientes. Tente novamente.")
                                        else:
                                            st.session_state.clientes = carregar_clientes()
                                            st.success("✅ Clientes restaurados!")
                                            st.rerun()
                        else:
                            st.error("❌ Erro ao conectar")
                    except Exception as e:
                        st.error(f"❌ Erro: {e}")

        with tab_config:
            st.markdown("### ⚙️ Configuração")

            st.markdown("""
            **📋 Passo a Passo para Configurar:**

            1. **Criar Projeto no Google Cloud**
            2. **Ativar APIs necessárias**
            3. **Criar Service Account**
            4. **Baixar credenciais JSON**
            5. **Adicionar credenciais no Streamlit Secrets**

            👉 **Tutorial completo será fornecido após o commit!**
            """)

            st.divider()

            st.markdown("**🔍 Status Atual:**")

            if GSPREAD_AVAILABLE:
                st.success("✅ Biblioteca gspread instalada")
            else:
                st.error("❌ Biblioteca gspread não instalada")
                st.code("pip install gspread google-auth")

            if "gcp_service_account" in st.secrets:
                st.success("✅ Credenciais configuradas")

                # Mostra informações (sem expor dados sensíveis)
                try:
                    creds = dict(st.secrets["gcp_service_account"])
                    st.write(f"- **Project ID:** {creds.get('project_id', 'N/A')}")
                    st.write(f"- **Client Email:** {creds.get('client_email', 'N/A')}")
                except Exception as e:
                    logger.debug(f"Erro ao exibir detalhes das credenciais: {e}")
            else:
                st.warning("⚠️ Credenciais não configuradas")
                st.info("Adicione as credenciais em `.streamlit/secrets.toml`")

            st.divider()

            # Link para a planilha
            if status_ok:
                try:
                    client = conectar_google_sheets()
                    if client:
                        spreadsheet = obter_ou_criar_planilha(client)
                        if spreadsheet:
                            st.markdown(f"**📊 Sua Planilha:**")
                            st.markdown(f"[🔗 Abrir no Google Sheets](https://docs.google.com/spreadsheets/d/{spreadsheet.id})")
                except Exception as e:
                    logger.debug(f"Erro ao exibir link da planilha: {e}")

    # ===== ABA 5: TELEGRAM =====
    with t5:
        st.subheader("📱 Integração Telegram")

        # Helpers
        def _telegram_secrets():
            """Retorna (token, chat_id) dos secrets ou (None, None)."""
            try:
                tok = st.secrets.get("TELEGRAM_BOT_TOKEN") or st.secrets.get("telegram", {}).get("bot_token")
                cid = st.secrets.get("TELEGRAM_CHAT_ID") or st.secrets.get("telegram", {}).get("chat_id")
                return (tok or "").strip(), (cid or "").strip()
            except Exception:
                return "", ""

        def _enviar_telegram(token: str, chat_id: str, texto: str) -> tuple[bool, str]:
            try:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                resp = requests.post(url, json={"chat_id": chat_id, "text": texto, "parse_mode": "Markdown"}, timeout=15)
                if resp.status_code == 200:
                    return True, "Mensagem enviada!"
                try:
                    desc = resp.json().get("description", resp.text)
                except Exception:
                    desc = resp.text
                return False, f"HTTP {resp.status_code}: {desc}"
            except requests.Timeout:
                return False, "Timeout — Telegram não respondeu em 15s."
            except Exception as e:
                return False, str(e)

        tok, cid = _telegram_secrets()
        telegram_ok = bool(tok and cid)

        st.info("""
        💡 **Para que serve?**
        - ✅ Teste a conexão com o seu bot Telegram
        - ✅ Envie a lista de pedidos manualmente (sem esperar o cron do GitHub Actions)
        - ✅ Dispare notificações para hoje ou amanhã com um clique
        """)

        st.divider()

        # Status
        st.markdown("**🔍 Status da Configuração:**")

        if telegram_ok:
            st.success(f"✅ TELEGRAM_BOT_TOKEN — configurado")
            st.success(f"✅ TELEGRAM_CHAT_ID — {cid}")
        else:
            if not tok:
                st.error("❌ TELEGRAM_BOT_TOKEN não encontrado nos secrets")
            if not cid:
                st.error("❌ TELEGRAM_CHAT_ID não encontrado nos secrets")

            st.divider()
            st.markdown("### ⚙️ Como Configurar")
            st.markdown("""
            Adicione as linhas abaixo no arquivo `.streamlit/secrets.toml` do seu projeto:

            ```toml
            TELEGRAM_BOT_TOKEN = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
            TELEGRAM_CHAT_ID   = "-1001234567890"
            ```

            **Onde obter esses valores:**
            1. **Bot Token:** Fale com [@BotFather](https://t.me/BotFather) no Telegram → `/newbot` → copie o token
            2. **Chat ID:** Adicione o bot ao grupo/canal → use [@userinfobot](https://t.me/userinfobot) para obter o ID

            > Se estiver no Streamlit Cloud, adicione em **App settings → Secrets**.
            """)

        if telegram_ok:
            st.divider()
            tab_notif, tab_teste, tab_horario = st.tabs(["📤 Enviar Notificação", "🧪 Testar Conexão", "⏰ Horário Automático"])

            with tab_teste:
                st.markdown("### 🧪 Teste de Conexão")
                msg_teste = st.text_input(
                    "Mensagem de teste:",
                    value="🍛 Cantinho do Caruru — teste de conexão Telegram ✅",
                    key="telegram_msg_teste"
                )
                if st.button("📤 Enviar Mensagem de Teste", use_container_width=True):
                    with st.spinner("Enviando..."):
                        ok, msg = _enviar_telegram(tok, cid, msg_teste)
                    if ok:
                        st.success(f"✅ {msg}")
                        st.toast("Mensagem enviada!", icon="📱")
                    else:
                        st.error(f"❌ {msg}")

            with tab_horario:
                st.markdown("### ⏰ Horário da Notificação Automática")
                st.info(
                    "Define em que horário (Brasília) o GitHub Actions envia o resumo diário.\n\n"
                    "O sistema verifica a cada hora entre **04:00 e 12:00 (Brasília)** e só envia "
                    "quando o horário bate com o configurado aqui."
                )

                status_ok_sheets, _ = verificar_status_sheets()
                if not status_ok_sheets:
                    st.warning("⚠️ Configure o Google Sheets primeiro — o horário é salvo lá.")
                else:
                    client_sheets = conectar_google_sheets()
                    if client_sheets:
                        hora_salva = ler_hora_notificacao(client_sheets)

                        horas_disponiveis = list(range(4, 13))  # 4h a 12h Brasília
                        idx_atual = horas_disponiveis.index(hora_salva) if hora_salva in horas_disponiveis else 3

                        hora_nova = st.selectbox(
                            "Horário de envio (Brasília):",
                            options=horas_disponiveis,
                            format_func=lambda h: f"{h:02d}:00",
                            index=idx_atual,
                            key="telegram_hora_notif",
                        )

                        st.caption(f"Configuração atual: **{hora_salva:02d}:00 (Brasília)**")

                        if st.button("💾 Salvar Horário", type="primary", use_container_width=True, key="btn_salvar_horario"):
                            ok_h, msg_h = salvar_hora_notificacao(client_sheets, hora_nova)
                            if ok_h:
                                st.success(msg_h)
                                st.toast(f"⏰ Notificações agendadas para {hora_nova:02d}:00 Brasília", icon="⏰")
                            else:
                                st.error(msg_h)
                    else:
                        st.error("❌ Não foi possível conectar ao Google Sheets")

            with tab_notif:
                st.markdown("### 📤 Enviar Notificação de Pedidos")

                hoje = hoje_brasil()
                amanha = hoje + timedelta(days=1)

                if "telegram_data_escolha" not in st.session_state:
                    st.session_state["telegram_data_escolha"] = amanha

                def _set_telegram_hoje():
                    st.session_state["telegram_data_escolha"] = hoje_brasil()

                def _set_telegram_amanha():
                    st.session_state["telegram_data_escolha"] = hoje_brasil() + timedelta(days=1)

                data_alvo = st.date_input(
                    "📅 Pedidos de qual data?",
                    format="DD/MM/YYYY",
                    key="telegram_data_escolha",
                    help="Selecione a data dos pedidos que deseja enviar. Por padrão, mostra os pedidos de amanhã."
                )

                col_h, col_a = st.columns(2)
                with col_h:
                    st.button(
                        "📍 Hoje",
                        use_container_width=True,
                        key="btn_telegram_hoje",
                        on_click=_set_telegram_hoje,
                    )
                with col_a:
                    st.button(
                        "➡️ Amanhã",
                        use_container_width=True,
                        key="btn_telegram_amanha",
                        on_click=_set_telegram_amanha,
                    )

                with st.expander("🔍 Diagnóstico da notificação automática"):
                    hora_atual_br = agora_brasil().hour
                    hora_atual_str = agora_brasil().strftime("%H:%M")
                    status_sheets_diag, _ = verificar_status_sheets()
                    hora_notif_diag = 7
                    df_sheets_diag = None

                    if status_sheets_diag:
                        client_diag = conectar_google_sheets()
                        if client_diag:
                            hora_notif_diag = ler_hora_notificacao(client_diag)
                            df_sheets_diag, _ = carregar_do_sheets(client_diag, "Pedidos")

                    col_d1, col_d2 = st.columns(2)
                    with col_d1:
                        st.metric("⏰ Hora configurada", f"{hora_notif_diag:02d}:00 Brasília")
                    with col_d2:
                        st.metric("🕐 Hora atual", f"{hora_atual_str} Brasília")

                    if hora_atual_br == hora_notif_diag:
                        st.success("✅ Horário atual coincide — o cron enviaria neste momento.")
                    else:
                        st.info(f"⏳ O cron enviará quando forem {hora_notif_diag:02d}:00 Brasília.")

                    st.markdown(f"**📦 Pedidos para {data_alvo.strftime('%d/%m/%Y')} no Google Sheets:**")
                    if not status_sheets_diag:
                        st.warning("⚠️ Google Sheets não conectado — não é possível verificar.")
                    elif df_sheets_diag is None:
                        st.error("❌ Falha ao conectar ao Sheets.")
                    elif df_sheets_diag.empty:
                        st.warning("⚠️ Sheets está vazio — sincronize os dados primeiro.")
                    else:
                        try:
                            df_diag = df_sheets_diag[df_sheets_diag["Data"] == data_alvo]
                            df_diag = df_diag[~df_diag["Status"].str.contains("Entregue|Cancelado", na=False)]
                            if df_diag.empty:
                                st.warning(
                                    f"⚠️ Nenhum pedido encontrado no Sheets para "
                                    f"{data_alvo.strftime('%d/%m/%Y')} — o cron **não enviará** mensagem."
                                )
                            else:
                                st.success(
                                    f"✅ {len(df_diag)} pedido(s) no Sheets para esta data "
                                    f"— o cron enviará normalmente."
                                )
                                for _, r in df_diag.iterrows():
                                    nome = str(r.get("Cliente", "?")).strip().title()
                                    st.caption(f"→ {nome}")
                        except Exception as _e:
                            st.error(f"Erro ao filtrar pedidos do Sheets: {_e}")

                    st.markdown(
                        "🔗 [Ver histórico de execuções no GitHub Actions]"
                        "(https://github.com/radbrse/caruru/actions/workflows/notificar_pedidos.yml)"
                    )

                df = st.session_state.pedidos
                if df.empty:
                    st.warning("Nenhum pedido carregado.")
                else:
                    try:
                        df_filtrado = df[df["Data"] == data_alvo]
                        df_filtrado = df_filtrado[~df_filtrado["Status"].str.contains("Entregue|Cancelado", na=False)]
                    except Exception:
                        df_filtrado = pd.DataFrame()

                    st.info(f"📦 {len(df_filtrado)} pedido(s) para {data_alvo.strftime('%d/%m/%Y')}")

                    dias_pt = {
                        "Monday": "segunda-feira", "Tuesday": "terça-feira",
                        "Wednesday": "quarta-feira", "Thursday": "quinta-feira",
                        "Friday": "sexta-feira", "Saturday": "sábado", "Sunday": "domingo",
                    }
                    dia_sem = dias_pt.get(data_alvo.strftime("%A"), data_alvo.strftime("%A"))
                    data_fmt = f"{data_alvo.strftime('%d/%m/%Y')} ({dia_sem})"

                    if df_filtrado.empty:
                        preview = (
                            f"🍛 *Cantinho do Caruru*\n\n"
                            f"📅 {data_fmt}\n\n"
                            f"📭 Nenhum pedido cadastrado para esta data."
                        )
                    else:
                        total_c = int(df_filtrado.get("Caruru", pd.Series(dtype=float)).fillna(0).astype(float).sum())
                        total_b = int(df_filtrado.get("Bobo", pd.Series(dtype=float)).fillna(0).astype(float).sum())
                        total_v = df_filtrado.get("Valor", pd.Series(dtype=float)).fillna(0).astype(float).sum()

                        def _brl(v: float) -> str:
                            return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

                        def _falta_row(row) -> float:
                            pag = str(row.get("Pagamento", "")).strip().upper()
                            v = float(row.get("Valor") or 0)
                            if pag == "NÃO PAGO": return v
                            if pag == "METADE":   return v / 2
                            return 0.0

                        total_pendente = sum(_falta_row(r) for _, r in df_filtrado.iterrows())

                        linhas = []
                        for _, p in df_filtrado.iterrows():
                            nome = str(p.get("Cliente", "?")).strip().title()
                            qc = int(float(p.get("Caruru") or 0))
                            qb = int(float(p.get("Bobo") or 0))
                            itens = []
                            if qc: itens.append(f"{qc} kg de Caruru")
                            if qb: itens.append(f"{qb} kg de Bobó")
                            hora = str(p.get("Hora", "")).strip()
                            hora_fmt = hora[:5] if hora and hora != "nan" and len(hora) >= 5 else hora
                            hora_str = f"  ⏰ {hora_fmt}" if hora_fmt and hora_fmt != "nan" else ""
                            flags = []
                            if str(p.get("Extra", "")).strip().lower() in ("true", "1", "sim"): flags.append("⚡ Extra")
                            if str(p.get("Vegano", "")).strip().lower() in ("true", "1", "sim"): flags.append("🌿 Vegano")
                            if str(p.get("Delivery", "")).strip().lower() in ("true", "1", "sim"): flags.append("🛵 Delivery")
                            falta = _falta_row(p)
                            if falta > 0:
                                pag = str(p.get("Pagamento", "")).strip().upper()
                                pag_label = f"{'💸' if pag == 'NÃO PAGO' else '🔸'} Falta {_brl(falta)}"
                            else:
                                pag_label = "✅ Pedido pago"
                            linha1 = f"• *{nome}*{hora_str}"
                            detalhes = itens + flags + [pag_label]
                            linha2 = "  " + "  ".join(detalhes)
                            linhas.append(f"{linha1}\n{linha2}")

                        preview = (
                            f"🍛 *Cantinho do Caruru*\n\n"
                            f"📅 Pedidos: *{data_fmt}*\n\n"
                            f"📦 *{len(df_filtrado)} pedido(s)*\n"
                            f"🥘 Caruru: *{total_c} kg*  |  🦐 Bobó: *{total_b} kg*\n"
                            f"💰 Total: *{_brl(total_v)}*\n"
                            + (f"💸 A receber: *{_brl(total_pendente)}*\n" if total_pendente > 0 else "")
                            + f"\n👥 *Clientes:*\n" + "\n\n".join(linhas)
                        )

                    with st.expander("👁️ Preview da mensagem", expanded=True):
                        st.text(preview)

                    if st.button("📤 Enviar para Telegram", type="primary", use_container_width=True):
                        with st.spinner("Enviando..."):
                            ok, msg = _enviar_telegram(tok, cid, preview)
                        if ok:
                            st.success("✅ Notificação enviada com sucesso!")
                            st.toast("Notificação enviada!", icon="📱")
                        else:
                            st.error(f"❌ {msg}")

    # ===== ABA 6: CONFIGURAÇÕES =====
    with t6:
        st.subheader("⚙️ Configurações")

        st.write("**Informações do Sistema:**")
        st.write(f"- Versão: {VERSAO}")
        st.write(f"- Pedidos cadastrados: {len(st.session_state.pedidos)}")
        st.write(f"- Clientes cadastrados: {len(st.session_state.clientes)}")
        st.write(f"- Chave PIX: {CHAVE_PIX}")

        st.divider()

        # Seção de alteração de preço base
        st.write("### 💰 Preço Base dos Produtos")

        preco_atual = obter_preco_base()
        st.info(f"**Preço base atual:** R$ {preco_atual:.2f}")

        st.markdown("""
        💡 **Dica:** Altere o preço base quando necessário. Todos os pedidos novos usarão o novo preço.
        Pedidos já criados manterão o valor calculado no momento da criação.
        """)

        col_preco1, col_preco2 = st.columns([3, 1])

        with col_preco1:
            novo_preco = st.number_input(
                "Novo preço base (R$)",
                min_value=0.01,
                max_value=1000.0,
                value=preco_atual,
                step=5.0,
                format="%.2f",
                key="input_novo_preco"
            )

        with col_preco2:
            st.write("")  # Espaçamento
            st.write("")  # Espaçamento
            if st.button("💾 Salvar Preço", use_container_width=True, type="primary"):
                if abs(novo_preco - preco_atual) < 0.01:
                    st.warning("⚠️ O preço não foi alterado")
                else:
                    sucesso, mensagem = atualizar_preco_base(novo_preco)
                    if sucesso:
                        st.success(mensagem)
                        st.toast(f"💰 Preço atualizado para R$ {novo_preco:.2f}", icon="💰")
                        time_module.sleep(1)
                        st.rerun()
                    else:
                        st.error(mensagem)

        st.divider()

        st.write("**Arquivos:**")
        arquivos = [ARQUIVO_PEDIDOS, ARQUIVO_CLIENTES, ARQUIVO_HISTORICO, ARQUIVO_LOG]
        for arq in arquivos:
            if os.path.exists(arq):
                tamanho = os.path.getsize(arq) / 1024
                st.write(f"- ✅ {arq} ({tamanho:.1f} KB)")
            else:
                st.write(f"- ❌ {arq} (não existe)")

        st.divider()

        if st.button("🔄 Recarregar Dados", use_container_width=True):
            st.session_state.pedidos = carregar_pedidos()
            st.session_state.clientes = carregar_clientes()
            st.success("✅ Dados recarregados!")
            st.rerun()
