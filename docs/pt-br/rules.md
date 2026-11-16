# Regras e identidade

Uma regra define quanta cota um cliente pode consumir em uma janela. Informe
um limite por chamada de `limiter.limit(...)`. Exemplos válidos incluem
`"2/second"`, `"10 per 2 minutes"`, `"100/hour"`, `"500/day"`,
`"1000/month"` e `"5000/year"`. A quantidade e o multiplicador da janela
devem ser positivos. Consulte a
[sintaxe dos limites](https://limits.readthedocs.io/en/stable/quickstart.html#rate-limit-string-notation).
Para aplicar várias janelas, declare uma dependência para cada uma.

Para cada app abaixo, salve o bloco como `app.py` e execute
`python -m uvicorn app:app` depois de seguir o [início rápido](quickstart.md).
Os exemplos usam `X-Account` como dado de demonstração. Na sua aplicação,
obtenha a conta e seu plano a partir de dados autenticados.

## Escolha a chave do cliente e o escopo da rota

Por padrão, `key_by_ip` usa `request.client.host` e `default_route_id` usa
o `operation_id` explícito ou o identificador gerado pelo FastAPI. Métodos HTTP
ou padrões de rota distintos normalmente têm cotas próprias. Já `/orders/1` e
`/orders/2` correspondem à mesma operação. Atrás de um proxy reverso, configure
o servidor ASGI para aceitar endereços encaminhados só por proxies confiáveis.

Defina `Limiter(key_func=...)` para escolher a identidade padrão do cliente e
`limiter.limit(..., key_func=...)` para substituí-la em uma regra. Defina
`Limiter(route_id_func=...)` para mudar o escopo das rotas. Cada função retorna
uma string não vazia. Aqui, as duas operações de pedidos compartilham o escopo
lógico `orders`. A operação de status usa o identificador padrão e substitui
a identidade do cliente por `key_by_ip`.

```python title="app.py"
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Request

from fastapi_ratelimits import Limiter, default_route_id, key_by_ip


async def account(x_account: Annotated[str, Header(min_length=1)]) -> str:
    return x_account


async def route_scope(request: Request) -> str:
    route_id = await default_route_id(request)
    if route_id in {"list_orders", "create_order"}:
        return "orders"
    return route_id


limiter = Limiter(
    storage_uri="async+memory://",
    key_func=account,
    route_id_func=route_scope,
)
app = FastAPI(lifespan=limiter.lifespan)
per_account = Depends(limiter.limit("1/minute"))


@app.get("/orders", operation_id="list_orders", dependencies=[per_account])
async def list_orders() -> list[str]:
    return []


@app.post("/orders", operation_id="create_order", dependencies=[per_account])
async def create_order() -> dict[str, bool]:
    return {"created": True}


@app.get("/status", dependencies=[Depends(limiter.limit("1/minute", key_func=key_by_ip))])
async def status() -> dict[str, bool]:
    return {"ok": True}
```

```sh
curl -i -H 'X-Account: demo-a' http://127.0.0.1:8000/orders
curl -i -H 'X-Account: demo-a' -X POST http://127.0.0.1:8000/orders
curl -i -H 'X-Account: demo-b' -X POST http://127.0.0.1:8000/orders
```

Espere `200`, `429` e `200`. A conta `demo-a` já consumiu sua cota de
pedidos e `demo-b` tem outro contador. Duas requisições a `/status` a partir do
mesmo IP retornam `200` e `429`, independentemente do cabeçalho `X-Account`.

## Compartilhe uma cota e resolva valores por requisição

`group` é um nome não vazio que substitui o escopo da rota. As regras
compartilham um contador quando grupo, chave do cliente, estratégia, quantidade
e janela coincidem no mesmo namespace do storage. O namespace de grupos é
separado dos identificadores de rota, mesmo com nomes iguais, e uma regra com
grupo dispensa a chamada de `route_id_func`.

Passe uma função como primeiro argumento de `limit` para escolher a cota por
requisição. Passe em `cost` um inteiro positivo ou uma dependência que retorne
esse valor. O padrão é `1`. Este app usa uma cota horária compartilhada, um
custo dinâmico para PDF validado por `Query` e um custo fixo para CSV. Ele
também aplica uma cota própria por rota.

```python title="app.py"
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query

from fastapi_ratelimits import Limiter


async def account(x_account: Annotated[str, Header(min_length=1)]) -> str:
    return x_account


async def export_quota(user: Annotated[str, Depends(account)]) -> str:
    return "50/hour" if user == "demo-pro" else "5/hour"


async def pdf_cost(pages: Annotated[int, Query(ge=1)] = 1) -> int:
    return pages


limiter = Limiter(storage_uri="async+memory://", key_func=account)
app = FastAPI(lifespan=limiter.lifespan)
per_route = Depends(limiter.limit("20/minute"))
pdf_budget = Depends(limiter.limit(export_quota, group="exports", cost=pdf_cost))
csv_budget = Depends(limiter.limit(export_quota, group="exports", cost=2))


@app.get("/exports/pdf", dependencies=[per_route, pdf_budget])
async def export_pdf() -> dict[str, str]:
    return {"format": "pdf"}


@app.get("/exports/csv", dependencies=[per_route, csv_budget])
async def export_csv() -> dict[str, str]:
    return {"format": "csv"}
```

```sh
curl -i -H 'X-Account: demo-basic' 'http://127.0.0.1:8000/exports/pdf?pages=3'
curl -i -H 'X-Account: demo-basic' http://127.0.0.1:8000/exports/csv
curl -i -H 'X-Account: demo-basic' http://127.0.0.1:8000/exports/csv
curl -i -H 'X-Account: demo-pro' 'http://127.0.0.1:8000/exports/pdf?pages=3'
```

Espere `200`, `200`, `429` e `200`. As duas primeiras requisições consomem
as cinco unidades de `demo-basic`. A cota maior de `demo-pro` permite sua
exportação em PDF.

O FastAPI resolve as funções e suas dependências. Aqui, tanto o
`Depends(account)` aninhado quanto `key_func=account` usam a mesma função.
O FastAPI reaproveita seu resultado por padrão dentro da mesma requisição.
Em testes, você pode substituí-la por uma função assíncrona com
`app.dependency_overrides[account]`.

## Use um callback síncrono existente

O FastAPI executa callbacks declarados com `def` em uma thread de trabalho.
Ao configurar um diretamente no limiter, em uma regra ou no middleware de
cabeçalhos, a biblioteca emite `SynchronousCallbackWarning`. Prefira
`async def` para callbacks que fazem I/O assíncrona. Para ver o aviso, troque
`async def account` por `def account` em qualquer app acima e reinicie o
Uvicorn. Os exemplos HTTP continuam funcionando.

## Ordene as regras de uma operação

Liste as dependências da rota na ordem em que devem ser verificadas. A primeira
recusa encerra a sequência. As regras anteriores mantêm a cota já consumida.
Na estratégia de janela fixa, tentativas recusadas também podem incrementar o
contador. Uma requisição permitida consome a cota antes de executar a função da
rota, seja ela síncrona ou assíncrona. A cota continua consumida se essa função
falhar depois.
