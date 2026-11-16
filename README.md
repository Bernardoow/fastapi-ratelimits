# fastapi-ratelimits

Rate limiting assíncrono para APIs HTTP com FastAPI. As regras são dependências do
FastAPI e usam as estratégias assíncronas de [limits](https://limits.readthedocs.io/en/stable/async.html).
Requer Python 3.11 ou superior.

## Primeiro limite

Instale o pacote com `pip install .` a partir deste repositório. Para Redis, use
`pip install '.[redis]'`.

```python
from fastapi import Depends, FastAPI

from fastapi_ratelimits import Limiter

limiter = Limiter(storage_uri="async+memory://")
app = FastAPI(lifespan=limiter.lifespan)


@app.get("/orders", dependencies=[Depends(limiter.limit("10/minute"))])
async def orders():
    return {"orders": []}
```

Com esse exemplo, cada IP tem dez chamadas por minuto para essa operação. O IP
vem de `request.client`; configure os proxies confiáveis no servidor se a API
estiver atrás de um proxy. O identificador da rota usa o `operation_id` explícito
ou o `unique_id` gerado pelo FastAPI. Use identificadores distintos para operações
com cotas independentes. `key_by_ip` e `default_route_id` são funções públicas.

Use `async with limiter.lifespan(app):` dentro do lifespan existente da aplicação,
se houver. O limiter verifica a cota antes do endpoint, mesmo quando o endpoint é
`def`. Uma requisição admitida consome cota mesmo se o endpoint falhar depois.

Limite excedido responde `429` com `Retry-After` em segundos, uma estimativa
baseada na janela da regra que recusou. Falhas operacionais do storage respondem
`503` e impedem a execução do endpoint. Para personalizar as respostas, registre
handlers do FastAPI para `RateLimitExceeded` e `StorageUnavailable`. Ao formatar
um `429` próprio, use `exc.headers` para preservar `Retry-After`. Os handlers
`rate_limit_exceeded_handler` e `storage_unavailable_handler` também são públicos.

## Identidade, grupos e custos

Passe `key_func` ao `Limiter` ou a uma regra específica. Passe `route_id_func`
ao `Limiter` para substituir a identificação das rotas. A biblioteca deixa o
FastAPI resolver essas funções, inclusive subdependências, cache e
`dependency_overrides`. Prefira `async def` com I/O assíncrono. Funções `def`
são aceitas, emitem `SynchronousCallbackWarning` na configuração e rodam em
uma thread de trabalho.

```python
from typing import Annotated

from fastapi import Depends, FastAPI, Header

from fastapi_ratelimits import Limiter


async def account(x_account: Annotated[str, Header()]) -> str:
    return x_account  # Em produção, derive a identidade da autenticação da aplicação.


async def export_quota(user: Annotated[str, Depends(account)]) -> str:
    return "1000/hour" if user == "demo-pro" else "100/hour"


async def export_cost(items: int = 1) -> int:
    return items


limiter = Limiter(storage_uri="async+memory://", key_func=account)
app = FastAPI(lifespan=limiter.lifespan)
shared = Depends(limiter.limit(export_quota, group="exports", cost=export_cost))


@app.get("/export/pdf", dependencies=[shared, Depends(limiter.limit("20/minute"))])
async def export_pdf():
    return {"format": "pdf"}


@app.get("/export/csv", dependencies=[shared, Depends(limiter.limit("40/minute"))])
async def export_csv():
    return {"format": "csv"}
```

Use uma dependência por regra e liste-as na ordem desejada. O grupo substitui o
escopo da rota e preserva a identidade. Para compartilhar uma cota, as regras
usam o mesmo grupo, identidade, estratégia, quantidade e janela no mesmo storage. O custo é
um inteiro positivo fixo ou resolvido por dependência; seu padrão é 1.

A primeira recusa interrompe a sequência. Se uma regra anterior já consumiu,
esse consumo permanece. A janela fixa de `limits` pode incrementar o contador
mesmo na tentativa recusada. A lista explícita não define herança de políticas
entre aplicação, routers e rotas.

## Storage e estratégias

Escolha exatamente uma origem: `storage_uri` ou `storage`. Memória precisa ser
escolhida explicitamente e mantém contadores locais a cada instância da aplicação.
Para coordenar processos, use um Redis comum com o mesmo prefixo e as mesmas regras:

```python
limiter = Limiter(
    storage_uri="async+redis://localhost:6379/0",
    storage_options={"key_prefix": "orders-api", "socket_timeout": 0.5},
    strategy="moving-window",
)
```

As chaves Redis criadas nesse exemplo começam com `orders-api:`. As URIs de
memória e Redis (TCP, TLS e socket Unix) criam recursos sob responsabilidade do
limiter. Para reutilizar um backend já configurado, passe uma instância de
`limits.aio.storage.Storage` como `Limiter(storage=my_storage)` e gerencie seu
ciclo de vida e prefixo no próprio objeto. `storage_options` pertence à forma por
URI. Um cliente Redis não é uma instância de storage de `limits`.

As estratégias são `fixed-window` (padrão), `moving-window` e
`sliding-window-counter`, selecionadas por limiter. Memória e Redis suportam as
três. Quando fornece um storage próprio, a estratégia escolhida precisa ser
compatível com ele. Use instâncias distintas para estratégias distintas; elas
mantêm contadores separados mesmo quando apontam para o mesmo backend e prefixo.

## Headers opcionais

Adicione o middleware antes de iniciar a aplicação:

```python
from fastapi_ratelimits import RateLimitHeadersMiddleware

app.add_middleware(RateLimitHeadersMiddleware)
```

Ele acrescenta `X-RateLimit-Limit`, `X-RateLimit-Remaining` e
`X-RateLimit-Reset` (timestamp Unix em segundos) às respostas com status abaixo
de 400 que passaram por uma regra, inclusive respostas em streaming. Com várias
regras, o padrão informa aquela com menor proporção de saldo, usando a ordem de
avaliação em caso de empate. Passe `headers_func` para formatar a tupla de
`RateLimitSnapshot` na ordem da avaliação. O middleware não consome cota, e os
valores observados podem mudar com requisições concorrentes.

## Testes

```sh
uv sync --python 3.11 --extra redis
uv run --python 3.11 pytest -m 'not redis'
uv run --python 3.11 mypy
uv run --python 3.11 ruff check .
```

Para testar Redis, aponte `RATELIMITS_TEST_REDIS_URL` para um servidor descartável
local e rode a suíte completa. Use a URI do cliente Redis, sem o prefixo `async+`:

```sh
RATELIMITS_TEST_REDIS_URL=redis://127.0.0.1:6379/0 uv run --python 3.11 --extra redis pytest
```
