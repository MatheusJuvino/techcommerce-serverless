"""Hierarquia de erros que define o comportamento de retentativa.

- PermanentError: repetir não resolve (dados inválidos, pedido inexistente, transição proibida).
  A função registra a falha, publica ProcessingFailed e encerra SEM lançar exceção,
  evitando retentativas inúteis.
- TransientError: falha temporária (throttling, indisponibilidade). A exceção é propagada
  para que o Lambda/EventBridge apliquem a política de retentativas e, ao esgotá-las,
  enviem o evento para a Dead Letter Queue.
"""


class TechCommerceError(Exception):
    pass


class PermanentError(TechCommerceError):
    pass


class ValidationError(PermanentError):
    def __init__(self, message: str, details: list[str] | None = None):
        super().__init__(message)
        self.details = details or []


class NotFoundError(PermanentError):
    pass


class InvalidTransitionError(PermanentError):
    pass


class TransientError(TechCommerceError):
    pass


class EventPublishError(TransientError):
    pass


class IdempotencyInProgressError(TransientError):
    pass
