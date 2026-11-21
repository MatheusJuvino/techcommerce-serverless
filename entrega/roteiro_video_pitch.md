# Roteiro do vídeo pitch — TechCommerce Serverless

**Aluno:** Matheus Juvino da Silva — RA 147779
**Disciplina:** Cloud Computing for Software Development — UniFECAF
**Tema:** Automação de processos em nuvem com AWS Lambda e Amazon EventBridge
**Duração:** 3min51s (limite: 4 minutos)
**Link do vídeo (YouTube, não listado):** `[INSERIR O LINK APÓS A PUBLICAÇÃO]`

O vídeo já está montado: slides animados, diagrama de arquitetura, trecho real do
`template.yaml` e a demonstração gravada automaticamente na interface web. Falta só a sua voz.
Os tempos e as falas abaixo vêm de `video/roteiro.json`, que é a fonte usada para gerar o vídeo.

> A demonstração (cenas 5 e 6) usa o **ambiente local simulado**. O vídeo mostra isso o tempo todo
> num selo na tela, e a narração da cena 5 diz isso explicitamente. Não apresente essas cenas como
> se fossem o Console da AWS.

## Como gravar a narração

1. Gerar o vídeo sem narração (cerca de 6 minutos; só é preciso refazer se mudar algo no projeto):

   ```powershell
   pip install -r video/requirements.txt
   python video/build_video.py
   ```

   Saídas em `entrega/video/`: `video_pitch_sem_narracao.mp4`, `video_guia_com_falas.mp4`
   (mesmo vídeo com as falas na tela, para ensaiar), `legendas_narracao.srt` e `falas.json`.

2. Abrir o estúdio de narração:

   ```powershell
   python video/estudio_narracao.py
   ```

   O navegador abre com o vídeo, um teleprompter (fala atual em destaque e a próxima embaixo) e o
   medidor do microfone. Clique em **Gravar**: há uma contagem 3-2-1 e o vídeo começa. Dá para
   gravar o vídeo inteiro de uma vez ou cena por cena; se errar uma cena, regrave só ela. O áudio
   é nivelado automaticamente e o resultado sai em `entrega/video/video_pitch_final.mp4`.

3. Alternativa: gravar a voz em outro aplicativo (celular, Audacity) assistindo ao
   `video_guia_com_falas.mp4` e juntar depois:

   ```powershell
   python video/estudio_narracao.py --audio minha_voz.m4a --offset 0.8
   ```

   `--offset` descarta segundos do início do áudio para alinhar a voz ao vídeo (valor negativo
   atrasa a voz).

Ritmo: cerca de 135 palavras por minuto. Cada fala tem uma janela própria; se terminar antes, só
espere a próxima aparecer.

---

## Cena 1 — Abertura e problema · 0:00 a 0:25

**Na tela:** título do projeto com os ícones de Lambda e EventBridge e os seus dados; depois
"O desafio da TechCommerce" com quatro cartões (pedidos lentos, pagamentos desatualizados,
relatórios manuais, equipes sem aviso).

| Início | Fala |
|---|---|
| 0:00 | Olá! Eu sou Matheus Juvino da Silva e este é o projeto de automação de processos em nuvem para a TechCommerce, um e-commerce fictício. |
| 0:10 | A empresa sofria com quatro problemas: pedidos demorando para ser processados, pagamentos que não atualizavam o pedido, |
| 0:18 | relatórios de vendas feitos à mão e equipes que não eram avisadas quando algo dava errado. |

## Cena 2 — Proposta · 0:25 a 0:45

**Na tela:** "Sem servidores", as funções Lambda surgindo e o barramento do EventBridge ligando
todas elas com pulsos de eventos; depois o efeito de escala.

| Início | Fala |
|---|---|
| 0:25 | A solução é uma arquitetura serverless orientada a eventos na AWS. |
| 0:30 | Não existe servidor para administrar: cada etapa é uma função AWS Lambda, |
| 0:35 | e o Amazon EventBridge liga essas funções por meio de eventos. |
| 0:40 | Assim, cada parte escala e falha de forma independente. |

## Cena 3 — Arquitetura · 0:45 a 1:25

**Na tela:** o diagrama é montado e os eventos percorrem o caminho real: Cliente → API Gateway →
`create_order` → DynamoDB e EventBridge → `process_order`; `TransactionStatusChanged` →
`update_transaction`; Scheduler → `generate_sales_report` → S3; `notification_dispatcher` → SNS e
equipes; faixa do CloudWatch e da fila DLQ.

| Início | Fala |
|---|---|
| 0:45 | O pedido chega pelo API Gateway. |
| 0:48 | A função create_order valida os dados, grava no DynamoDB e publica o evento OrderReceived no barramento do EventBridge. |
| 0:56 | A partir daí tudo é automático: uma regra entrega o evento à função process_order, que aplica as regras de negócio. |
| 1:04 | Os pagamentos chegam como eventos TransactionStatusChanged; |
| 1:08 | o EventBridge Scheduler dispara o relatório diário, salvo em CSV no S3; |
| 1:13 | e a função de notificações avisa cada equipe pelo SNS. |
| 1:18 | O CloudWatch concentra logs, métricas e alarmes. |

## Cena 4 — Lambda e EventBridge no template SAM · 1:25 a 1:50

**Na tela:** trecho real de `infrastructure/template.yaml` com destaque na função, no filtro da
regra (`source` e `detail-type`), na `RetryPolicy` e na `DeadLetterConfig`; depois o agendamento
`cron(0 6 * * ? *)` com fuso `America/Sao_Paulo`.

| Início | Fala |
|---|---|
| 1:25 | Toda a infraestrutura está descrita como código com o AWS SAM. |
| 1:30 | Aqui está a regra: ela filtra eventos pela origem e pelo tipo, tem retentativas e uma fila DLQ para o que falhar. |
| 1:39 | E aqui o agendamento: todo dia às seis da manhã, no horário de São Paulo, o relatório é gerado sozinho. |

## Cena 5 — Demonstração: pedido automatizado · 1:50 a 2:40

**Na tela (ambiente local simulado):** destaque no selo LOCAL · SIMULADO e no aviso; pedido
aprovável enviado (HTTP 202 · RECEIVED); o pedido passa a APPROVED; histórico mostra as execuções
AUTOMÁTICO; evento de pagamento CAPTURED publicado e o pedido vira PAID; pedido acima do limite é
REJECTED e o SNS avisa o suporte.

| Início | Fala |
|---|---|
| 1:50 | Agora a demonstração. Ela roda num ambiente local que simula o EventBridge e os serviços da AWS com o mesmo código das funções — não é a conta AWS. |
| 2:01 | Envio um pedido... a API responde na hora com "recebido", |
| 2:06 | e segundos depois o pedido aparece como aprovado. |
| 2:10 | Repare no histórico: essa aprovação não foi pedida por ninguém, foi o EventBridge que acionou o Lambda. |
| 2:18 | Agora o gateway de pagamento confirma a captura, e o pedido vira "pago". |
| 2:26 | Um pedido acima do limite é rejeitado automaticamente e o suporte é notificado. |

## Cena 6 — Demonstração: relatório agendado · 2:40 a 3:07

**Na tela (ambiente local simulado):** clique em "Disparar agendamento"; os dois CSV aparecem na
lista; o conteúdo real do CSV de resumo é exibido com receita, ticket médio e produtos mais
vendidos em destaque; histórico mostra o Scheduler e a notificação para a gestão.

| Início | Fala |
|---|---|
| 2:40 | No relatório, em vez de esperar até as seis da manhã, eu disparo o agendamento agora. |
| 2:47 | A função consolida as vendas e grava dois arquivos CSV: o detalhe dos pedidos e o resumo, |
| 2:54 | com receita, ticket médio e produtos mais vendidos. |
| 2:59 | A gestão recebe a notificação de que o relatório está pronto. |

## Cena 7 — Confiabilidade, segurança e custos · 3:07 a 3:34

**Na tela:** três cartões (Confiável, Seguro, Econômico) e um terminal com linhas reais de
`entrega/evidencias/pytest_resultado.txt`, terminando em `67 passed, 3 skipped`.

| Início | Fala |
|---|---|
| 3:07 | A solução trata eventos duplicados com idempotência, separa erros temporários de erros definitivos, usa retentativas, fila DLQ e alarmes. |
| 3:16 | Cada função tem só as permissões de que precisa. |
| 3:20 | São sessenta e sete testes automatizados aprovados. |
| 3:23 | E, como é serverless, o custo acompanha o uso: a estimativa é de cerca de nove dólares por mês para trezentos mil pedidos. |

## Cena 8 — Encerramento · 3:34 a 3:51

**Na tela:** resultado do projeto, `sam deploy --guided` como próximo passo, link do repositório
no GitHub e "Obrigado!" com o seu nome.

| Início | Fala |
|---|---|
| 3:34 | Com Lambda e EventBridge, a TechCommerce passa a processar pedidos, pagamentos e relatórios automaticamente, com escala e custo sob controle. |
| 3:42 | O próximo passo é implantar o stack na AWS com um único comando do SAM. Obrigado! |

---

## Checklist antes de publicar

- [ ] Assistir ao `video_pitch_final.mp4` inteiro e conferir se a voz acompanha as cenas.
- [ ] Duração ≤ 4:00 (o vídeo tem 3:51).
- [ ] Vídeo publicado no YouTube como **Não listado**.
- [ ] Link inserido no topo deste roteiro e em `docs/capa.json` (`video_url`), seguido de
      `python scripts/build_report.py` para atualizar o Apêndice B do PDF.
