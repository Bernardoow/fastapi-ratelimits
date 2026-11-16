# Início rápido

Permita duas requisições por minuto a `GET /orders` para cada IP de cliente.
Este exemplo usa storage em memória e roda em um único processo.

## Instale a partir do repositório

Execute os comandos abaixo em um ambiente virtual ativo com Python 3.11 ou superior.

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
async def orders():
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

Se a aplicação já tem uma função de lifespan, use `limiter.lifespan(app)` dentro
dela. Coloque a inicialização e a limpeza existentes antes e depois do `yield`,
respectivamente.

```python
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with limiter.lifespan(app):
        yield


app = FastAPI(lifespan=lifespan)
```

Use `FastAPI(lifespan=lifespan)` no lugar da linha `FastAPI(...)` original, antes
de registrar as rotas. Ao rodar vários processos, use um
[backend Redis compartilhado](storage.md#redis).
