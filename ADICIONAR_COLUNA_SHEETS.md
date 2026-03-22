# 🔧 Como Adicionar a Coluna "Hora_Entrega" no Google Sheets

## ⚡ Solução Rápida (Manual - 2 minutos)

### Passo 1: Abra sua planilha
Acesse: https://docs.google.com/spreadsheets/d/1JpDwh45CyXmHHqbs1byl_GCl-Dw1ewy_k3yg9C240/edit

### Passo 2: Vá para a aba "Pedidos"
Clique na aba **"Pedidos"** (primeira aba)

### Passo 3: Insira uma nova coluna
1. Localize a coluna **G** (que contém "Hora")
2. Clique com o **botão direito** no cabeçalho da coluna **H** (Status)
3. Selecione: **"Inserir 1 coluna à esquerda"**

### Passo 4: Nomeie a coluna
1. Na nova coluna **H**, célula **H1**, digite: `Hora_Entrega`
2. Pressione **Enter**

### Passo 5: Pronto!
✅ A estrutura está atualizada!
✅ O app agora carregará os dados corretamente
✅ Pedidos antigos terão Hora_Entrega vazia (normal)
✅ Novos pedidos entregues terão o horário capturado automaticamente

---

## 🤖 Alternativa Automática

Execute este comando no terminal (dentro do ambiente Streamlit):

```bash
streamlit run adicionar_coluna_sheets.py
```

---

## 📋 Estrutura Final das Colunas

Após adicionar a coluna, a aba "Pedidos" deve ter esta sequência:

| A | B | C | D | E | F | G | H | I | J | K | L | M |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ID_Pedido | Cliente | Caruru | Bobo | Valor | Data | Hora | **Hora_Entrega** | Status | Pagamento | Contato | Desconto | Observacoes |

---

## ❓ Dúvidas Frequentes

### P: Preciso preencher a coluna Hora_Entrega para pedidos antigos?
**R:** Não! Deixe vazia. O sistema detecta automaticamente pedidos antigos.

### P: O que acontece com novos pedidos?
**R:** Quando você marcar como "✅ Entregue", o horário será capturado automaticamente.

### P: Posso deletar a coluna depois?
**R:** Não recomendado. O sistema precisa dela para funcionar corretamente.

---

## 🆘 Problemas?

Se após adicionar a coluna ainda não funcionar:
1. Feche e reabra o app Streamlit
2. Force atualização: Ctrl+F5 (Windows) ou Cmd+Shift+R (Mac)
3. Verifique se digitou exatamente: `Hora_Entrega` (sem espaços)
