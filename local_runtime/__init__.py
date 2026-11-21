"""Simulador local da arquitetura (NÃO é implantado na AWS).

Permite demonstrar todos os fluxos sem conta AWS:
- DynamoDB, S3, SNS, SQS e EventBridge PutEvents são emulados em memória pelo `moto`,
  de modo que o MESMO código boto3 das funções Lambda é executado;
- o roteamento das regras do EventBridge, as retentativas assíncronas do Lambda,
  a DLQ e o EventBridge Scheduler são reproduzidos a partir do `infrastructure/template.yaml`.
Todos os resultados obtidos aqui são simulações locais e são identificados como tal na interface.
"""
