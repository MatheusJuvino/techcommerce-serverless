# Fluxo de geração automática de relatórios (Fluxo 3)

O agendamento é definido no parâmetro `ReportScheduleExpression` do template
(padrão `cron(0 6 * * ? *)`, fuso `America/Sao_Paulo`, ou seja, todos os dias às 06:00).
Também é possível solicitar o relatório sob demanda publicando `SalesReportRequested`.

```mermaid
flowchart TD
    S(["EventBridge Scheduler<br/>cron(0 6 * * ? *) America/Sao_Paulo"]) -->|"Input: trigger=schedule,<br/>scheduledTime"| R
    D([POST /reports → SalesReportRequested]) --> RULE{{Regra SalesReportRequested}} --> R
    R[λ generate_sales_report] --> I{Execução já realizada?<br/>chave scheduledTime / eventId}
    I -- Sim --> I1[Ignora reentrega] --> F([Fim])
    I -- Não --> P[Resolve período<br/>last_24h · today · yesterday · last_7d]
    P --> Q[(DynamoDB Query no GSI ByCreatedDay<br/>dia a dia, paginado)]
    Q --> C[Consolida vendas<br/>status, receita, ticket médio, top produtos]
    C --> CSV[Gera 2 CSVs<br/>detalhado + resumo]
    CSV --> S3[(S3: reports/AAAA/MM/DD/*.csv<br/>SSE-AES256)]
    S3 --> E[PutEvents SalesReportGenerated]
    E --> N[λ notification_dispatcher → SNS gestão]
    R -. logs JSON + métrica EMF SalesReportsGenerated .-> CW[CloudWatch]
    R -. erro transitório: 2 retentativas .-> DLQ[[SQS DLQ]]
    S -. falha de entrega: RetryPolicy 3x .-> DLQ
```

```mermaid
sequenceDiagram
    autonumber
    participant SCH as EventBridge Scheduler
    participant GR as λ generate_sales_report
    participant DB as DynamoDB (GSI ByCreatedDay)
    participant S3 as Amazon S3
    participant EB as EventBridge
    participant CW as CloudWatch Logs

    SCH->>GR: invoke (Input JSON com scheduledTime)
    GR->>GR: idempotência (report#schedule#scheduledTime)
    GR->>DB: Query createdDay = hoje/ontem
    DB-->>GR: pedidos do período
    GR->>GR: consolida e gera CSV
    GR->>S3: PutObject sales-report-*.csv e sales-summary-*.csv
    GR->>EB: PutEvents SalesReportGenerated
    GR->>CW: log estruturado + métrica EMF
```
