# Respostas e cabeçalhos

## Conheça as respostas padrão

| Status | Causa | Resposta padrão |
| --- | --- | --- |
| `429 Too Many Requests` | Uma regra recusou a requisição. | `{"detail":"Rate limit exceeded"}` e `Retry-After`, uma estimativa em segundos inteiros baseada na janela da regra que recusou a requisição. |
| `503 Service Unavailable` | Uma falha operacional no storage impediu a verificação da regra. | `{"detail":"Rate limit storage unavailable"}`. A função da rota não roda. |

Por padrão, o FastAPI trata `RateLimitExceeded` e `StorageUnavailable` como
exceções HTTP. Você pode registrar `rate_limit_exceeded_handler` e
`storage_unavailable_handler` explicitamente para manter esse comportamento
ou registrar handlers próprios para mudar o corpo da resposta. Preserve
`exc.headers` ao personalizar o `429` para que o cliente continue recebendo
`Retry-After`.

## Adicione cabeçalhos de cota

Ative `RateLimitHeadersMiddleware` para respostas com status abaixo de
`400` quando pelo menos uma regra permitiu a requisição. Isso também funciona
com respostas em streaming. O formatador padrão escolhe a regra com a menor
fração de cota restante. Em caso de empate, vence a primeira avaliada.

| Cabeçalho padrão | Valor |
| --- | --- |
| `X-RateLimit-Limit` | A quantidade de cota da regra escolhida. |
| `X-RateLimit-Remaining` | A cota restante da regra após permitir a requisição. |
| `X-RateLimit-Reset` | O horário de renovação da regra como timestamp Unix em segundos, arredondado para cima. |

Passe `headers_func` para personalizar os cabeçalhos. A função recebe uma
tupla de objetos `RateLimitSnapshot` na ordem de avaliação e retorna um
mapeamento com nomes e valores dos cabeçalhos em strings. Cada snapshot
registra `limit`, `remaining`, `reset_at`, `cost`, `scope` e se a cota é
compartilhada via `group` (`shared`). Esses valores refletem o momento em que
a regra rodou. Requisições concorrentes podem alterar a cota restante antes
de o cliente ler o cabeçalho.

## Execute as configurações padrão e personalizada

Com a [instalação do início rápido](quickstart.md), salve o exemplo como
`app.py`. O app pode usar um storage que falha de propósito para reproduzir
o `503` sem um servidor Redis.

```python title="app.py"
import os

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from limits.aio.storage import MemoryStorage

from fastapi_ratelimits import (
    Limiter,
    RateLimitExceeded,
    RateLimitHeadersMiddleware,
    RateLimitSnapshot,
    StorageUnavailable,
    default_rate_limit_headers,
    rate_limit_exceeded_handler,
    storage_unavailable_handler,
)


class UnavailableStorage(MemoryStorage):
    async def incr(self, key: str, expiry: float, amount: int = 1) -> int:
        raise ConnectionError("Simulated storage outage")


async def quota_exceeded(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "quota_exceeded"},
        headers=exc.headers,
    )


async def unavailable(_request: Request, exc: StorageUnavailable) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "quota_temporarily_unavailable"},
    )


async def quota_headers(snapshots: tuple[RateLimitSnapshot, ...]) -> dict[str, str]:
    headers = dict(await default_rate_limit_headers(snapshots))
    snapshot = snapshots[0]
    headers["X-Quota-Cost"] = str(snapshot.cost)
    if snapshot.shared:
        headers["X-Quota-Scope"] = snapshot.scope
    return headers


if os.environ.get("SIMULATE_OUTAGE") == "1":
    limiter = Limiter(storage=UnavailableStorage())
else:
    limiter = Limiter(storage_uri="async+memory://")

app = FastAPI(lifespan=limiter.lifespan)
mode = os.environ.get("RESPONSE_MODE")
if mode == "custom":
    app.add_exception_handler(RateLimitExceeded, quota_exceeded)
    app.add_exception_handler(StorageUnavailable, unavailable)
    app.add_middleware(RateLimitHeadersMiddleware, headers_func=quota_headers)
else:
    if mode == "builtin":
        app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
        app.add_exception_handler(StorageUnavailable, storage_unavailable_handler)
    app.add_middleware(RateLimitHeadersMiddleware)


@app.get("/orders", dependencies=[Depends(limiter.limit("2/minute", group="orders", cost=2))])
async def orders() -> list[str]:
    return []
```

Execute um comando por vez.

```sh
python -m uvicorn app:app
RESPONSE_MODE=custom python -m uvicorn app:app
RESPONSE_MODE=custom SIMULATE_OUTAGE=1 python -m uvicorn app:app
```

Para cada execução do servidor, faça duas requisições a partir do mesmo cliente.

```sh
curl -i http://127.0.0.1:8000/orders
curl -i http://127.0.0.1:8000/orders
```

| Modo | Primeira resposta | Segunda resposta |
| --- | --- | --- |
| Padrão | `200` com `X-RateLimit-Limit: 2` e `X-RateLimit-Remaining: 0`. | `429` com o corpo padrão e `Retry-After`. |
| Personalizado | Os mesmos cabeçalhos do `200`, mais `X-Quota-Cost: 2` e `X-Quota-Scope: orders`. | `429` com `{"error":"quota_exceeded"}` e `Retry-After`. |
| Falha simulada no storage | `503` com `{"error":"quota_temporarily_unavailable"}`. | O mesmo corpo do `503`. |

Para ver o corpo padrão do `503`, repita o último modo usando apenas
`SIMULATE_OUTAGE=1`. Para usar os handlers explícitos da biblioteca, defina
`RESPONSE_MODE=builtin`.
