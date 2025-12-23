#!/usr/bin/env python3
"""
Script de Diagnóstico de Datas
Identifica problemas de formato de data nos pedidos
"""

import pandas as pd
from datetime import date, datetime

# Carrega o arquivo CSV
df = pd.read_csv('banco_de_dados_caruru.csv', dtype={'Contato': str})

print("=" * 80)
print("🔍 DIAGNÓSTICO DE DATAS - PEDIDOS DO DIA 24/12/2025")
print("=" * 80)
print()

# 1. Total de pedidos
print(f"📊 Total de pedidos no banco: {len(df)}")
print()

# 2. Converte datas
print("🔄 Convertendo datas...")
df["Data_Original"] = df["Data"].copy()  # Guarda original
df["Data"] = pd.to_datetime(df["Data"], errors="coerce").dt.date

# 3. Verifica datas inválidas
datas_invalidas = df[df["Data"].isna()]
if len(datas_invalidas) > 0:
    print(f"⚠️  {len(datas_invalidas)} pedidos com data INVÁLIDA:")
    for idx, row in datas_invalidas.iterrows():
        print(f"   ID {row['ID_Pedido']}: '{row['Data_Original']}' (Cliente: {row['Cliente']})")
    print()

# 4. Filtra por 24/12/2025
data_natal = date(2025, 12, 24)
df_natal = df[df["Data"] == data_natal]

print(f"🎄 Pedidos para 24/12/2025: {len(df_natal)}")
print()

# 5. Agrupa por Status
print("📋 Distribuição por Status:")
status_counts = df_natal.groupby('Status').size()
for status, count in status_counts.items():
    print(f"   {status}: {count} pedidos")
print()

# 6. Calcula totais
total_caruru = df_natal['Caruru'].astype(float).sum()
total_bobo = df_natal['Bobo'].astype(float).sum()
total_valor = df_natal['Valor'].astype(float).sum()

print("💰 Totais para 24/12/2025:")
print(f"   Caruru: {total_caruru} kg")
print(f"   Bobó: {total_bobo} kg")
print(f"   Valor: R$ {total_valor:,.2f}")
print()

# 7. Filtra apenas PENDENTES (sem entregues)
df_pendentes = df_natal[df_natal['Status'] != "✅ Entregue"]
total_caruru_pend = df_pendentes['Caruru'].astype(float).sum()
total_bobo_pend = df_pendentes['Bobo'].astype(float).sum()
total_valor_pend = df_pendentes['Valor'].astype(float).sum()

print("📦 Totais PENDENTES (excluindo entregues):")
print(f"   Pedidos: {len(df_pendentes)}")
print(f"   Caruru: {total_caruru_pend} kg")
print(f"   Bobó: {total_bobo_pend} kg")
print(f"   Valor: R$ {total_valor_pend:,.2f}")
print()

# 8. Mostra diferença
if len(df_natal) != len(df_pendentes):
    diff_pedidos = len(df_natal) - len(df_pendentes)
    diff_caruru = total_caruru - total_caruru_pend
    diff_bobo = total_bobo - total_bobo_pend
    diff_valor = total_valor - total_valor_pend

    print("🔍 Diferença (ENTREGUES):")
    print(f"   Pedidos: {diff_pedidos}")
    print(f"   Caruru: {diff_caruru} kg")
    print(f"   Bobó: {diff_bobo} kg")
    print(f"   Valor: R$ {diff_valor:,.2f}")
    print()

    print("✅ Pedidos ENTREGUES do dia 24/12:")
    df_entregues = df_natal[df_natal['Status'] == "✅ Entregue"]
    for idx, row in df_entregues.iterrows():
        print(f"   ID {row['ID_Pedido']}: {row['Cliente']} - {row['Caruru']}kg Caruru + {row['Bobo']}kg Bobó = R$ {row['Valor']}")
    print()

# 9. Verifica tipos de data
print("🔍 Análise de Tipos de Data:")
tipos_unicos = df["Data"].apply(type).unique()
print(f"   Tipos encontrados: {tipos_unicos}")
print()

# 10. Pedidos com data alterada recentemente
print("📝 Últimas alterações de data:")
print("   (Verificando pedidos que podem ter sido editados)")
df_datas = df.copy()
df_datas = df_datas.sort_values('ID_Pedido', ascending=False)
print("   Últimos 10 pedidos cadastrados:")
for idx, row in df_datas.head(10).iterrows():
    print(f"   ID {row['ID_Pedido']}: {row['Cliente']} - Data: {row['Data']}")
print()

print("=" * 80)
print("✅ Diagnóstico concluído!")
print("=" * 80)
