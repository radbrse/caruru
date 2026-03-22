#!/usr/bin/env python3
"""
Script de migração para adicionar coluna Hora_Entrega aos pedidos existentes.
Execute este script apenas UMA vez para atualizar dados antigos.
"""

import pandas as pd
import os
import shutil
from datetime import datetime

ARQUIVO_PEDIDOS = "pedidos.csv"

def migrar_pedidos():
    """Adiciona coluna Hora_Entrega aos pedidos existentes."""

    if not os.path.exists(ARQUIVO_PEDIDOS):
        print(f"✅ Nenhum arquivo {ARQUIVO_PEDIDOS} encontrado. Nada a migrar.")
        return True

    print(f"📂 Arquivo {ARQUIVO_PEDIDOS} encontrado. Iniciando migração...")

    try:
        # Criar backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{ARQUIVO_PEDIDOS}.backup_{timestamp}.csv"
        shutil.copy(ARQUIVO_PEDIDOS, backup_file)
        print(f"💾 Backup criado: {backup_file}")

        # Carregar dados
        df = pd.read_csv(ARQUIVO_PEDIDOS)
        print(f"📊 Total de pedidos: {len(df)}")

        # Verificar se coluna já existe
        if 'Hora_Entrega' in df.columns:
            print("ℹ️ Coluna 'Hora_Entrega' já existe. Nada a fazer.")
            return True

        # Adicionar coluna Hora_Entrega vazia
        df['Hora_Entrega'] = ""

        # Salvar
        df.to_csv(ARQUIVO_PEDIDOS, index=False)
        print(f"✅ Migração concluída! Coluna 'Hora_Entrega' adicionada a {len(df)} pedidos.")
        print(f"💡 Dica: Os próximos pedidos marcados como 'Entregue' terão o horário de entrega registrado automaticamente.")

        return True

    except Exception as e:
        print(f"❌ Erro na migração: {e}")
        print(f"⚠️ Restaure o backup se necessário: {backup_file}")
        return False

if __name__ == "__main__":
    print("="*60)
    print("🔄 MIGRAÇÃO: Adicionar coluna Hora_Entrega")
    print("="*60)

    sucesso = migrar_pedidos()

    print("="*60)
    if sucesso:
        print("✅ Migração finalizada com sucesso!")
    else:
        print("❌ Migração falhou. Verifique os erros acima.")
    print("="*60)
