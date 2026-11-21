# Arquitetura geral — TechCommerce Serverless

Visão geral dos serviços AWS e de suas conexões. Os nomes de recursos seguem o template
`infrastructure/template.yaml` (prefixo `techcommerce-<ambiente>-`).

Versão com ícones oficiais da AWS (pacote `logos` do Iconify), usada no relatório:
![Arquitetura com ícones AWS](png/arquitetura_icones.png)

## Diagrama geral (Mermaid)

```mermaid
flowchart LR
    client["Cliente / Front-end"]
    gateway["Gateway de pagamento<br/>(produtor externo)"]
    teams["Equipes: logística, atendimento,<br/>financeiro, operações, gestão"]

    subgraph AWS["AWS Cloud — sa-east-1"]
        api["Amazon API Gateway<br/>(REST, throttling, CORS)"]

        subgraph SYNC["Lambda síncronas (API)"]
            create["λ create_order"]
            read["λ read_api"]
            demo["λ demo_events"]
        end

        bus{{"Amazon EventBridge<br/>barramento techcommerce-bus"}}
        scheduler(["EventBridge Scheduler<br/>cron(0 6 * * ? *)"])

        subgraph ASYNC["Lambda assíncronas (eventos)"]
            process["λ process_order"]
            tx["λ update_transaction"]
            report["λ generate_sales_report"]
            notify["λ notification_dispatcher"]
        end

        subgraph DATA["Dados"]
            orders[("DynamoDB orders")]
            idem[("DynamoDB idempotency")]
            audit[("DynamoDB automation-log")]
            s3[("S3 reports/*.csv")]
        end

        subgraph OPS["Operação e resiliência"]
            sns["Amazon SNS"]
            dlq[["SQS Dead Letter Queue"]]
            cw["CloudWatch Logs,<br/>métricas e alarmes"]
        end
    end

    client -->|HTTPS| api
    api --> SYNC
    create -->|grava pedido| orders
    create -->|OrderReceived| bus
    demo -->|eventos de teste| bus
    gateway -.->|TransactionStatusChanged| bus
    read -->|consultas| DATA

    bus -->|OrderReceived| process
    bus -->|TransactionStatusChanged| tx
    bus -->|SalesReportRequested| report
    scheduler -->|agendamento| report
    bus -->|eventos operacionais| notify

    process -->|status| orders
    tx -->|transação| orders
    report -->|CSV| s3
    ASYNC -.->|eventos de resultado| bus
    ASYNC -.->|idempotência| idem
    SYNC & ASYNC -.->|histórico| audit
    notify --> sns --> teams
    ASYNC -.->|falha após retentativas| dlq
    dlq -.-> cw
    cw -.->|alarme| sns
```

## Responsabilidade de cada serviço

| Serviço | Papel na solução |
|---|---|
| Amazon API Gateway | Porta de entrada HTTPS; throttling; CORS; integração Lambda Proxy |
| AWS Lambda | 7 funções com responsabilidade única (receber, processar, atualizar transação, relatório, notificar, consultar, publicar eventos de demonstração) |
| Amazon EventBridge | Barramento customizado; regras por `source`/`detail-type`; arquivo para replay |
| EventBridge Scheduler | Agendamento do relatório (cron com fuso America/Sao_Paulo, retentativas e DLQ) |
| Amazon DynamoDB | Pedidos (status + histórico), chaves de idempotência e histórico de automações |
| Amazon S3 | Relatórios CSV criptografados, privados, com ciclo de vida |
| Amazon SNS | Notificações às equipes, com atributos para *filter policies* |
| Amazon SQS | Dead Letter Queue de eventos/invocações que falharam |
| Amazon CloudWatch | Logs JSON estruturados, métricas EMF e alarmes (DLQ, erros, 5XX) |
