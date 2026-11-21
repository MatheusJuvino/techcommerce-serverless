# Roteiro do vídeo pitch — TechCommerce Serverless

**Disciplina:** Cloud Computing for Software Development — UniFECAF
**Tema:** Automação de processos em nuvem com AWS Lambda e Amazon EventBridge
**Duração máxima:** 4 minutos (roteiro planejado para ~3min50s)
**Link do vídeo (YouTube, não listado):** `[INSERIR O LINK APÓS A PUBLICAÇÃO]`

> Antes de gravar, prepare o ambiente seguindo `entrega/sugestoes_cenas_demonstracao.md`.
> A demonstração usa o **ambiente local simulado**. Diga isso explicitamente no vídeo (a narração
> já inclui a frase) e não apresente a tela local como se fosse o Console da AWS. Se o stack for
> implantado na AWS antes da gravação, adapte as cenas 5 e 6 conforme a seção "Versão AWS" do
> documento de cenas.

Ritmo de referência: cerca de 140 palavras por minuto. Os textos de narração abaixo somam
aproximadamente 520 palavras.

---

## Cena 1 — Abertura e problema · 0:00 a 0:25 (25 s)

**Tela:** slide de título (nome do projeto, aluno, disciplina) → slide com os quatro problemas
(ícones: relógio, cartão, planilha, sino).

**Narração:**
> Olá! Eu sou [SEU NOME] e este é o projeto de automação de processos em nuvem para a TechCommerce,
> um e-commerce fictício. A empresa sofria com quatro problemas: pedidos demorando para ser
> processados, pagamentos que não atualizavam o pedido, relatórios de vendas feitos à mão e
> equipes que não eram avisadas quando algo dava errado.

## Cena 2 — Proposta · 0:25 a 0:45 (20 s)

**Tela:** slide "Solução: arquitetura serverless orientada a eventos" com os logos de Lambda e
EventBridge.

**Narração:**
> A solução é uma arquitetura serverless orientada a eventos na AWS. Não existe servidor para
> administrar: cada etapa é uma função AWS Lambda, e o Amazon EventBridge liga essas funções por
> meio de eventos. Assim, cada parte escala e falha de forma independente.

## Cena 3 — Arquitetura · 0:45 a 1:25 (40 s)

**Tela:** `diagrams/png/arquitetura_icones.png` em tela cheia; usar o cursor para seguir o
caminho API Gateway → Lambda → EventBridge → Lambdas → DynamoDB / S3 / SNS.

**Narração:**
> O pedido chega pelo API Gateway. A função create_order valida os dados, grava no DynamoDB e
> publica o evento OrderReceived no barramento do EventBridge. A partir daí tudo é automático:
> uma regra entrega o evento à função process_order, que aplica as regras de negócio. Os
> pagamentos chegam como eventos TransactionStatusChanged; o EventBridge Scheduler dispara o
> relatório diário, salvo em CSV no S3; e a função de notificações avisa cada equipe pelo SNS.
> O CloudWatch concentra logs, métricas e alarmes.

## Cena 4 — Lambda e EventBridge em detalhe · 1:25 a 1:50 (25 s)

**Tela:** `infrastructure/template.yaml` no editor, destacando a regra `OrderReceivedRule`
(pattern + RetryPolicy + DeadLetterConfig) e depois o bloco `DailySalesReportSchedule`.

**Narração:**
> Toda a infraestrutura está descrita como código com o AWS SAM. Aqui está a regra: ela filtra
> eventos pela origem e pelo tipo, tem retentativas e uma fila DLQ para o que falhar. E aqui o
> agendamento: todo dia às seis da manhã, no horário de São Paulo, o relatório é gerado sozinho.

## Cena 5 — Demonstração: pedido automatizado · 1:50 a 2:45 (55 s)

**Tela:** interface web em `http://127.0.0.1:8000`, mostrando o selo **LOCAL · SIMULADO**.
1. Clicar em **✔ Aprovável** e em **Enviar pedido (POST /orders)**.
2. Mostrar o pedido mudando de `RECEIVED` para `APPROVED` na lista **Pedidos** e as entradas
   **AUTOMÁTICO** em **Histórico das automações**.
3. Clicar no pedido para abrir a linha do tempo.
4. Em **Evento de transação**, publicar `CAPTURED (pago)` → o pedido passa a `PAID`.
5. Clicar em **✖ Acima do limite** e enviar → pedido `REJECTED` e notificação para o suporte.

**Narração:**
> Agora a demonstração. Ela roda num ambiente local que simula o EventBridge e os serviços da
> AWS com o mesmo código das funções — não é a conta AWS. Envio um pedido... a API responde na
> hora com "recebido", e segundos depois o pedido aparece como aprovado. Repare no histórico:
> essa aprovação não foi pedida por ninguém, foi o EventBridge que acionou o Lambda. Agora o
> gateway de pagamento confirma a captura, e o pedido vira "pago". Um pedido acima do limite é
> rejeitado automaticamente e o suporte é notificado.

## Cena 6 — Demonstração: relatório agendado · 2:45 a 3:15 (30 s)

**Tela:** card **Relatórios de vendas** → clicar em **⏰ Disparar agendamento** (executa agora o
alvo do agendamento, simulando o Scheduler) → mostrar o novo arquivo na lista e abrir o CSV de
resumo (download) → mostrar a entrada "EventBridge Scheduler" no histórico.

**Narração:**
> No relatório, em vez de esperar até as seis da manhã, eu disparo o agendamento agora. A função
> consolida as vendas e grava dois arquivos CSV: o detalhe dos pedidos e o resumo, com receita,
> ticket médio e produtos mais vendidos. A gestão recebe a notificação de que o relatório está
> pronto.

## Cena 7 — Confiabilidade, segurança e custos · 3:15 a 3:40 (25 s)

**Tela:** terminal com o final de `pytest` (`67 passed, 3 skipped`) → slide com três colunas:
"Confiável" (idempotência, retentativas, DLQ, alarmes), "Seguro" (privilégio mínimo, sem
credenciais no código, S3 criptografado) e "Econômico" (paga por uso, ~US$ 9/mês estimados para
300 mil pedidos).

**Narração:**
> A solução trata eventos duplicados com idempotência, separa erros temporários de erros
> definitivos, usa retentativas, fila DLQ e alarmes. Cada função tem só as permissões de que
> precisa. São sessenta e sete testes automatizados aprovados. E, como é serverless, o custo
> acompanha o uso: a estimativa é de cerca de nove dólares por mês para trezentos mil pedidos.

## Cena 8 — Encerramento · 3:40 a 3:55 (15 s)

**Tela:** slide final com o diagrama reduzido, link do repositório (se houver) e "Obrigado!".

**Narração:**
> Com Lambda e EventBridge, a TechCommerce passa a processar pedidos, pagamentos e relatórios
> automaticamente, com escala e custo sob controle. O próximo passo é implantar o stack na AWS
> com um único comando do SAM. Obrigado!

---

## Checklist antes de publicar

- [ ] Duração final ≤ 4:00.
- [ ] A frase sobre o ambiente local simulado aparece na cena 5.
- [ ] Nenhum dado pessoal real ou credencial aparece na tela (terminal, `.env`, navegador).
- [ ] Vídeo publicado no YouTube como **Não listado**.
- [ ] Link inserido no topo deste roteiro e em `docs/capa.json` (`video_url`), seguido de
      `python scripts/build_report.py` para atualizar o Apêndice B do PDF.
