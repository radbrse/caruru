"""
CRUD de pedidos e sincronização de dados de clientes.
"""

import streamlit as st
import pandas as pd

from config import (
    logger, agora_brasil, OPCOES_STATUS, OPCOES_PAGAMENTO
)
from utils import (
    limpar_telefone, validar_telefone, validar_quantidade,
    validar_desconto, validar_data_pedido, validar_hora,
    gerar_id_sequencial, calcular_total
)
from database import (
    salvar_pedidos, carregar_pedidos,
    salvar_clientes, carregar_clientes,
    registrar_alteracao
)
from sheets import sincronizar_automaticamente

# ==============================================================================
# CRUD DE PEDIDOS
# ==============================================================================
def criar_pedido(cliente, caruru, bobo, data, hora, status, pagamento, contato, desconto, observacoes):
    """Cria novo pedido com validação completa."""
    erros = []
    avisos = []

    if not cliente or not cliente.strip():
        erros.append("❌ Cliente é obrigatório.")

    qc, msg = validar_quantidade(caruru, "Caruru")
    if msg: avisos.append(msg)

    qb, msg = validar_quantidade(bobo, "Bobó")
    if msg: avisos.append(msg)

    if qc == 0 and qb == 0:
        erros.append("❌ Pedido deve ter pelo menos 1 item (Caruru ou Bobó).")

    dc, msg = validar_desconto(desconto)
    if msg: avisos.append(msg)

    dt, msg = validar_data_pedido(data, permitir_passado=False)
    if msg: avisos.append(msg)

    hr, msg = validar_hora(hora)
    if msg: avisos.append(msg)

    tel, msg = validar_telefone(contato)
    if msg: avisos.append(msg)

    if erros:
        return None, erros, avisos

    df_p = st.session_state.pedidos
    nid = gerar_id_sequencial(df_p)
    val = calcular_total(qc, qb, dc)

    novo = {
        "ID_Pedido": nid,
        "Cliente": cliente.strip(),
        "Caruru": qc,
        "Bobo": qb,
        "Valor": val,
        "Data": dt,
        "Hora": hr,
        "Status": status if status in OPCOES_STATUS else "🔴 Pendente",
        "Pagamento": pagamento if pagamento in OPCOES_PAGAMENTO else "NÃO PAGO",
        "Contato": tel,
        "Desconto": dc,
        "Observacoes": observacoes.strip() if observacoes else ""
    }

    df_novo = pd.DataFrame([novo])
    st.session_state.pedidos = pd.concat([df_p, df_novo], ignore_index=True)

    if not salvar_pedidos(st.session_state.pedidos):
        st.session_state.pedidos = df_p
        return None, ["❌ ERRO: Não foi possível salvar o pedido. Tente novamente."], []

    st.session_state.pedidos = carregar_pedidos()
    registrar_alteracao("CRIAR", nid, "pedido_completo", None, f"{cliente} - R${val}")

    sucesso_sync, msg_sync, tipo_op = sincronizar_dados_cliente(
        nome_cliente=cliente.strip(),
        contato=tel,
        observacoes=""
    )
    if sucesso_sync and tipo_op in ["criado", "atualizado_nome"]:
        logger.info(f"🔄 Sincronização ao criar pedido: {msg_sync}")

    sincronizar_automaticamente(operacao="criar")

    return nid, [], avisos

def atualizar_pedido(id_pedido, campos_atualizar):
    """Atualiza pedido existente."""
    try:
        df = st.session_state.pedidos
        mask = df['ID_Pedido'] == id_pedido

        if not mask.any():
            return False, f"❌ Pedido #{id_pedido} não encontrado."

        idx = df[mask].index[0]

        if 'Status' in campos_atualizar and campos_atualizar['Status'] == "✅ Entregue":
            status_anterior = df.at[idx, 'Status']
            if status_anterior != "✅ Entregue":
                campos_atualizar['Hora'] = agora_brasil().time()
                logger.info(f"Pedido #{id_pedido} marcado como entregue - hora atualizada para {campos_atualizar['Hora']}")

        for campo, valor in campos_atualizar.items():
            valor_antigo = df.at[idx, campo]

            if campo == "Caruru":
                valor, _ = validar_quantidade(valor, "Caruru")
            elif campo == "Bobo":
                valor, _ = validar_quantidade(valor, "Bobó")
            elif campo == "Desconto":
                valor, _ = validar_desconto(valor)
            elif campo == "Data":
                valor, _ = validar_data_pedido(valor, permitir_passado=True)
            elif campo == "Hora":
                valor, _ = validar_hora(valor)
            elif campo == "Contato":
                valor, _ = validar_telefone(valor)
            elif campo == "Status":
                if valor not in OPCOES_STATUS:
                    valor = "🔴 Pendente"
            elif campo == "Pagamento":
                if valor not in OPCOES_PAGAMENTO:
                    valor = "NÃO PAGO"

            df.at[idx, campo] = valor
            registrar_alteracao("EDITAR", id_pedido, campo, valor_antigo, valor)

        if any(c in campos_atualizar for c in ["Caruru", "Bobo", "Desconto"]):
            df.at[idx, 'Valor'] = calcular_total(
                df.at[idx, 'Caruru'],
                df.at[idx, 'Bobo'],
                df.at[idx, 'Desconto']
            )

        if not salvar_pedidos(df):
            return False, f"❌ ERRO: Não foi possível salvar as alterações. Tente novamente."

        st.session_state.pedidos = carregar_pedidos()

        if 'Cliente' in campos_atualizar or 'Contato' in campos_atualizar:
            nome_cliente_atual = df.at[idx, 'Cliente']
            contato_atual = df.at[idx, 'Contato']
            sucesso_sync, msg_sync, tipo_op = sincronizar_dados_cliente(
                nome_cliente=nome_cliente_atual,
                contato=contato_atual,
                observacoes=""
            )
            if sucesso_sync and tipo_op != "sem_alteracao":
                logger.info(f"🔄 Sincronização ao atualizar pedido #{id_pedido}: {msg_sync}")

        sincronizar_automaticamente(operacao="editar")

        return True, f"✅ Pedido #{id_pedido} atualizado."

    except Exception as e:
        logger.error(f"Erro atualizar pedido: {e}")
        return False, f"❌ Erro ao atualizar: {e}"

def excluir_pedido(id_pedido, motivo=""):
    """Exclui pedido com registro."""
    try:
        df = st.session_state.pedidos
        mask = df['ID_Pedido'] == id_pedido

        if not mask.any():
            return False, f"❌ Pedido #{id_pedido} não encontrado."

        pedido = df[mask].iloc[0]
        cliente = pedido.get('Cliente', 'Desconhecido')

        df_atualizado = df[~mask].reset_index(drop=True)

        if not salvar_pedidos(df_atualizado):
            return False, f"❌ ERRO: Não foi possível excluir o pedido. Tente novamente."

        st.session_state.pedidos = carregar_pedidos()

        registrar_alteracao("EXCLUIR", id_pedido, "pedido_completo", f"{cliente}", motivo or "Sem motivo")

        sincronizar_automaticamente(operacao="excluir")

        return True, f"✅ Pedido #{id_pedido} ({cliente}) excluído."

    except Exception as e:
        logger.error(f"Erro excluir pedido: {e}")
        return False, f"❌ Erro ao excluir: {e}"

def buscar_pedido(id_pedido):
    """Busca pedido por ID."""
    df = st.session_state.pedidos
    mask = df['ID_Pedido'] == id_pedido
    if mask.any():
        return df[mask].iloc[0].to_dict()
    return None

# ==============================================================================
# SINCRONIZAÇÃO DE CLIENTES
# ==============================================================================
def sincronizar_contatos_pedidos(df_pedidos=None, df_clientes=None):
    """Sincroniza contatos dos clientes em todos os pedidos existentes."""
    pedidos = df_pedidos.copy() if df_pedidos is not None else st.session_state.pedidos.copy()
    clientes = df_clientes if df_clientes is not None else st.session_state.clientes

    if pedidos is None or clientes is None or pedidos.empty or clientes.empty:
        return 0, 0

    clientes_norm = clientes.copy()
    clientes_norm['Nome'] = clientes_norm['Nome'].fillna("").astype(str).str.strip()
    clientes_norm['Contato'] = clientes_norm['Contato'].fillna("").astype(str).apply(limpar_telefone)

    mapa_contatos = clientes_norm.set_index('Nome')['Contato'].to_dict()

    atualizados = 0
    for idx, pedido in pedidos.iterrows():
        nome = str(pedido.get('Cliente', '')).strip()
        if not nome:
            continue

        contato_cliente = mapa_contatos.get(nome, "")
        contato_atual = str(pedido.get('Contato', '')) if pd.notna(pedido.get('Contato', '')) else ""

        if contato_cliente and contato_cliente != contato_atual:
            pedidos.at[idx, 'Contato'] = contato_cliente
            atualizados += 1

    if atualizados > 0:
        if not salvar_pedidos(pedidos):
            logger.error("❌ Erro ao salvar pedidos durante sincronização de contatos")
            return 0, len(mapa_contatos)
        st.session_state.pedidos = carregar_pedidos()

    return atualizados, len(mapa_contatos)

def sincronizar_dados_cliente(nome_cliente, contato, nome_cliente_antigo=None, observacoes=""):
    """Sincroniza dados de cliente entre pedidos e cadastro de clientes."""
    try:
        logger.info(f"🔄 INICIANDO sincronizar_dados_cliente - Nome: '{nome_cliente}', Contato: '{contato}', Nome_Antigo: '{nome_cliente_antigo}'")

        if not nome_cliente or not nome_cliente.strip():
            logger.warning("sincronizar_dados_cliente: nome_cliente vazio")
            return False, "Nome do cliente não pode ser vazio", "erro"

        nome_cliente = nome_cliente.strip()
        contato_limpo = limpar_telefone(contato) if contato else ""

        logger.info(f"📋 Após limpeza - Nome: '{nome_cliente}', Contato_Limpo: '{contato_limpo}'")

        df_clientes = st.session_state.clientes.copy()
        logger.info(f"📊 Clientes carregados: {len(df_clientes)} registros")

        alterado = False
        tipo_operacao = "sem_alteracao"
        mensagem = ""

        if contato_limpo:
            logger.info(f"🔍 Buscando cliente por contato: '{contato_limpo}'")

            df_clientes['Contato_Normalizado'] = df_clientes['Contato'].apply(limpar_telefone)
            mask_contato = df_clientes['Contato_Normalizado'] == contato_limpo

            contatos_encontrados = mask_contato.sum()
            logger.info(f"📊 Contatos encontrados: {contatos_encontrados}")

            if mask_contato.any():
                idx = df_clientes[mask_contato].index[0]
                nome_antigo_cadastro = df_clientes.loc[idx, 'Nome']

                logger.info(f"✅ Cliente encontrado - Nome atual no cadastro: '{nome_antigo_cadastro}', Nome novo: '{nome_cliente}'")

                if nome_antigo_cadastro != nome_cliente:
                    logger.info(f"📝 ATUALIZANDO nome do cliente: '{nome_antigo_cadastro}' → '{nome_cliente}'")
                    df_clientes.loc[idx, 'Nome'] = nome_cliente

                    registrar_alteracao(
                        tipo="ATUALIZAR_CLIENTE",
                        id_pedido=0,
                        campo="Nome",
                        valor_antigo=nome_antigo_cadastro,
                        valor_novo=nome_cliente
                    )

                    alterado = True
                    tipo_operacao = "atualizado_nome"
                    mensagem = f"Nome atualizado: '{nome_antigo_cadastro}' → '{nome_cliente}'"

                if observacoes and observacoes.strip():
                    obs_antigas = df_clientes.loc[idx, 'Observacoes']
                    if str(obs_antigas) != str(observacoes):
                        df_clientes.loc[idx, 'Observacoes'] = observacoes
                        alterado = True
                        if tipo_operacao == "sem_alteracao":
                            tipo_operacao = "atualizado_observacoes"

                df_clientes = df_clientes.drop(columns=['Contato_Normalizado'])
            else:
                logger.info(f"✨ Criando novo cliente: '{nome_cliente}' (Contato: {contato_limpo})")

                novo_cliente = {
                    'Nome': nome_cliente,
                    'Contato': contato_limpo,
                    'Observacoes': observacoes if observacoes else ""
                }

                df_clientes = pd.concat([df_clientes, pd.DataFrame([novo_cliente])], ignore_index=True)

                if 'Contato_Normalizado' in df_clientes.columns:
                    df_clientes = df_clientes.drop(columns=['Contato_Normalizado'])

                registrar_alteracao(
                    tipo="CRIAR_CLIENTE",
                    id_pedido=0,
                    campo="Cliente_Completo",
                    valor_antigo="",
                    valor_novo=f"{nome_cliente} - {contato_limpo}"
                )

                alterado = True
                tipo_operacao = "criado"
                mensagem = f"Novo cliente criado: '{nome_cliente}'"
        else:
            mask_nome = df_clientes['Nome'].str.strip() == nome_cliente

            if mask_nome.any():
                tipo_operacao = "sem_alteracao"
                mensagem = "Cliente já existe (busca por nome, sem contato fornecido)"
            else:
                logger.info(f"✨ Criando novo cliente sem contato: '{nome_cliente}'")

                novo_cliente = {
                    'Nome': nome_cliente,
                    'Contato': "",
                    'Observacoes': observacoes if observacoes else ""
                }

                df_clientes = pd.concat([df_clientes, pd.DataFrame([novo_cliente])], ignore_index=True)

                registrar_alteracao(
                    tipo="CRIAR_CLIENTE",
                    id_pedido=0,
                    campo="Cliente_Completo",
                    valor_antigo="",
                    valor_novo=f"{nome_cliente} - (sem contato)"
                )

                alterado = True
                tipo_operacao = "criado"
                mensagem = f"Novo cliente criado: '{nome_cliente}' (sem contato)"

        if alterado:
            logger.info(f"💾 SALVANDO alterações no banco de clientes...")

            if salvar_clientes(df_clientes):
                logger.info(f"✅ Banco de clientes salvo com sucesso!")

                st.session_state.clientes = carregar_clientes()
                logger.info(f"🔄 Session state de clientes recarregado. Total: {len(st.session_state.clientes)} clientes")

                logger.info(f"✅✅✅ Sincronização de cliente CONCLUÍDA COM SUCESSO: {mensagem}")

                sincronizar_automaticamente(operacao="atualizar_cliente")

                return True, mensagem, tipo_operacao
            else:
                logger.error("❌ ERRO ao salvar dados de cliente no arquivo")
                return False, "Erro ao salvar dados do cliente", "erro"
        else:
            logger.info(f"ℹ️ Cliente '{nome_cliente}' já está atualizado - Nenhuma alteração necessária")
            return True, "Cliente já está atualizado", "sem_alteracao"

    except Exception as e:
        logger.error(f"❌❌❌ ERRO CRÍTICO em sincronizar_dados_cliente: {e}", exc_info=True)
        return False, f"Erro ao sincronizar dados: {str(e)}", "erro"
