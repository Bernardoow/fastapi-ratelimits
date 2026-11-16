# Respostas e cabeçalhos

## Quando uma requisição é recusada

| Status | Causa | O que o cliente recebe |
| --- | --- | --- |
| `429 Too Many Requests` | Uma regra recusou a requisição. | O cabeçalho `Retry-After`, com uma estimativa em segundos inteiros baseada na janela da regra que recusou. |
| `503 Service Unavailable` | Uma falha operacional impediu o storage de processar a regra. | Uma resposta de erro. O endpoint não executa. |

Registre handlers de exceção no FastAPI para `RateLimitExceeded` e
`StorageUnavailable` se quiser personalizar essas respostas. Ao personalizar o
`429`, use `exc.headers` para preservar `Retry-After`.

```python
from fastapi import Request
from fastapi.responses import JSONResponse

from fastapi_ratelimits import RateLimitExceeded


@app.exception_handler(RateLimitExceeded)
async def quota_exceeded(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "quota_exceeded"},
        headers=exc.headers,
    )
```

## Adicione cabeçalhos de cota

Registre `RateLimitHeadersMiddleware` antes de iniciar a aplicação.

```python
from fastapi_ratelimits import RateLimitHeadersMiddleware

app.add_middleware(RateLimitHeadersMiddleware)
```

O middleware inclui estes cabeçalhos nas respostas com status abaixo de `400`
quando pelo menos uma regra admitiu a requisição. Isso inclui streaming.

| Cabeçalho | Valor |
| --- | --- |
| `X-RateLimit-Limit` | Quantidade total da cota da regra selecionada. |
| `X-RateLimit-Remaining` | Saldo da cota da regra selecionada após admitir a requisição. |
| `X-RateLimit-Reset` | Horário de renovação da cota da regra selecionada, como timestamp Unix em segundos, arredondado para cima. |

Com várias regras, o formatador padrão escolhe aquela com a menor proporção
de saldo restante. Em caso de empate, usa a primeira regra avaliada. Os valores
podem mudar enquanto requisições concorrentes consomem cota. O middleware só
observa a cota.

Passe `headers_func` ao middleware para formatar a tupla de `RateLimitSnapshot`
na ordem de avaliação das regras. A função retorna um mapeamento de nomes de
cabeçalho para valores em string.
