# Corrige integridade dos pedidos, recibos, backup e notificações

A versão anterior podia declarar quitação de pedidos não pagos, perder pedidos ao salvar uma sessão antiga e mostrar proteção de backup sem confirmação. Esta mudança corrige os nove achados da auditoria da main `122eddf`, preservando o schema de 17 colunas.

Recibos e indicadores distinguem total, recebido e saldo; preço base é recuperável no Sheets; buscas são literais; Telegram divide mensagens grandes e sinaliza falhas parciais. CRUD e upload usam uma trava comum, revisões rejeitam escritas obsoletas e a restauração valida o conjunto antes de salvar, desfazendo falhas capturadas. O painel exibe valores financeiros em colunas mais largas.

Validação: testes de regressão com arquivos temporários, dois processos concorrentes, PDFs reais, falhas simuladas de rede/gravação, oito telas via Streamlit AppTest e recibos renderizados. CI Linux incluída. Não foram acessados dados de produção nem enviados Telegram/Sheets durante os testes.

Implantação: preservar backup online e preço vigente antes do merge. Fazer um envio completo após o primeiro acesso para migrar o preço ao Sheets. Se não houver preço local nem remoto, a interface pedirá o valor vigente, sem aplicar R$ 70 automaticamente. Detalhes de recuperação e limitações em `docs/AUDITORIA_ONLINE_2026-09-13.md`.
