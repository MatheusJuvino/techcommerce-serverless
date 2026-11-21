# Fluxo de eventos entre Amazon EventBridge e AWS Lambda

Cada evento possui `source`, `detail-type` e um envelope `detail = {metadata, data}`.
As regras abaixo estão declaradas no template e são aplicadas também pelo simulador local.

```mermaid
flowchart LR
    subgraph PRODUTORES["Produtores (PutEvents)"]
        P1["λ create_order<br/>techcommerce.orders"]
        P2["Gateway / λ demo_events<br/>techcommerce.payments"]
        P3["λ demo_events<br/>techcommerce.reports"]
        P4["λ process_order<br/>λ update_transaction<br/>λ generate_sales_report"]
    end

    BUS{{"Amazon EventBridge<br/>techcommerce-&lt;env&gt;-bus"}}

    subgraph REGRAS["Regras (event patterns)"]
        R1["order-received<br/>detail-type: OrderReceived"]
        R2["transaction-status-changed<br/>detail-type: TransactionStatusChanged"]
        R3["sales-report-requested<br/>detail-type: SalesReportRequested"]
        R4["operational-notifications<br/>OrderApproved · OrderRejected ·<br/>TransactionUpdated · ProcessingFailed ·<br/>SalesReportGenerated"]
    end

    subgraph ALVOS["Alvos (AWS Lambda, invocação assíncrona)"]
        L1["λ process_order"]
        L2["λ update_transaction"]
        L3["λ generate_sales_report"]
        L4["λ notification_dispatcher"]
    end

    SCH(["EventBridge Scheduler"]) --> L3
    P1 -->|OrderReceived| BUS
    P2 -->|TransactionStatusChanged| BUS
    P3 -->|SalesReportRequested| BUS
    P4 -->|eventos de resultado| BUS
    BUS --> R1 --> L1
    BUS --> R2 --> L2
    BUS --> R3 --> L3
    BUS --> R4 --> L4
    L1 & L2 & L3 -.->|publicam resultado| BUS
    R1 & R2 & R3 & R4 -.->|"RetryPolicy + DeadLetterConfig"| DLQ[[SQS DLQ]]
    L1 & L2 & L3 & L4 -.->|"EventInvokeConfig: 2 retentativas → OnFailure"| DLQ
```

## Tratamento de falhas e idempotência

```mermaid
flowchart TD
    E([Evento entregue ao Lambda]) --> K{PutItem condicional<br/>da chave de idempotência}
    K -- já COMPLETED --> DUP[Retorna resultado anterior<br/>DUPLICATE_IGNORED]
    K -- obtida --> X[Executa a lógica]
    X -- sucesso --> OK[Marca COMPLETED com resultado]
    X -- erro permanente<br/>dados inválidos, pedido inexistente,<br/>transição proibida --> PF[Marca COMPLETED como FAILED<br/>publica ProcessingFailed → SNS operações<br/>NÃO relança: sem retentativa inútil]
    X -- erro transitório<br/>throttling, indisponibilidade --> TR[Libera a chave e relança a exceção]
    TR --> RT{Retentativas<br/>restantes?}
    RT -- sim --> E
    RT -- não --> DLQ[[Dead Letter Queue]] --> AL[Alarme CloudWatch → SNS]
```

## Exemplo de evento

```json
{
  "source": "techcommerce.orders",
  "detail-type": "OrderReceived",
  "detail": {
    "metadata": {
      "eventId": "1b0d3c5e-…",
      "correlationId": "4f35da88-…",
      "occurredAt": "2026-11-21T00:51:44.315Z",
      "schemaVersion": "1.0",
      "producer": "create_order"
    },
    "data": { "orderId": "ORD-2C52633F0D45", "total": 4079.7, "paymentMethod": "PIX", "itemsCount": 3 }
  }
}
```
