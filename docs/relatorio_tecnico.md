# !RESUMO

Este relatório apresenta o projeto e a implementação de uma solução de automação de processos em nuvem para a TechCommerce, empresa fictícia de comércio eletrônico que enfrenta atrasos no processamento de pedidos, falhas na atualização de transações e esforço manual na geração de relatórios de vendas. A solução adota uma arquitetura *serverless* orientada a eventos na Amazon Web Services (AWS), na qual o Amazon API Gateway recebe pedidos, funções AWS Lambda executam a lógica de negócio, o Amazon EventBridge roteia eventos de domínio entre os componentes e o Amazon EventBridge Scheduler dispara a geração periódica de relatórios. Os dados são persistidos no Amazon DynamoDB, os relatórios em CSV são armazenados no Amazon S3, as notificações operacionais são enviadas pelo Amazon SNS e o Amazon CloudWatch concentra logs, métricas e alarmes. A infraestrutura foi descrita como código com o AWS Serverless Application Model (SAM) e incorpora idempotência, controle de transições de estado, retentativas, fila de mensagens não processadas (DLQ) e permissões de privilégio mínimo. Como não houve implantação em uma conta AWS, a validação foi feita com 67 testes automatizados aprovados (com serviços AWS emulados pela biblioteca moto), validação estática do *template* (cfn-lint e `sam validate --lint`), empacotamento com `sam build` e uma demonstração ponta a ponta em um ambiente local que simula o EventBridge e o Scheduler. Os resultados indicam que a arquitetura atende aos quatro fluxos propostos — pedidos, transações, relatórios e notificações — e estão claramente identificados como resultados de simulação local, e não de execução na AWS.

**Palavras-chave:** computação em nuvem; *serverless*; AWS Lambda; Amazon EventBridge; arquitetura orientada a eventos.

[[PAGEBREAK]]

[[TOC]]

[[BODY]]

# 1 INTRODUÇÃO

A computação em nuvem transformou a forma como sistemas de software são construídos e operados. Em vez de adquirir e administrar servidores, as organizações passaram a consumir recursos computacionais sob demanda, pagando apenas pelo que utilizam (MELL; GRANCE, 2011). Dentro desse paradigma, o modelo *serverless* leva a abstração um passo adiante: o desenvolvedor entrega apenas o código e a configuração, enquanto o provedor se encarrega do provisionamento, da escala e da disponibilidade da infraestrutura (JONAS *et al.*, 2019; AMAZON WEB SERVICES, 2026a).

Este trabalho aplica esses conceitos a um problema concreto de negócio. A TechCommerce, empresa fictícia de comércio eletrônico, precisa automatizar processos que hoje dependem de intervenção manual ou de rotinas pouco confiáveis: o processamento de pedidos, a atualização das transações de pagamento, a geração de relatórios de vendas e a comunicação com as equipes internas. Para isso, foi projetada e implementada uma arquitetura orientada a eventos baseada no AWS Lambda e no Amazon EventBridge, complementada por serviços gerenciados da AWS.

O documento está organizado da seguinte forma: o capítulo 2 contextualiza o problema; o capítulo 3 define os objetivos; o capítulo 4 apresenta a fundamentação teórica; os capítulos 5 a 7 descrevem a arquitetura, a justificativa das escolhas e os fluxos automatizados; o capítulo 8 detalha a implementação; os capítulos 9 a 12 discutem escalabilidade, segurança, monitoramento e custos; o capítulo 13 apresenta os resultados obtidos e o capítulo 14 traz as conclusões.

> **Nota sobre as fontes.** Os materiais didáticos das Unidades 1 a 4 da disciplina não estavam disponíveis no ambiente em que este relatório foi elaborado. Por esse motivo, a fundamentação teórica baseia-se na documentação oficial da AWS, nas referências indicadas no enunciado e em literatura técnica reconhecida. **Recomenda-se complementar o capítulo 4 e as referências com citações do material das Unidades 1 a 4** antes da entrega final.

# 2 CONTEXTUALIZAÇÃO DO PROBLEMA

A TechCommerce comercializa produtos eletrônicos pela internet e registrou crescimento no volume de pedidos, com picos concentrados em campanhas promocionais. A operação atual apresenta quatro problemas principais:

- **Atrasos no processamento de pedidos:** a validação e a aprovação dependem de rotinas executadas em lote ou de verificação manual, o que aumenta o tempo entre a compra e o envio para a logística.
- **Falhas na atualização de transações:** as confirmações de pagamento enviadas pelo *gateway* nem sempre são refletidas no pedido, gerando divergências entre o status financeiro e o status do pedido.
- **Relatórios manuais:** a consolidação diária de vendas é feita manualmente, consumindo tempo da equipe e sujeita a erros.
- **Baixa visibilidade operacional:** as equipes de logística, financeiro, suporte e gestão não são avisadas de forma padronizada sobre aprovações, recusas, falhas e relatórios disponíveis.

Além disso, uma infraestrutura dimensionada para os picos permanece ociosa na maior parte do tempo, enquanto uma infraestrutura dimensionada para a média sofre com lentidão nos momentos de maior demanda. O desafio, portanto, é automatizar esses processos com uma solução que escale conforme a demanda, seja tolerante a falhas, mantenha o histórico das operações e tenha custo proporcional ao uso.

# 3 OBJETIVOS

## 3.1 Objetivo geral

Projetar e implementar uma arquitetura *serverless* orientada a eventos na AWS, baseada no AWS Lambda e no Amazon EventBridge, que automatize o processamento de pedidos, a atualização de transações, a geração de relatórios de vendas e o envio de notificações operacionais da TechCommerce.

## 3.2 Objetivos específicos

- Receber pedidos por uma API REST, validar os dados e publicar o evento `OrderReceived` no EventBridge.
- Processar pedidos de forma assíncrona, aplicando regras de negócio e registrando o resultado no DynamoDB.
- Atualizar automaticamente o status das transações a partir de eventos `TransactionStatusChanged`, respeitando transições de estado válidas.
- Gerar automaticamente, em horário agendado, um relatório consolidado de vendas em CSV e armazená-lo no Amazon S3.
- Notificar as equipes responsáveis sobre aprovações, recusas, atualizações de transação, falhas e relatórios gerados.
- Garantir idempotência, retentativas, tratamento de falhas com fila DLQ, logs estruturados e monitoramento.
- Descrever toda a infraestrutura como código com o AWS SAM, com permissões de privilégio mínimo.
- Disponibilizar testes automatizados e um ambiente de demonstração local que não exija conta AWS, diferenciando claramente a simulação local da execução real na nuvem.

# 4 FUNDAMENTAÇÃO TEÓRICA

## 4.1 Computação em nuvem

Segundo o National Institute of Standards and Technology (NIST), computação em nuvem é um modelo que permite acesso conveniente e sob demanda, pela rede, a um conjunto compartilhado de recursos computacionais configuráveis — como redes, servidores, armazenamento, aplicações e serviços —, que podem ser rapidamente provisionados e liberados com mínimo esforço de gerenciamento ou interação com o provedor (MELL; GRANCE, 2011). O NIST destaca cinco características essenciais:

- **Autoatendimento sob demanda:** o consumidor provisiona recursos sem interação humana com o provedor.
- **Amplo acesso à rede:** os recursos ficam disponíveis pela rede, por mecanismos padronizados.
- **Agrupamento de recursos:** os recursos do provedor atendem a múltiplos clientes em modelo *multi-tenant*.
- **Elasticidade rápida:** a capacidade pode ser ampliada ou reduzida rapidamente, conforme a demanda.
- **Serviço medido:** o uso é monitorado e cobrado de forma transparente.

Essas características são diretamente relevantes para a TechCommerce: a elasticidade responde aos picos de pedidos e o serviço medido permite pagar apenas pelo processamento efetivamente realizado.

## 4.2 Modelos de serviço

Os modelos de serviço descrevem a divisão de responsabilidades entre provedor e cliente. Quanto mais alto o nível de abstração, menos componentes o cliente precisa administrar (MELL; GRANCE, 2011; AMAZON WEB SERVICES, 2026k).

Tabela: Modelos de serviço em nuvem e exemplos na AWS
| Modelo | O cliente gerencia | O provedor gerencia | Exemplos na AWS |
|---|---|---|---|
| IaaS (Infraestrutura como Serviço) | Sistema operacional, *runtime*, aplicação e dados | Hardware, rede, virtualização | Amazon EC2, Amazon VPC, Amazon EBS |
| PaaS (Plataforma como Serviço) | Aplicação e dados | Infraestrutura, sistema operacional e *runtime* | AWS Elastic Beanstalk |
| SaaS (Software como Serviço) | Apenas o uso e a configuração | Toda a pilha, incluindo a aplicação | Amazon WorkMail, Amazon Chime |
| FaaS / *serverless* | Código das funções e configuração | Servidores, escala, disponibilidade e *runtime* | AWS Lambda, Amazon EventBridge, Amazon DynamoDB |
Fonte: elaborada pelo autor com base em Mell e Grance (2011) e Amazon Web Services (2026k).

A solução proposta situa-se no modelo FaaS combinado com serviços gerenciados (*Backend as a Service*), em que banco de dados, filas, armazenamento e mensageria também são consumidos sem administração de servidores.

## 4.3 Computação *serverless*

Computação *serverless* não significa ausência de servidores, mas sim que o gerenciamento deles é responsabilidade do provedor. Roberts (2018) caracteriza o modelo pela combinação de funções executadas sob demanda, disparadas por eventos, com serviços de terceiros que substituem componentes antes mantidos pela equipe. Baldini *et al.* (2017) e Jonas *et al.* (2019) destacam como propriedades centrais: escala automática, inclusive até zero; cobrança por execução, sem custo de capacidade ociosa; e redução significativa do esforço operacional.

Essas vantagens vêm acompanhadas de restrições que precisam ser consideradas no projeto: funções têm tempo máximo de execução, são sem estado (o estado deve ser externalizado em bancos ou filas), podem sofrer latência de inicialização (*cold start*) e, por se integrarem por eventos assíncronos, exigem cuidado com entregas duplicadas e com a observabilidade de fluxos distribuídos (BALDINI *et al.*, 2017; AMAZON WEB SERVICES, 2026h).

## 4.4 Arquitetura orientada a eventos

Em uma arquitetura orientada a eventos (*Event-Driven Architecture*, EDA), os componentes comunicam-se pela emissão e pelo consumo de eventos — registros imutáveis de fatos que ocorreram no domínio, como "pedido recebido" ou "pagamento capturado". Fowler (2017) distingue padrões como a notificação de eventos, em que o produtor apenas informa que algo ocorreu, e a transferência de estado transportada pelo evento, em que o evento carrega os dados necessários ao consumidor. Hohpe e Woolf (2003) descrevem os padrões de mensageria que sustentam essas integrações, como canais publicador/assinante, roteadores baseados em conteúdo e canais de mensagens inválidas (*dead letter channel*).

Os principais benefícios da EDA são o desacoplamento entre produtores e consumidores, a possibilidade de adicionar novos consumidores sem alterar o produtor, a absorção de picos por meio de processamento assíncrono e o isolamento de falhas. Em contrapartida, a entrega de eventos costuma seguir a semântica "pelo menos uma vez" (*at-least-once*), o que exige consumidores idempotentes (AMAZON WEB SERVICES, 2026f; AMAZON WEB SERVICES, 2026h).

## 4.5 AWS Lambda

O AWS Lambda é um serviço de computação *serverless* que executa código em resposta a eventos e gerencia automaticamente os recursos computacionais, sem a necessidade de provisionar ou administrar servidores (AMAZON WEB SERVICES, 2026a; AMAZON WEB SERVICES, 2026b). O desenvolvedor fornece uma função em uma das linguagens suportadas — neste projeto, Python 3.12 — e configura memória, tempo limite, variáveis de ambiente e permissões. A cobrança considera o número de requisições e a duração da execução proporcional à memória alocada (AMAZON WEB SERVICES, 2026j).

O Lambda pode ser invocado de forma síncrona (por exemplo, pelo API Gateway, que aguarda a resposta) ou assíncrona (por exemplo, pelo EventBridge). Na invocação assíncrona, o serviço enfileira o evento, realiza até duas retentativas em caso de erro e pode encaminhar os eventos que falharam a um destino de falha, como uma fila do Amazon SQS (AMAZON WEB SERVICES, 2026f). Esse comportamento é a base da estratégia de tolerância a falhas adotada no projeto. O artigo de Massaronii ([s. d.]) ilustra a criação de automações com Lambda disparadas por agendamento, abordagem análoga à utilizada aqui para os relatórios, porém implementada com o AWS SAM em vez do Serverless Framework.

## 4.6 Amazon EventBridge e EventBridge Scheduler

O Amazon EventBridge é um serviço *serverless* de barramento de eventos que conecta aplicações por meio de eventos, roteando-os de produtores para consumidores com base em regras (AMAZON WEB SERVICES, 2026c). Seus principais conceitos são:

- **Barramento de eventos (*event bus*):** canal que recebe os eventos. O projeto utiliza um barramento personalizado, `techcommerce-<ambiente>-bus`, isolado do barramento padrão da conta.
- **Regras e padrões de eventos:** cada regra possui um padrão (*event pattern*) que seleciona eventos pelo conteúdo, por exemplo `source` e `detail-type`, e um ou mais destinos (AMAZON WEB SERVICES, 2026d).
- **Política de retentativa e DLQ por destino:** quando a entrega ao destino falha, o EventBridge tenta novamente e pode enviar o evento a uma fila SQS de mensagens não entregues.
- **Arquivo e reprodução (*archive and replay*):** os eventos podem ser arquivados e reprocessados posteriormente, recurso útil para auditoria e recuperação.

O Amazon EventBridge Scheduler, por sua vez, é um agendador *serverless* que permite criar, executar e gerenciar tarefas a partir de um serviço central, com expressões `cron`, `rate` ou execuções únicas, suporte a fusos horários e políticas próprias de retentativa e DLQ (AMAZON WEB SERVICES, 2026e). No projeto, ele dispara diariamente a geração do relatório de vendas.

## 4.7 Serviços complementares

- **Amazon API Gateway:** serviço gerenciado para criar, publicar e proteger APIs, com limitação de taxa (*throttling*), CORS e integração direta com o Lambda.
- **Amazon DynamoDB:** banco de dados NoSQL chave-valor totalmente gerenciado, com latência de milissegundos, modo de capacidade sob demanda e escritas condicionais, essenciais para idempotência e controle de concorrência (AMAZON WEB SERVICES, 2026l).
- **Amazon S3:** armazenamento de objetos durável, utilizado para os relatórios CSV, com criptografia e regras de ciclo de vida.
- **Amazon SNS:** serviço de mensagens publicador/assinante; uma única publicação é entregue a múltiplos assinantes (e-mail, filas, funções), com filtragem por atributos.
- **Amazon SQS:** filas gerenciadas, aqui usadas como DLQ para eventos que esgotaram as retentativas.
- **Amazon CloudWatch:** logs, métricas e alarmes para observabilidade e resposta a incidentes.

## 4.8 Infraestrutura como código com AWS SAM

Infraestrutura como código (*Infrastructure as Code*, IaC) consiste em descrever recursos de infraestrutura em arquivos versionados, permitindo provisionamento reprodutível e revisável. O AWS Serverless Application Model (SAM) é uma extensão do AWS CloudFormation com sintaxe simplificada para funções, APIs, eventos e agendamentos, acompanhada da SAM CLI para validação, empacotamento e implantação (AMAZON WEB SERVICES, 2026g).

# 5 ARQUITETURA PROPOSTA

## 5.1 Visão geral

A arquitetura segue o estilo orientado a eventos: a API apenas valida e registra o pedido, publicando um evento; todo o restante do processamento ocorre de forma assíncrona, disparado por regras do EventBridge ou pelo EventBridge Scheduler. A Figura 1 apresenta a visão geral com os ícones dos serviços e a Figura 2 detalha as conexões entre os componentes.

![Visão geral da arquitetura serverless da TechCommerce](diagrams/png/arquitetura_icones.png)
Fonte: elaborada pelo autor (Mermaid, com ícones do pacote Iconify "logos").

![Arquitetura detalhada: produtores, barramento de eventos, funções e serviços de dados](diagrams/png/arquitetura_1.png)
Fonte: elaborada pelo autor.

## 5.2 Componentes

Tabela: Componentes da arquitetura e respectivas responsabilidades
| Componente | Serviço AWS | Responsabilidade |
|---|---|---|
| API REST | Amazon API Gateway | Expor `POST /orders`, consultas (`GET /orders`, `/reports`, `/automations`) e endpoints de demonstração; aplicar *throttling* e CORS |
| `create_order` | AWS Lambda | Validar o pedido, gravar com status `RECEIVED` e publicar `OrderReceived` |
| `process_order` | AWS Lambda | Aplicar regras de negócio, aprovar ou rejeitar e publicar `OrderApproved` ou `OrderRejected` |
| `update_transaction` | AWS Lambda | Aplicar a transição de pagamento ao pedido e publicar `TransactionUpdated` |
| `generate_sales_report` | AWS Lambda | Consolidar vendas do período, gerar CSVs no S3 e publicar `SalesReportGenerated` |
| `notification_dispatcher` | AWS Lambda | Transformar eventos de negócio em notificações para as equipes via SNS |
| `demo_events` e `read_api` | AWS Lambda | Publicar eventos de demonstração e atender às consultas da interface web |
| Barramento de eventos | Amazon EventBridge | Rotear eventos de domínio por regras; arquivar eventos por 7 dias |
| Agendamento | EventBridge Scheduler | Disparar o relatório diário às 06h (America/Sao_Paulo) |
| Pedidos, idempotência e histórico | Amazon DynamoDB | Tabelas `orders`, `idempotency` e `automation-log`, em modo sob demanda |
| Relatórios | Amazon S3 | Armazenar os CSVs com criptografia, acesso público bloqueado e ciclo de vida |
| Notificações | Amazon SNS | Tópico único com atributos `eventType`, `team` e `severity` para filtragem |
| DLQ | Amazon SQS | Receber eventos que esgotaram as retentativas (retenção de 14 dias) |
| Observabilidade | Amazon CloudWatch | Logs JSON, métricas personalizadas (EMF) e 5 alarmes |
Fonte: elaborada pelo autor a partir de `infrastructure/template.yaml`.

## 5.3 Contrato de eventos

Todos os eventos de domínio seguem um envelope comum no campo `detail`, composto por metadados e dados de negócio. O identificador único `eventId` permite rastrear e deduplicar eventos, e o `correlationId` liga todos os eventos e logs gerados por um mesmo pedido.

```
{
  "source": "techcommerce.orders",
  "detail-type": "OrderReceived",
  "detail": {
    "metadata": {
      "eventId": "9f1c3e2a-...",            // identificador único do evento
      "correlationId": "4f35da88-...",      // rastreia o pedido de ponta a ponta
      "occurredAt": "2026-11-21T00:51:44.315Z",
      "schemaVersion": "1.0",
      "producer": "create_order"
    },
    "data": { "orderId": "ORD-2C52633F0D45", "total": 4079.70, "...": "..." }
  }
}
```

Tabela: Catálogo de eventos de domínio
| Evento (`detail-type`) | Origem (`source`) | Produtor | Consumidor(es) |
|---|---|---|---|
| `OrderReceived` | `techcommerce.orders` | `create_order` | `process_order` |
| `OrderApproved` / `OrderRejected` | `techcommerce.orders` | `process_order` | `notification_dispatcher` |
| `TransactionStatusChanged` | `techcommerce.payments` | *Gateway* de pagamento (simulado por `demo_events`) | `update_transaction` |
| `TransactionUpdated` | `techcommerce.payments` | `update_transaction` | `notification_dispatcher` |
| `SalesReportRequested` | `techcommerce.reports` | `demo_events` (sob demanda) | `generate_sales_report` |
| `SalesReportGenerated` | `techcommerce.reports` | `generate_sales_report` | `notification_dispatcher` |
| `ProcessingFailed` | `techcommerce.operations` | Qualquer função, em falha permanente | `notification_dispatcher` |
Fonte: elaborada pelo autor a partir de `src/models/events.py`.

![Roteamento de eventos entre o EventBridge e as funções Lambda](diagrams/png/fluxo_eventos_1.png)
Fonte: elaborada pelo autor.

## 5.4 Modelo de dados

A tabela `orders` usa `orderId` como chave de partição e possui o índice secundário global `ByCreatedDay` (`createdDay` + `createdAt`), que permite ao relatório consultar os pedidos de um período sem varrer a tabela inteira. Cada pedido mantém um histórico (`history`) com cada mudança de status, a função responsável e o identificador do evento. A tabela `idempotency` armazena as chaves de processamento com expiração automática por TTL, e a tabela `automation-log` registra cada execução automática, por dia, para alimentar o histórico exibido na interface.

# 6 JUSTIFICATIVA DAS ESCOLHAS TECNOLÓGICAS

A escolha de cada serviço considerou os requisitos da TechCommerce — demanda variável, necessidade de automação, rastreabilidade e custo proporcional ao uso — e as alternativas disponíveis.

Tabela: Escolhas tecnológicas, alternativas consideradas e justificativa
| Necessidade | Escolha | Alternativa considerada | Justificativa |
|---|---|---|---|
| Executar a lógica de negócio | AWS Lambda | Contêineres no Amazon ECS ou instâncias EC2 | Escala automática por requisição, sem servidores ociosos e com cobrança por execução |
| Integrar componentes | Amazon EventBridge | Chamadas diretas entre funções ou Amazon SNS | Roteamento por conteúdo, novos consumidores sem alterar produtores, arquivo/reprodução e DLQ por destino |
| Agendar relatórios | EventBridge Scheduler | Regras agendadas do EventBridge ou *cron* em servidor | Fuso horário nativo (America/Sao_Paulo), retentativa e DLQ próprias, sem servidor dedicado |
| Persistir pedidos | Amazon DynamoDB sob demanda | Amazon RDS (PostgreSQL) | Sem gestão de conexões ou instâncias, escritas condicionais para idempotência e custo por requisição |
| Armazenar relatórios | Amazon S3 | Anexos em e-mail ou banco de dados | Durabilidade, baixo custo, criptografia e ciclo de vida automático |
| Notificar equipes | Amazon SNS | Envio direto de e-mail pelo código | Uma publicação para vários assinantes e filtragem por equipe |
| Infraestrutura como código | AWS SAM | Serverless Framework ou Terraform | Ferramenta oficial da AWS, sintaxe concisa para Lambda, EventBridge e Scheduler e validação integrada |
| Linguagem | Python 3.12 com boto3 | Node.js | SDK oficial maduro, legibilidade e ecossistema de testes (pytest, moto) |
Fonte: elaborada pelo autor.

O ponto central da justificativa é o desacoplamento. Como a API apenas publica `OrderReceived`, um pico de pedidos não sobrecarrega o processamento: os eventos são entregues às funções de forma assíncrona e o Lambda escala o número de execuções concorrentes conforme a demanda. Além disso, novas automações — por exemplo, uma futura função antifraude — podem ser adicionadas apenas criando uma nova regra no barramento, sem alterar as funções existentes.

# 7 FLUXOS AUTOMATIZADOS

## 7.1 Fluxo 1 – Processamento de pedidos

O cliente envia o pedido para `POST /orders`. A função `create_order` valida os dados (cliente, itens, quantidades, preços e forma de pagamento), grava o pedido com status `RECEIVED` e publica `OrderReceived`, respondendo imediatamente com HTTP 202 (aceito). O cabeçalho opcional `Idempotency-Key` evita pedidos duplicados quando o cliente reenvia a mesma requisição. Em seguida, a regra `order-received` do EventBridge invoca `process_order`, que aplica as regras de negócio:

- valor total acima de R$ 10.000,00 (parâmetro `MaxOrderValue`) é rejeitado para análise manual;
- quantidade por item acima de 50 unidades é rejeitada;
- pagamento por boleto acima de R$ 5.000,00 é rejeitado.

O resultado é gravado com uma atualização condicional — que só ocorre se o pedido ainda estiver em `RECEIVED` — e o evento `OrderApproved` ou `OrderRejected` é publicado, gerando a notificação para a logística ou para o suporte.

![Fluxo de processamento de pedidos](diagrams/png/fluxo_pedidos_1.png){scale=0.85}
Fonte: elaborada pelo autor.

![Diagrama de sequência do processamento de um pedido](diagrams/png/fluxo_pedidos_2.png)
Fonte: elaborada pelo autor.

![Ciclo de vida (estados) do pedido](diagrams/png/fluxo_pedidos_3.png){scale=0.8}
Fonte: elaborada pelo autor.

## 7.2 Fluxo 2 – Atualização de transações

O *gateway* de pagamento publica `TransactionStatusChanged` no barramento (na demonstração, esse papel é exercido pelo endpoint `POST /transactions`). A função `update_transaction` valida o evento, verifica se a transição é permitida para o status atual do pedido, confere se o valor da transação corresponde ao total do pedido e atualiza o pedido de forma condicional. Transições inválidas e pedidos inexistentes são falhas permanentes: não adianta tentar novamente, então a função publica `ProcessingFailed` para a equipe de operações.

Tabela: Transições de transação e efeito sobre o pedido
| Status da transação | Status do pedido exigido | Novo status do pedido |
|---|---|---|
| `AUTHORIZED` | `APPROVED` | Mantém `APPROVED` (pagamento autorizado) |
| `CAPTURED` | `APPROVED` | `PAID` |
| `DECLINED` | `APPROVED` | `PAYMENT_DECLINED` |
| `REFUNDED` | `PAID` | `REFUNDED` |
Fonte: elaborada pelo autor a partir de `src/models/transaction.py`.

A chave de idempotência deste fluxo é composta por `transactionId` e status, de modo que o mesmo evento do *gateway* entregue duas vezes é processado apenas uma vez.

## 7.3 Fluxo 3 – Relatório de vendas agendado

O EventBridge Scheduler dispara `generate_sales_report` com a expressão `cron(0 6 * * ? *)` no fuso `America/Sao_Paulo`, ou seja, todos os dias às 06h00. A expressão, o fuso e o estado (ativo/inativo) são parâmetros do *template* (`ReportScheduleExpression`, `ReportScheduleTimezone` e `ReportScheduleState`) e podem ser alterados sem modificar o código — por exemplo, `rate(1 hour)` para relatórios horários. O mesmo relatório pode ser solicitado sob demanda pelo evento `SalesReportRequested`, com os períodos `last_24h`, `today`, `yesterday` ou `last_7d`.

A função consulta o índice `ByCreatedDay`, consolida os indicadores (total de pedidos por status, receita aprovada e confirmada, ticket médio, taxa de aprovação, receita por forma de pagamento e produtos mais vendidos) e grava dois arquivos no S3: o detalhamento dos pedidos e o resumo consolidado, em `reports/AAAA/MM/DD/`. A chave de idempotência do agendamento usa o horário programado (`<aws.scheduler.scheduled-time>`), evitando relatórios duplicados quando o Scheduler realiza uma retentativa.

![Fluxo de geração do relatório de vendas](diagrams/png/fluxo_relatorios_1.png){scale=0.85}
Fonte: elaborada pelo autor.

![Sequência da geração agendada do relatório](diagrams/png/fluxo_relatorios_2.png)
Fonte: elaborada pelo autor.

## 7.4 Fluxo 4 – Notificações operacionais

A função `notification_dispatcher` é acionada por uma regra que seleciona os cinco eventos notificáveis e publica uma mensagem no tópico SNS com atributos que permitem filtrar as assinaturas por equipe. A assinatura de e-mail da logística, por exemplo, usa uma política de filtro que recebe apenas mensagens com `team = logistics`.

Tabela: Eventos notificáveis e equipes de destino
| Evento | Equipe (`team`) | Severidade | Objetivo |
|---|---|---|---|
| `OrderApproved` | logistics | INFO | Iniciar separação e envio |
| `OrderRejected` | support | WARNING | Contatar o cliente ou revisar manualmente |
| `TransactionUpdated` | finance | INFO | Conciliar pagamentos |
| `ProcessingFailed` | operations | ERROR | Investigar falhas permanentes |
| `SalesReportGenerated` | management | INFO | Disponibilizar o relatório à gestão |
Fonte: elaborada pelo autor a partir de `src/services/notifications.py`.

# 8 IMPLEMENTAÇÃO

## 8.1 Organização do código

O projeto, localizado na pasta `techcommerce-serverless`, separa responsabilidades em camadas:

- `src/handlers/`: pontos de entrada das funções Lambda, responsáveis apenas por interpretar o evento e chamar os serviços;
- `src/services/` e `src/repositories/`: regras de negócio, idempotência, publicação de eventos, relatórios e acesso ao DynamoDB e ao S3;
- `src/models/` e `src/utils/`: validação, modelos de eventos, configuração por variáveis de ambiente, logs estruturados e erros;
- `infrastructure/template.yaml`: *template* AWS SAM com todos os recursos;
- `local_runtime/` e `frontend/`: ambiente de demonstração local e interface web;
- `tests/`: testes unitários, de *handlers*, de infraestrutura e de integração;
- `diagrams/` e `docs/`: diagramas Mermaid e este relatório.

As configurações (nomes de tabelas, barramento, bucket, tópico e limites de negócio) são lidas de variáveis de ambiente injetadas pelo *template*; nenhuma credencial é armazenada no código.

## 8.2 Idempotência

Como o EventBridge, o Scheduler e as invocações assíncronas do Lambda garantem entrega "pelo menos uma vez", o mesmo evento pode chegar mais de uma vez. Antes de qualquer efeito colateral, cada consumidor tenta gravar sua chave de idempotência com uma escrita condicional; somente a primeira execução obtém o *lock*, e as seguintes recebem o resultado já registrado. O trecho a seguir, de `src/services/idempotency.py`, mostra a escrita condicional:

```
self.table.put_item(
    Item={"pk": key, "status": "IN_PROGRESS",
          "lockExpiresAt": now + self.lock_timeout_seconds,
          "expireAt": now + self.ttl_seconds, "createdAt": now_iso()},
    ConditionExpression="attribute_not_exists(pk) OR "
                        "(#s = :inprogress AND lockExpiresAt < :now)",
    ...
)
```

Em caso de falha transitória, o *lock* é liberado para que a retentativa possa executar; em caso de falha permanente, a chave é concluída com status `FAILED`, impedindo reprocessamentos inúteis.

## 8.3 Tratamento de erros e retentativas

Os erros foram classificados em dois tipos. Os **erros permanentes** (dados inválidos, pedido inexistente, transição não permitida) não se resolvem com novas tentativas: a função registra o erro, publica `ProcessingFailed` e encerra sem lançar exceção. Os **erros transitórios** (indisponibilidade momentânea de uma dependência) são relançados para que a plataforma tente novamente: o Lambda realiza até 2 retentativas assíncronas e, esgotadas as tentativas, envia o evento para a DLQ no SQS; a mensagem na DLQ dispara um alarme no CloudWatch, que notifica a equipe pelo SNS. As regras do EventBridge também possuem política de retentativa (até 5 tentativas em até 1 hora) e DLQ própria para falhas de entrega.

![Tratamento de falhas, retentativas e idempotência](diagrams/png/fluxo_eventos_2.png){scale=0.85}
Fonte: elaborada pelo autor.

## 8.4 Infraestrutura como código

O arquivo `infrastructure/template.yaml` descreve todos os recursos: barramento e arquivo do EventBridge, fila DLQ, três tabelas DynamoDB, bucket S3 com política que exige TLS, tópico SNS com assinaturas opcionais, API Gateway, sete funções Lambda com grupos de logs dedicados, regras, agendamento e cinco alarmes. O trecho a seguir mostra a declaração da regra que conecta o evento `OrderReceived` à função `process_order`:

```
Events:
  OrderReceivedRule:
    Type: EventBridgeRule
    Properties:
      EventBusName: !Ref TechCommerceEventBus
      Pattern:
        source: [techcommerce.orders]
        detail-type: [OrderReceived]
      RetryPolicy:
        MaximumRetryAttempts: 5
        MaximumEventAgeInSeconds: 3600
      DeadLetterConfig:
        Arn: !GetAtt EventsDeadLetterQueue.Arn
```

O agendamento do relatório é declarado com o tipo `ScheduleV2` do SAM, que cria um recurso do EventBridge Scheduler com expressão, fuso horário, retentativa e DLQ parametrizados.

## 8.5 Ambiente local de demonstração

Para permitir a demonstração sem uma conta AWS, foi construído um ambiente local (`scripts/run_local.py`) que lê o próprio `template.yaml`, cria as tabelas, o bucket, o tópico e a fila em memória com a biblioteca moto, e executa as mesmas funções Lambda do diretório `src/`. Um simulador do EventBridge aplica os padrões de eventos das regras declaradas no *template*, invoca as funções de forma assíncrona com retentativas e DLQ, e um agendador local reproduz o disparo do Scheduler. **Esse ambiente é uma simulação**: ele reproduz o comportamento lógico dos fluxos, mas não substitui a validação em uma conta AWS real (latência, limites de serviço, permissões IAM efetivas e entrega de e-mails do SNS não são reproduzidos).

## 8.6 Interface web

A interface web (`frontend/`) consome a mesma API nos dois ambientes — local ou AWS, bastando configurar a URL — e permite criar pedidos (com cenários de aprovação, rejeição e falha), consultar o status e o histórico de cada pedido, publicar eventos de transação, solicitar relatórios, baixar os CSVs e acompanhar o histórico de automações, que diferencia o que foi disparado por requisição do que ocorreu automaticamente. Um indicador no topo da página informa se o ambiente é **LOCAL · SIMULADO** ou AWS.

## 8.7 Testes automatizados

Os testes foram escritos com pytest e utilizam a biblioteca moto para emular DynamoDB, S3, SNS, SQS e EventBridge, criando os recursos a partir do próprio *template*. Eles cobrem o recebimento e a validação de pedidos, a publicação de eventos, o processamento, a atualização condicional no DynamoDB, os relatórios, as falhas, a idempotência, o agendamento, as notificações e a conformidade do *template* (incluindo verificação de que não há permissões com curinga nem credenciais embutidas). Há ainda testes de integração ponta a ponta sobre HTTP no ambiente local e testes destinados ao ambiente AWS implantado, que só são executados quando a variável `TECHCOMMERCE_API_URL` é definida.

# 9 ESCALABILIDADE E DISPONIBILIDADE

A escalabilidade decorre do uso exclusivo de serviços gerenciados que escalam automaticamente. O Lambda cria novas instâncias de execução conforme aumentam os eventos, o EventBridge e o SNS absorvem picos de publicação e o DynamoDB em modo sob demanda ajusta a capacidade ao tráfego, sem planejamento prévio (AMAZON WEB SERVICES, 2026b; AMAZON WEB SERVICES, 2026l). Como a API responde com HTTP 202 logo após registrar o pedido, o tempo de resposta ao cliente não depende da duração do processamento.

A disponibilidade é favorecida porque esses serviços são regionais e operam em múltiplas zonas de disponibilidade por padrão, sem configuração adicional. Além disso, o projeto adota:

- *throttling* no API Gateway (100 requisições por segundo, com rajadas de 200), protegendo o *backend* contra abusos;
- recuperação a um ponto no tempo (PITR) na tabela de pedidos;
- arquivo de eventos por 7 dias, permitindo reprocessar eventos após a correção de uma falha;
- desacoplamento total: se uma função falhar, as demais continuam operando e os eventos aguardam na fila de retentativa ou na DLQ.

Como evolução, recomenda-se configurar concorrência reservada para funções críticas e avaliar tabelas globais do DynamoDB, caso surja um requisito de operação em múltiplas regiões.

# 10 SEGURANÇA

A segurança foi tratada segundo o modelo de responsabilidade compartilhada e as boas práticas do IAM (AMAZON WEB SERVICES, 2026i):

- **Privilégio mínimo:** cada função possui uma política própria com apenas as ações necessárias sobre os recursos específicos. A função de relatório, por exemplo, só pode consultar o índice `ByCreatedDay` e gravar objetos com o prefixo `reports/`; não existem permissões com curinga em ações ou recursos, o que é verificado por um teste automatizado.
- **Sem credenciais no código:** as funções usam a função IAM de execução, e a configuração é feita por variáveis de ambiente. Um teste verifica a ausência de chaves de acesso no repositório.
- **Proteção de dados:** o bucket S3 tem criptografia no servidor, bloqueio de acesso público e política que nega requisições sem TLS; o DynamoDB e o SQS utilizam criptografia em repouso.
- **Validação de entrada:** todos os pedidos e eventos são validados antes do processamento, e o download de relatórios bloqueia caminhos fora do prefixo permitido.
- **Superfície de exposição controlada:** os endpoints de demonstração podem ser desativados pelo parâmetro `EnableDemoEndpoints`, a origem CORS é configurável e a injeção de falhas para demonstração (`EnableFaultInjection`) fica desativada por padrão.

Para um ambiente produtivo, recomenda-se acrescentar autenticação na API (por exemplo, Amazon Cognito ou chaves de API com planos de uso), AWS WAF e o AWS Secrets Manager para eventuais segredos de integração.

# 11 MONITORAMENTO E TRATAMENTO DE FALHAS

Todas as funções emitem logs estruturados em JSON com o `correlationId`, o nome da função e o identificador do evento, o que permite rastrear um pedido por todo o fluxo com o CloudWatch Logs Insights. Cada função tem grupo de logs próprio, com retenção configurável (parâmetro `LogRetentionDays`). Métricas de negócio são publicadas no namespace `TechCommerce` usando o formato *Embedded Metric Format* (EMF), sem chamadas adicionais de API: `OrdersProcessed` (por decisão), `TransactionsUpdated` (por status) e `SalesReportsGenerated` (por gatilho).

Tabela: Alarmes do CloudWatch definidos no template
| Alarme | Condição | Ação |
|---|---|---|
| `dlq-has-messages` | Mensagens visíveis na DLQ | Notificação no tópico SNS |
| `process-order-errors` | Erros na função `process_order` | Notificação no tópico SNS |
| `update-transaction-errors` | Erros na função `update_transaction` | Notificação no tópico SNS |
| `sales-report-errors` | Erros na função `generate_sales_report` | Notificação no tópico SNS |
| `api-5xx` | Respostas 5XX no API Gateway | Notificação no tópico SNS |
Fonte: elaborada pelo autor a partir de `infrastructure/template.yaml`.

Em resumo, as falhas são tratadas em camadas: retentativas automáticas para erros transitórios, eventos `ProcessingFailed` para erros permanentes, DLQ para eventos que esgotaram as tentativas, alarmes para alertar a equipe e o arquivo de eventos do EventBridge para reprocessamento após a correção.

# 12 REDUÇÃO DE CUSTOS

No modelo *serverless*, o custo acompanha o volume de uso: não há cobrança por servidores ociosos fora dos horários de pico. Para ilustrar, a Tabela 8 apresenta uma **estimativa de ordem de grandeza** para 300 mil pedidos por mês (cerca de 10 mil por dia). Cada pedido gera aproximadamente 1 requisição na API, 5 invocações Lambda, 4 eventos personalizados no EventBridge, 20 unidades de escrita e 10 de leitura no DynamoDB e 2 publicações no SNS.

Tabela: Estimativa mensal de custo para 300 mil pedidos (valores de referência em USD)
| Serviço | Volume estimado | Preço de referência | Custo aproximado |
|---|---|---|---|
| API Gateway (REST) | 0,3 milhão de requisições | US$ 3,50 por milhão | US$ 1,05 |
| Lambda (requisições) | 1,5 milhão de invocações | US$ 0,20 por milhão | US$ 0,30 |
| Lambda (duração, arm64, 256 MB, ~100 ms) | 37.500 GB-s | US$ 0,0000133334 por GB-s | US$ 0,50 |
| EventBridge (eventos personalizados) | 1,2 milhão de eventos | US$ 1,00 por milhão | US$ 1,20 |
| DynamoDB sob demanda (escritas) | 6 milhões de unidades | US$ 0,625 por milhão | US$ 3,75 |
| DynamoDB sob demanda (leituras) | 3 milhões de unidades | US$ 0,125 por milhão | US$ 0,38 |
| SNS (publicações) | 0,6 milhão | US$ 0,50 por milhão | US$ 0,30 |
| CloudWatch Logs (ingestão) | ~3 GB | US$ 0,50 por GB | US$ 1,50 |
| EventBridge Scheduler e S3 | 30 execuções e poucos MB | — | Desprezível |
| **Total aproximado** | | | **~US$ 9 por mês** |
Fonte: elaborada pelo autor com base nas páginas oficiais de preços da AWS (AMAZON WEB SERVICES, 2026j), região us-east-1, sem considerar o nível gratuito. Valores sujeitos a alteração; a região sa-east-1 tem preços mais altos.

Para comparação, manter apenas duas instâncias Amazon EC2 `t3.medium` ligadas continuamente — configuração mínima para alta disponibilidade em um modelo tradicional — custaria cerca de US$ 60 por mês somente em computação (aproximadamente US$ 0,0416 por hora cada, na região us-east-1), sem incluir banco de dados, balanceador de carga e o esforço de aplicar atualizações e monitorar servidores. Os valores devem ser confirmados na AWS Pricing Calculator para a região escolhida; o objetivo da comparação é evidenciar a diferença de modelo de cobrança, e não fornecer um orçamento definitivo. O envio de e-mails pelo SNS é cobrado à parte, razão pela qual as assinaturas usam filtros por equipe.

Outras decisões do projeto que reduzem custos:

- funções em arquitetura arm64 (AWS Graviton), com preço por GB-s inferior ao da arquitetura x86;
- DynamoDB sob demanda, sem capacidade provisionada ociosa, e TTL para remover automaticamente registros de idempotência e de histórico;
- ciclo de vida no S3, movendo relatórios para a classe Standard-IA após 30 dias e excluindo-os após 365 dias;
- retenção limitada dos logs no CloudWatch;
- processamento assíncrono, que evita manter funções aguardando respostas de outros serviços.

# 13 RESULTADOS E DEMONSTRAÇÃO

> **Importante:** todos os resultados deste capítulo foram obtidos **localmente**, com testes automatizados e com o ambiente de simulação descrito na seção 8.5. **Nenhuma implantação foi realizada em uma conta AWS** durante a elaboração deste trabalho; portanto, não são apresentados resultados de execução na nuvem, métricas do CloudWatch ou capturas do Console da AWS.

## 13.1 Testes automatizados

A suíte foi executada em 20/11/2026 com Python 3.12.13 no Windows. Resultado: **67 testes aprovados e 3 ignorados**, em aproximadamente 21 segundos. Os 3 testes ignorados são os destinados ao ambiente AWS implantado, que dependem da variável `TECHCOMMERCE_API_URL`. A saída completa está em `entrega/evidencias/pytest_resultado.txt` e em formato JUnit em `entrega/evidencias/pytest_junit.xml`.

Tabela: Resultado da suíte de testes por arquivo
| Arquivo de teste | Escopo | Aprovados | Ignorados |
|---|---|---|---|
| `unit/test_order_validation.py` | Validação de pedidos | 9 | 0 |
| `unit/test_business_rules.py` | Regras de negócio e transições | 10 | 0 |
| `unit/test_reports_and_notifications.py` | Consolidação de relatórios, períodos e notificações | 10 | 0 |
| `unit/test_event_patterns.py` | Correspondência de padrões do EventBridge | 2 | 0 |
| `handlers/test_order_flow.py` | Fluxo 1: API, eventos, DynamoDB e idempotência | 11 | 0 |
| `handlers/test_transaction_flow.py` | Fluxo 2: transições, duplicidade e falhas | 6 | 0 |
| `handlers/test_report_and_notification_flow.py` | Fluxos 3 e 4: agendamento, S3 e SNS | 6 | 0 |
| `infrastructure/test_template.py` | Template SAM, IAM e cfn-lint | 10 | 0 |
| `integration/test_local_end_to_end.py` | Ponta a ponta via HTTP, DLQ e agendador (local) | 3 | 0 |
| `integration/test_aws_deployed.py` | Ambiente AWS implantado | 0 | 3 |
| **Total** | | **67** | **3** |
Fonte: execução do pytest pelo autor (`entrega/evidencias/pytest_resultado.txt`).

## 13.2 Validação da infraestrutura como código

O *template* foi validado com o cfn-lint (sem apontamentos) e com `sam validate --lint` da SAM CLI 1.174.0, que o reconheceu como um *template* SAM válido; o comando `sam build` empacotou as sete funções com sucesso. As saídas estão em `entrega/evidencias/validacao_template.txt`. Essas verificações confirmam a consistência sintática e estrutural do *template*, mas não substituem uma implantação real.

## 13.3 Demonstração dos fluxos (simulação local)

O script `scripts/demo_flows.py` exercitou os quatro fluxos pela API HTTP do ambiente local. Os principais resultados registrados em `entrega/evidencias/demo_flows_local.txt` foram:

- **Fluxo 1:** pedido inválido rejeitado com HTTP 400 e lista de erros; pedido válido aceito com HTTP 202 e aprovado automaticamente pelo `process_order` (status `RECEIVED` → `APPROVED`); reenvio com a mesma `Idempotency-Key` retornou o mesmo pedido; pedido de R$ 25.500,00 em boleto rejeitado por duas regras.
- **Fluxo 2:** evento `CAPTURED` atualizou o pedido para `PAID`; o mesmo evento reenviado foi ignorado por idempotência; uma transação para pedido inexistente gerou `ProcessingFailed`.
- **Fluxo 3:** a solicitação de relatório gerou dois arquivos CSV no S3 simulado (312 e 368 bytes), com 2 pedidos no período, taxa de aprovação de 50% e receita confirmada de R$ 4.079,70.
- **Fluxo 4:** foram produzidas as cinco notificações (logística, suporte, financeiro, operações e gestão) e o histórico registrou 18 execuções, separando chamadas de API e execuções automáticas.

Os testes de integração também verificaram o cenário de falha transitória: um pedido com o SKU de injeção de falhas foi executado 3 vezes (a original e 2 retentativas), enviado para a DLQ e gerou a notificação simulada do alarme. As Figuras 10 e 11 mostram a interface web conectada ao ambiente local.

![Interface web conectada ao ambiente local simulado: pedidos e histórico de automações](entrega/evidencias/01_console_local_visao_geral.png)
Fonte: captura de tela do ambiente local (simulação; não representa a AWS).

![Detalhe de um pedido com a linha do tempo de status (ambiente local simulado)](entrega/evidencias/02_console_local_detalhe_pedido.png)
Fonte: captura de tela do ambiente local (simulação; não representa a AWS).

## 13.4 O que depende de implantação na AWS

Os itens a seguir só podem ser comprovados após a implantação em uma conta AWS, com credenciais e autorização adequadas, usando `sam deploy --guided` (instruções no `README.md`):

- execução real das funções e das regras do EventBridge e do Scheduler, com os respectivos logs e métricas no CloudWatch;
- aplicação efetiva das políticas IAM e das políticas de recursos (S3, SQS);
- entrega de e-mails pelo SNS, que exige confirmação da assinatura;
- latência, concorrência e comportamento sob carga;
- execução dos 3 testes de integração com `TECHCOMMERCE_API_URL` apontando para a API implantada;
- custos reais, que devem ser acompanhados pelo AWS Cost Explorer.

## 13.5 Limitações

O ambiente local reproduz a lógica dos serviços, mas não seus limites, sua latência nem seu modelo de permissões. O *gateway* de pagamento é simulado por um endpoint de demonstração, e a API não possui autenticação, decisão aceitável para o contexto acadêmico, mas que deve ser revista para uso em produção.

# 14 CONCLUSÃO

Este trabalho demonstrou como uma arquitetura *serverless* orientada a eventos pode resolver os problemas operacionais da TechCommerce. O AWS Lambda eliminou a necessidade de servidores dedicados para a lógica de negócio, e o Amazon EventBridge desacoplou os componentes, permitindo que cada etapa — validação, processamento, atualização de pagamentos, relatórios e notificações — evolua e escale de forma independente. O EventBridge Scheduler substituiu a geração manual de relatórios por uma rotina automática e configurável.

Do ponto de vista técnico, destacam-se as práticas que tornam a automação confiável: idempotência baseada em escritas condicionais, controle explícito das transições de estado, distinção entre falhas permanentes e transitórias, retentativas com DLQ, alarmes, logs estruturados com correlação e permissões de privilégio mínimo, tudo descrito como código no AWS SAM. A estimativa de custos indicou que, para o volume considerado, o modelo de pagamento por uso tende a ser significativamente mais econômico que uma infraestrutura dimensionada para os picos.

Os 67 testes aprovados, a validação do *template* e a demonstração ponta a ponta comprovam o funcionamento da solução **em ambiente local simulado**. Como próximos passos, recomenda-se implantar o *stack* em uma conta AWS, executar os testes de integração contra a API real, coletar métricas de desempenho e custos efetivos, adicionar autenticação à API e complementar a fundamentação teórica com o material das Unidades 1 a 4 da disciplina.

# REFERÊNCIAS

REF: AMAZON WEB SERVICES. **AWS Lambda**. [S. l.], 2026a. Disponível em: https://aws.amazon.com/pt/lambda/. Acesso em: 20 nov. 2026.

REF: AMAZON WEB SERVICES. **What is AWS Lambda?** AWS Lambda Developer Guide. [S. l.], 2026b. Disponível em: https://docs.aws.amazon.com/lambda/latest/dg/welcome.html. Acesso em: 20 nov. 2026.

REF: AMAZON WEB SERVICES. **What is Amazon EventBridge?** Amazon EventBridge User Guide. [S. l.], 2026c. Disponível em: https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-what-is.html. Acesso em: 20 nov. 2026.

REF: AMAZON WEB SERVICES. **Amazon EventBridge event patterns**. Amazon EventBridge User Guide. [S. l.], 2026d. Disponível em: https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-event-patterns.html. Acesso em: 20 nov. 2026.

REF: AMAZON WEB SERVICES. **What is Amazon EventBridge Scheduler?** EventBridge Scheduler User Guide. [S. l.], 2026e. Disponível em: https://docs.aws.amazon.com/scheduler/latest/UserGuide/what-is-scheduler.html. Acesso em: 20 nov. 2026.

REF: AMAZON WEB SERVICES. **Invoking a Lambda function asynchronously**. AWS Lambda Developer Guide. [S. l.], 2026f. Disponível em: https://docs.aws.amazon.com/lambda/latest/dg/invocation-async.html. Acesso em: 20 nov. 2026.

REF: AMAZON WEB SERVICES. **What is the AWS Serverless Application Model (AWS SAM)?** [S. l.], 2026g. Disponível em: https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/what-is-sam.html. Acesso em: 20 nov. 2026.

REF: AMAZON WEB SERVICES. **Serverless Applications Lens – AWS Well-Architected Framework**. [S. l.], 2026h. Disponível em: https://docs.aws.amazon.com/wellarchitected/latest/serverless-applications-lens/welcome.html. Acesso em: 20 nov. 2026.

REF: AMAZON WEB SERVICES. **Security best practices in IAM**. AWS Identity and Access Management User Guide. [S. l.], 2026i. Disponível em: https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html. Acesso em: 20 nov. 2026.

REF: AMAZON WEB SERVICES. **Páginas de preços**: AWS Lambda (https://aws.amazon.com/lambda/pricing/), Amazon EventBridge (https://aws.amazon.com/eventbridge/pricing/), Amazon API Gateway (https://aws.amazon.com/api-gateway/pricing/), Amazon DynamoDB (https://aws.amazon.com/dynamodb/pricing/), Amazon SNS (https://aws.amazon.com/sns/pricing/), Amazon CloudWatch (https://aws.amazon.com/cloudwatch/pricing/) e Amazon EC2 (https://aws.amazon.com/ec2/pricing/on-demand/). [S. l.], 2026j. Acesso em: 20 nov. 2026.

REF: AMAZON WEB SERVICES. **Tipos de computação em nuvem**. [S. l.], 2026k. Disponível em: https://aws.amazon.com/pt/types-of-cloud-computing/. Acesso em: 20 nov. 2026.

REF: AMAZON WEB SERVICES. **What is Amazon DynamoDB?** Amazon DynamoDB Developer Guide. [S. l.], 2026l. Disponível em: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html. Acesso em: 20 nov. 2026.

REF: BALDINI, I. *et al*. Serverless computing: current trends and open problems. *In*: CHAUDHARY, S.; SOMANI, G.; BUYYA, R. (ed.). **Research Advances in Cloud Computing**. Singapore: Springer, 2017. p. 1-20.

REF: FOWLER, M. **What do you mean by "Event-Driven"?** [S. l.], 2017. Disponível em: https://martinfowler.com/articles/201701-event-driven.html. Acesso em: 20 nov. 2026.

REF: HOHPE, G.; WOOLF, B. **Enterprise Integration Patterns**: designing, building, and deploying messaging solutions. Boston: Addison-Wesley, 2003.

REF: JONAS, E. *et al*. **Cloud programming simplified**: a Berkeley view on serverless computing. Berkeley: University of California, 2019. (arXiv:1902.03383). Disponível em: https://arxiv.org/abs/1902.03383. Acesso em: 20 nov. 2026.

REF: MASSARONII. **Como criar uma automação com AWS Lambda e Serverless Framework**. DEV Community, [s. d.]. Disponível em: https://dev.to/massaronii/como-criar-uma-automacao-com-aws-lambda-e-serverless-framework-3l2j. Acesso em: 20 nov. 2026.

REF: MELL, P.; GRANCE, T. **The NIST definition of cloud computing**. Gaithersburg: National Institute of Standards and Technology, 2011. (NIST Special Publication 800-145).

REF: ROBERTS, M. **Serverless architectures**. [S. l.], 2018. Disponível em: https://martinfowler.com/articles/serverless.html. Acesso em: 20 nov. 2026.

REF: UNIFECAF. **Cloud Computing for Software Development**: material didático, Unidades 1 a 4. [A COMPLEMENTAR: o material não estava disponível durante a elaboração deste relatório; inserir aqui as referências completas das unidades utilizadas.]

# APÊNDICE A – CÓDIGO-FONTE E EXECUÇÃO

O código-fonte completo da parte prática — funções Lambda, *template* AWS SAM, testes, ambiente local, interface web, diagramas e evidências — está disponível em: {{REPOSITORIO}}. O arquivo `README.md` do projeto contém as instruções detalhadas.

Tabela: Estrutura do projeto
| Pasta / arquivo | Conteúdo |
|---|---|
| `src/handlers/` | Pontos de entrada das sete funções Lambda |
| `src/services/`, `src/repositories/`, `src/models/`, `src/utils/` | Regras de negócio, idempotência, eventos, relatórios, notificações, acesso a dados e utilitários |
| `infrastructure/template.yaml` | Infraestrutura como código (AWS SAM) |
| `infrastructure/samconfig.toml` | Parâmetros padrão de *build* e implantação (sem credenciais) |
| `local_runtime/`, `scripts/run_local.py` | Ambiente local que simula EventBridge, Scheduler e serviços AWS |
| `frontend/` | Interface web de demonstração |
| `tests/` | Testes unitários, de *handlers*, de infraestrutura e de integração |
| `diagrams/` | Diagramas Mermaid (fonte e PNG) |
| `entrega/` | Este relatório, roteiro do vídeo e evidências |
Fonte: elaborada pelo autor.

Comandos principais (PowerShell, a partir da pasta do projeto):

```
# instalação
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# testes automatizados e validação do template
python -m pytest -v
cfn-lint infrastructure/template.yaml
sam validate --lint -t infrastructure/template.yaml

# demonstração local (simulação, sem conta AWS)
python scripts/run_local.py --open          # interface em http://127.0.0.1:8000
python scripts/demo_flows.py                # executa os quatro fluxos pelo terminal

# implantação na AWS (requer conta e credenciais configuradas)
cd infrastructure
sam build
sam deploy --guided
```

Tabela: Endpoints da API
| Método e caminho | Função | Descrição |
|---|---|---|
| `POST /orders` | `create_order` | Recebe e valida um pedido; publica `OrderReceived` |
| `GET /orders` e `GET /orders/{orderId}` | `read_api` | Lista pedidos e consulta status e histórico |
| `POST /transactions` | `demo_events` | Simula o *gateway* publicando `TransactionStatusChanged` |
| `POST /reports` | `demo_events` | Publica `SalesReportRequested` (relatório sob demanda) |
| `GET /reports` e `GET /reports/download` | `read_api` | Lista e baixa os relatórios CSV do S3 |
| `GET /automations` | `read_api` | Histórico das execuções automáticas |
| `GET /health` | `read_api` | Situação e ambiente da API |
Fonte: elaborada pelo autor a partir de `infrastructure/template.yaml`.
