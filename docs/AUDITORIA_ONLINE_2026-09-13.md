# Correções da auditoria online — versão 21.1

Base: `122eddf453e725e43112df9d7fc4ea4d68ca93b4`. Uso alvo: Streamlit online pelo navegador.

## Mudanças

| Achado | Correção |
|---|---|
| Recibo | Total, recebido e saldo separados. Quitação apenas com saldo zero. Preço do item reconstruído a partir do pedido histórico, sem usar o preço atual. Textos longos fluem e quebram página. |
| Preço base | Configuração recuperada do Sheets quando o arquivo local está ausente/inválido. Alteração exige confirmação remota. Não há fallback silencioso para R$ 70 nem pedido gratuito quando a configuração falha. O envio completo e o ZIP incluem preço base. |
| Proteção dos dados | Indicador usa confirmação do backup e assinatura dos arquivos atuais, compartilhada entre sessões. Toggle ligado, ausência de credenciais, falha e alterações posteriores ao backup não produzem selo verde. |
| Busca | As seis buscas de texto livre usam `regex=False`. |
| A Receber | Inclui entregues com saldo pendente e exclui cancelados. Financeiro usa todos os pedidos do dia, independente da busca na fila. Indicadores financeiros ganharam uma linha mais larga. |
| Telegram | Transporte comum a envio manual e agendado, texto simples e divisão em partes com limite conservador de 4.000 unidades UTF-16. Confirma todas as partes antes do sucesso; falha parcial não marca o dia como enviado. |
| Falha de gravação | CRUD usa cópias; publica sessão e histórico após salvar. Reversão pelo Histórico e entrega rápida usam o CRUD central. Edição conjunta de cliente/pedidos desfaz os arquivos se uma gravação falhar. |
| Restauração | Busca e valida pedidos, clientes e preço antes de gravar. Erro de qualquer fonte cancela. Falha de gravação restaura os bytes anteriores sob a trava. A confirmação visual persiste entre reruns. |
| Concorrência | Uma trava reentrante compartilhada serializa leitura, ID, alteração e gravação entre threads/processos do mesmo servidor. Formulário conflitante no mesmo campo é rejeitado. Escritas diretas obsoletas são rejeitadas por revisão SHA-256. Upload lê o disco sob a mesma trava, não a sessão. |

O schema de pedidos continua com **17 colunas**, incluindo Entrada, Extra, Vegano e Delivery. Sem nova coluna nem migração SQL. Pedidos antigos com desconto de 100% não permitem reconstruir o unitário; a edição de itens fica bloqueada nesse caso e o documento informa que o unitário não está disponível.

Os atalhos de envio/recuperação parcial em Manutenção foram substituídos pelo fluxo completo. CSVs externos continuam disponíveis nos importadores explícitos; essa substituição deliberada tem semântica diferente de editar um pedido. Backups locais agora têm microssegundos no nome para não se sobrescreverem dentro do mesmo segundo.

## Implantação e recuperação

1. Antes do merge, baixar um backup da versão online atual e registrar o preço vigente. O bundle local de código não substitui backup dos dados de produção.
2. Publicar a branch e abrir PR para `main`. Conferir o workflow de testes antes do merge. Nenhum push, PR, merge ou deploy foi executado nesta implementação.
3. No primeiro acesso após atualização, se houver configuração local, ela continua válida e será incluída no próximo envio completo. Usar **Confirmar backup agora** para migrar o preço ao Sheets antes de encerrar a sessão.
4. Se nem o arquivo local nem a chave `preco_base` no Sheets existirem, o app pedirá confirmação do preço vigente uma única vez antes de permitir uso. Não preencher com um valor presumido. Se a rede falhar durante a recuperação, o app bloqueia novos pedidos em vez de iniciar uma base incompleta.
5. A aba Config preserva `notification_hour` e `last_notification_date`; grava/atualiza apenas `preco_base`. A configuração deve permanecer acessível à mesma conta de serviço usada atualmente.
6. Após o deploy, verificar versão 21.1, recibo parcial, consulta de entregues não pagos e confirmação de backup. Esta checagem em produção não foi realizada nesta etapa.

Reversão de código: reaplicar a revisão anterior por PR. O schema não mudou. Se os dados tiverem sido alterados, recuperar um snapshot coerente e conferir os três componentes; não substituir a base por um backup antigo sem verificar pedidos posteriores.

## Validação

- Suíte em `tests/`: recibos reais com leitura de PDF; preço histórico; sessões antigas; criação concorrente por dois processos; conflitos; falhas de disco simuladas; recuperação do conjunto; preço ausente/rede indisponível; preservação das outras chaves de Config; indicador de backup; conteúdo e limite das mensagens; falha parcial sem registrar envio; schema de 17 colunas; ZIP com preço e dados atuais.
- Streamlit AppTest: navegação pelas oito telas, busca literal e confirmação de restauração em múltiplos reruns com falha simulada.
- Recibos fictícios pendente, parcial e pago renderizados com Poppler e conferidos visualmente.
- Preview local do app real no navegador, com dados e senha fictícios. Sem conectar à planilha ou enviar Telegram.
- Ambiente executado: Python 3.11 e dependências de requirements-dev.txt. Workflow Linux/Python 3.11 e 3.12 incluído; a execução no GitHub só ocorrerá após publicação.

Executar: `python -m pip install -r requirements-dev.txt` e `python -m pytest tests -q`.

## Limites práticos

O controle de concorrência protege processos que usam o mesmo diretório de dados no mesmo servidor. Não sincroniza duas instalações independentes nem edições feitas diretamente no Sheets. O envio de várias abas ao Google não é uma transação distribuída: erro parcial é sinalizado e não confirma proteção; deve-se repetir o backup completo quando a conexão voltar. A recuperação local desfaz falhas capturadas de escrita, mas não constitui garantia de atomicidade entre vários arquivos diante de queda de energia no meio da operação.

Não há repetição automática de partes do Telegram em resposta incerta: a mensagem de erro informa quantas partes foram confirmadas e avisa sobre possível duplicação ao repetir. A divisão preserva o conteúdo, mas um bloco muito longo pode continuar na parte seguinte.

O objetivo desta entrega são os nove achados. Funcionalidades novas como repetir pedido, cadastro estruturado de endereço e reformulação completa dos cartões móveis permanecem propostas de evolução, não foram misturadas às correções.
