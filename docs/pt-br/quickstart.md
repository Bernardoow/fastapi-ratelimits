# Início rápido

Permita duas requisições por minuto a `GET /orders` para cada IP de cliente.
Este exemplo usa storage em memória e roda em um único processo.

## Instale a partir do repositório

Use um ambiente virtual ativo com Python 3.11 ou superior. Se você já tem uma
aplicação FastAPI, confira os [requisitos das dependências](compatibility.md).

```sh
git clone https://github.com/Bernardoow/fastapi-ratelimits.git
cd fastapi-ratelimits
pip install . uvicorn
```

## Adicione uma regra

Salve o exemplo em `app.py`.

```python
from fastapi import Depends, FastAPI

from fastapi_ratelimits import Limiter

limiter = Limiter(storage_uri="async+memory://")
app = FastAPI(lifespan=limiter.lifespan)


@app.get("/orders", dependencies=[Depends(limiter.limit("2/minute"))])
async def orders() -> dict[str, list[str]]:
    return {"orders": []}
```

Inicie o servidor com Uvicorn.

```sh
python -m uvicorn app:app
```

Em outro terminal, envie três requisições em sequência.

```sh
for i in 1 2 3; do
    curl -i http://127.0.0.1:8000/orders
done
```

As duas primeiras retornam `200 OK`. A terceira retorna `429 Too Many Requests`
com `Retry-After` em segundos. Reinicie o servidor para zerar os contadores em
memória.

## Use um lifespan existente

Entre em `limiter.lifespan(app)` dentro da função de lifespan da aplicação
antes de ela servir requisições. Se houver mais de um limiter, entre no
contexto de cada um. O app abaixo usa uma janela fixa em todas as operações e
uma janela móvel mais restritiva em `/orders`. O `AsyncExitStack` encerra os
dois contextos no desligamento.

Salve esta versão como `app.py` e execute `python -m uvicorn app:app`.

```python title="app.py"
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Depends, FastAPI

from fastapi_ratelimits import Limiter

baseline = Limiter(storage_uri="async+memory://")
orders_quota = Limiter(storage_uri="async+memory://", strategy="moving-window")

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(baseline.lifespan(app))
        await stack.enter_async_context(orders_quota.lifespan(app))
        yield


app = FastAPI(
    lifespan=lifespan,
    dependencies=[Depends(baseline.limit("10/minute"))],
)


@app.get("/orders", dependencies=[Depends(orders_quota.limit("1/minute"))])
async def orders() -> list[str]:
    return []


@app.get("/status")
async def status() -> dict[str, bool]:
    return {"ok": True}
```

Duas requisições a `/orders` retornam `200` e `429`. Uma requisição a
`/status` ainda retorna `200` sob a regra da aplicação.

Veja as [dependências do FastAPI](dependencies.md) para aplicar regras de outras
formas e [Redis](storage.md#redis) para compartilhar contadores entre workers.
