#!/usr/bin/env python3
"""
Script para adicionar coluna Hora_Entrega no Google Sheets.
Execute este script uma vez para atualizar a estrutura da planilha.
"""

import streamlit as st
import sys

def adicionar_coluna_hora_entrega():
    """Adiciona coluna Hora_Entrega na planilha do Google Sheets."""

    print("="*70)
    print("🔧 Adicionando coluna 'Hora_Entrega' no Google Sheets")
    print("="*70)

    try:
        from sheets import conectar_google_sheets, obter_ou_criar_planilha

        # Conectar ao Sheets
        print("\n📡 Conectando ao Google Sheets...")
        client = conectar_google_sheets()
        if not client:
            print("❌ Erro: Não foi possível conectar ao Google Sheets")
            print("   Verifique se as credenciais estão configuradas corretamente.")
            return False

        print("✅ Conectado com sucesso!")

        # Obter planilha
        print("\n📋 Acessando planilha...")
        spreadsheet = obter_ou_criar_planilha(client, "Cantinho do Caruru - Dados")
        if not spreadsheet:
            print("❌ Erro: Não foi possível acessar a planilha")
            return False

        print(f"✅ Planilha encontrada: {spreadsheet.title}")

        # Acessar aba de Pedidos
        print("\n📝 Acessando aba 'Pedidos'...")
        try:
            worksheet = spreadsheet.worksheet("Pedidos")
            print("✅ Aba 'Pedidos' encontrada")
        except Exception as e:
            print(f"❌ Erro: Aba 'Pedidos' não encontrada - {e}")
            return False

        # Verificar estrutura atual
        print("\n🔍 Verificando estrutura atual...")
        headers = worksheet.row_values(1)
        print(f"   Colunas atuais: {headers}")

        # Verificar se Hora_Entrega já existe
        if 'Hora_Entrega' in headers:
            print("\n✅ Coluna 'Hora_Entrega' JÁ EXISTE!")
            print("   Nada a fazer.")
            return True

        # Encontrar posição para inserir (após "Hora")
        try:
            pos_hora = headers.index('Hora') + 1  # Posição após "Hora"
            print(f"\n📍 Inserindo 'Hora_Entrega' na posição {pos_hora + 1} (após 'Hora')")
        except ValueError:
            print("⚠️ Coluna 'Hora' não encontrada, adicionando no final")
            pos_hora = len(headers)

        # Inserir coluna
        print("\n➕ Adicionando coluna 'Hora_Entrega'...")
        worksheet.insert_cols([[]], col=pos_hora + 1, value_input_option='RAW')

        # Atualizar cabeçalho
        worksheet.update_cell(1, pos_hora + 1, 'Hora_Entrega')
        print("✅ Coluna 'Hora_Entrega' adicionada com sucesso!")

        # Verificar resultado
        print("\n🔍 Verificando resultado...")
        headers_novos = worksheet.row_values(1)
        print(f"   Colunas atualizadas: {headers_novos}")

        if 'Hora_Entrega' in headers_novos:
            print("\n" + "="*70)
            print("✅ SUCESSO! Coluna 'Hora_Entrega' adicionada ao Google Sheets")
            print("="*70)
            print("\n📌 Próximos passos:")
            print("   1. ✅ A planilha está atualizada")
            print("   2. 🔄 Reinicie o app Streamlit")
            print("   3. ✅ Os pedidos entregues aparecerão no histórico")
            print("   4. ✅ Novos pedidos terão horário de entrega capturado")
            return True
        else:
            print("\n❌ ERRO: Coluna não foi adicionada corretamente")
            return False

    except ImportError as e:
        print(f"\n❌ Erro: Bibliotecas necessárias não encontradas - {e}")
        print("   Execute este script dentro do ambiente do Streamlit:")
        print("   streamlit run adicionar_coluna_sheets.py")
        return False
    except Exception as e:
        print(f"\n❌ Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Se executado diretamente (não via Streamlit)
    if 'streamlit' not in sys.modules:
        print("⚠️ Este script deve ser executado via Streamlit:")
        print("   streamlit run adicionar_coluna_sheets.py")
        print("\nOu adicione a coluna manualmente no Google Sheets:")
        print("   1. Abra: https://docs.google.com/spreadsheets/d/1JpDwh45CyXmHHqbs1byl_GCl-Dw1ewy_k3yg9C240/edit")
        print("   2. Clique com botão direito na coluna 'H' (Status)")
        print("   3. Escolha 'Inserir 1 coluna à esquerda'")
        print("   4. Na nova coluna G, linha 1, digite: Hora_Entrega")
        sys.exit(1)

    # Se executado via Streamlit
    st.title("🔧 Adicionar Coluna Hora_Entrega")
    st.info("Este script adiciona a coluna 'Hora_Entrega' na planilha do Google Sheets.")

    if st.button("▶️ Executar", type="primary"):
        with st.spinner("Processando..."):
            sucesso = adicionar_coluna_hora_entrega()

        if sucesso:
            st.success("✅ Coluna adicionada com sucesso!")
            st.balloons()
        else:
            st.error("❌ Erro ao adicionar coluna. Veja os detalhes acima.")
