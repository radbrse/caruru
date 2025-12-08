# =================================================================================
# PÁGINA: GERENCIAR TUDO
# =================================================================================
elif menu == "Gerenciar Tudo":
    st.title("📦 Todos os Pedidos")
    
    df = st.session_state.pedidos
    
    if not df.empty:
        # 🔧 CORREÇÃO CRÍTICA: Remove linhas vazias e garante valores válidos
        df = df[df['Cliente'].astype(str).str.strip() != ''].copy()
        
        # 🔧 CORREÇÃO: Preenche Data e Hora com valores padrão (evita None)
        df['Data'] = df['Data'].fillna(date.today())
        df['Hora'] = df['Hora'].apply(lambda x: x if x is not None else time(12, 0))
        
        # Ordenação
        try:
            df['Hora_Sort'] = df['Hora']
            df = df.sort_values(by=["Data", "Hora_Sort"], ascending=[True, True]).drop(columns=['Hora_Sort'])
        except:
            df = df.sort_values(by="Data", ascending=True)
        
        df_editado = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "Valor": st.column_config.NumberColumn("Valor Total", format="R$ %.2f", disabled=True),
                "Data": st.column_config.DateColumn("Data", format="DD/MM/YYYY", required=True),  # ← Adicionado required
                "Hora": st.column_config.TimeColumn("Hora", format="HH:mm", required=True),       # ← Adicionado required
                "Status": st.column_config.SelectboxColumn(options=OPCOES_STATUS, required=True),
                "Pagamento": st.column_config.SelectboxColumn(options=OPCOES_PAGAMENTO, required=True),
                "Caruru": st.column_config.NumberColumn(format="%d", step=1),
                "Bobo": st.column_config.NumberColumn(format="%d", step=1),
                "Observacoes": st.column_config.TextColumn("Obs", width="large"),
            },
            hide_index=True
        )
        
        if not df_editado.equals(df):
            preco_base = 70.0
            df_editado['Valor'] = ((df_editado['Caruru'] * preco_base) + (df_editado['Bobo'] * preco_base)) * (1 - (df_editado['Desconto'] / 100))
            
            st.session_state.pedidos = df_editado
            salvar_pedidos(df_editado)
            st.toast("Salvo!", icon="💾")
            st.rerun()
