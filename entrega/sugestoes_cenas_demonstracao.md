# Sugestões de cenas e comandos para a gravação

Complementa `entrega/roteiro_video_pitch.md`. Todos os comandos devem ser executados na pasta
`techcommerce-serverless` (PowerShell no Windows).

## 1. Preparação (antes de gravar)

```powershell
# 1) Ambiente Python (uma única vez)
uv venv .venv --python 3.12          # ou: py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2) Conferir os testes (o resultado aparece na cena 7)
$env:PYTHONIOENCODING = "utf-8"
python -m pytest -q

# 3) Subir o ambiente local simulado (deixe este terminal aberto)
python scripts/run_local.py --port 8000 --schedule-interval 0 --open
```

- `--schedule-interval 0` desativa o disparo periódico do agendador local, para que o relatório
  só seja gerado quando você clicar em **⏰ Disparar agendamento** (evita entradas inesperadas
  no histórico durante a gravação). Sem esse parâmetro, o agendador local dispara a cada 120 s.
- Para começar com a tela limpa, reinicie o `run_local.py` imediatamente antes de gravar: os
  dados ficam apenas em memória.
- Navegador em tela cheia (F11), zoom de 110% a 125% para legibilidade, tema claro.
- Feche abas e notificações; não exiba `.env`, chaves ou e-mails reais.

## 2. Material de apoio para as cenas

| Cena | O que abrir | Arquivo / ação |
|---|---|---|
| 1–2 | Slides de abertura e proposta | Criar 2 slides simples (título; problemas; solução) |
| 3 | Diagrama de arquitetura | `diagrams/png/arquitetura_icones.png` (alternativa: `diagrams/png/arquitetura_1.png`) |
| 4 | Template SAM no editor | `infrastructure/template.yaml` → buscar `OrderReceivedRule` e `DailySalesReportSchedule` |
| 5 | Interface web | `http://127.0.0.1:8000` → cards **1 Novo pedido**, **2 Evento de transação**, **Pedidos**, **Histórico das automações** |
| 6 | Interface web | Card **3 Relatórios de vendas** → **⏰ Disparar agendamento** → baixar o `sales-summary-*.csv` |
| 7 | Terminal + slide | Saída de `python -m pytest -q`; slide "Confiável / Seguro / Econômico" |
| 8 | Slide final | Diagrama reduzido + agradecimento |

Diagramas de fluxo adicionais, caso queira usar cortes rápidos: `diagrams/png/fluxo_pedidos_1.png`,
`diagrams/png/fluxo_relatorios_1.png` e `diagrams/png/fluxo_eventos_1.png`.

## 3. Passo a passo da demonstração (cenas 5 e 6)

1. Mostrar o selo **LOCAL · SIMULADO** no topo da página (é ele que deixa claro que não é a AWS).
2. **✔ Aprovável** → **Enviar pedido (POST /orders)**. A resposta aparece com HTTP 202 e status
   `RECEIVED`; em 1–2 s o pedido passa a `APPROVED`.
3. No **Histórico das automações**, apontar as linhas marcadas como **AUTOMÁTICO**
   (`process_order` e `notification_dispatcher`, acionados por "EventBridge Rule") e a caixa da
   notificação SNS para a equipe de logística.
4. Clicar no pedido na lista para mostrar a linha do tempo de status.
5. Card **Evento de transação**: selecionar o pedido aprovado, escolher `CAPTURED (pago)` →
   **Publicar evento**. O pedido passa a `PAID` e o financeiro é notificado.
6. Opcional (5 s): clicar em **Publicar evento** de novo. A interface gera um novo
   `transactionId`, e capturar um pedido já `PAID` não é uma transição permitida: o histórico
   mostra `FAILED` em `update_transaction` e a notificação `ProcessingFailed` para operações
   (controle de estados). A deduplicação do mesmo evento (`DUPLICATE_IGNORED`) aparece na saída
   de `python scripts/demo_flows.py`, que reenvia o mesmo `transactionId`.
7. **✖ Acima do limite** → **Enviar pedido** → status `REJECTED` com o motivo, notificação para o
   suporte.
8. Card **Relatórios de vendas** → **⏰ Disparar agendamento** → o novo par de CSVs aparece na
   lista; baixar e abrir o resumo; apontar a entrada "EventBridge Scheduler" no histórico.

Cena extra opcional (se sobrar tempo): **⚡ Falha temporária** → o painel **Barramento de eventos
(simulação local)** mostra as retentativas e, após cerca de 6 s, o evento chega à **Dead Letter
Queue** e o alarme simulado notifica a equipe de operações.

## 4. Demonstração por linha de comando (alternativa à interface)

```powershell
# Executa os quatro fluxos contra um ambiente local temporário e imprime o passo a passo
python scripts/demo_flows.py

# Contra o servidor local já em execução
python scripts/demo_flows.py --api-url http://127.0.0.1:8000/api
```

## 5. Versão AWS (somente se o stack for implantado antes da gravação)

Requer conta AWS, credenciais configuradas (`aws configure`) e autorização para criar recursos.

```powershell
cd infrastructure
sam build
sam deploy --guided            # aceitar os padrões de samconfig.toml ou ajustar região/e-mails
cd ..

# URL da API exibida nos Outputs (ApiUrl); usar na interface (botão ⚙ API) ou nos scripts
python scripts/demo_flows.py --api-url https://<id>.execute-api.<regiao>.amazonaws.com/dev

# Logs em tempo real de uma função
sam logs -n ProcessOrderFunction --stack-name techcommerce-serverless-dev --tail

# Disparar o agendamento real sem esperar o horário: Console → EventBridge Scheduler →
# techcommerce-dev-sales-report (ou publicar SalesReportRequested)
python scripts/send_test_event.py --help
```

Nesse caso, as cenas 5 e 6 podem mostrar também o Console da AWS (CloudWatch Logs, tabela
DynamoDB, objeto no S3). Ao final, remova os recursos com `sam delete` para evitar custos.
Somente apresente como "execução na AWS" o que tiver sido efetivamente executado na conta.
