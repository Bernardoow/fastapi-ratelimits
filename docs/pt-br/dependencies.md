# Dependências do FastAPI

`limiter.limit(...)` cria uma dependência que verifica a cota antes de o FastAPI
chamar a função da rota. Use `Depends` onde você quer aplicar a regra.

| Onde declarar | Quais operações executam a regra |
| --- | --- |
| `@app.get(..., dependencies=[Depends(rule)])` | Aquela operação. O mesmo padrão funciona no decorador de rota de um router. |
| `Annotated[None, Depends(rule)]` | A operação com esse parâmetro. Quando a regra permite a requisição, a dependência retorna `None`. |
| `APIRouter(dependencies=[Depends(rule)])` | As operações do router, onde quer que ele seja incluído. |
| `app.include_router(router, dependencies=[Depends(rule)])` | As operações registradas por aquela inclusão. |
| `FastAPI(dependencies=[Depends(rule)])` | Todas as operações HTTP do FastAPI na aplicação, incluindo as dos routers. |

## Reutilize um limiter entre routers

Defina um `Limiter` em um módulo compartilhado. Cada router importa a instância
e passa a regra completa, com quantidade e janela, a `limiter.limit(...)` dentro
de `Depends`. Registre os routers e o lifespan do limiter na mesma aplicação.

Crie um pacote `app` com um `__init__.py` vazio e estes quatro módulos.

```python title="app/rate_limits.py"
from fastapi_ratelimits import Limiter

limiter = Limiter(storage_uri="async+memory://")
```

```python title="app/orders.py"
from fastapi import APIRouter, Depends

from .rate_limits import limiter

router = APIRouter(prefix="/orders", dependencies=[Depends(limiter.limit("10/minute"))])


@router.get("")
async def list_orders() -> list[int]:
    return [1, 2]


@router.get("/{order_id}")
async def get_order(order_id: int) -> dict[str, int]:
    return {"id": order_id}
```

```python title="app/reports.py"
from fastapi import APIRouter, Depends

from .rate_limits import limiter

router = APIRouter(prefix="/reports")


@router.get("/summary")
async def report_summary() -> dict[str, int]:
    return {"report_count": 1}


@router.get("/export", dependencies=[Depends(limiter.limit("1/second"))])
async def export_report() -> dict[str, str]:
    return {"format": "csv"}
```

```python title="app/main.py"
from fastapi import FastAPI

from .orders import router as orders_router
from .rate_limits import limiter
from .reports import router as reports_router

app = FastAPI(lifespan=limiter.lifespan)
app.include_router(orders_router)
app.include_router(reports_router)
```

Depois de seguir a [instalação do início rápido](quickstart.md), execute
`python -m uvicorn app.main:app` no diretório que contém `app/`.

Cada operação de pedidos permite dez requisições por minuto por IP. Depois
que `GET /orders` retorna `429`, o mesmo cliente ainda pode chamar
`GET /orders/1` com a cota própria dessa operação. Em um servidor recém-iniciado,
duas requisições a `GET /reports/export` com menos de um segundo de intervalo
retornam `200` e `429`. `GET /reports/summary` continua retornando `200`.

Para aplicar uma regra a todas as operações HTTP do app, importe `Depends` em
`app/main.py` e adicione `dependencies=[Depends(limiter.limit("100/minute"))]`
à chamada de `FastAPI(...)`. As regras de routers e operações também se aplicam. Use
[`group`](rules.md#compartilhe-uma-cota-e-resolva-valores-por-requisicao)
quando várias operações precisarem consumir a mesma cota.

## Aplique regras em cada nível

Com a [instalação do início rápido](quickstart.md), salve o exemplo como `app.py`
e execute `python -m uvicorn app:app`.

```python title="app.py"
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI

from fastapi_ratelimits import Limiter

limiter = Limiter(storage_uri="async+memory://")
app = FastAPI(
    lifespan=limiter.lifespan,
    dependencies=[Depends(limiter.limit("10/minute"))],
)


@app.get("/ping")
async def ping() -> dict[str, bool]:
    return {"ok": True}


@app.get("/orders", dependencies=[Depends(limiter.limit("1/minute"))])
async def orders() -> list[str]:
    return []


@app.get("/reports")
async def reports(_quota: Annotated[None, Depends(limiter.limit("1/minute"))]) -> list[str]:
    return []


exports = APIRouter(
    prefix="/exports",
    dependencies=[Depends(limiter.limit("2/minute", group="exports"))],
)


@exports.get("/csv")
async def csv() -> dict[str, str]:
    return {"format": "csv"}


@exports.get("/pdf")
async def pdf() -> dict[str, str]:
    return {"format": "pdf"}


app.include_router(exports)

catalog = APIRouter()


@catalog.get("/a")
@catalog.get("/b")
async def catalog_entry() -> dict[str, bool]:
    return {"ok": True}


app.include_router(
    catalog, prefix="/internal", dependencies=[Depends(limiter.limit("1/minute"))]
)
app.include_router(catalog, prefix="/public")
```

Com o servidor recém-iniciado, faça as requisições de cada sequência na ordem
indicada e a partir do mesmo cliente.

| Requisições | Status esperados | O que observar |
| --- | --- | --- |
| `GET /ping` duas vezes | `200`, `200` | A operação usa a regra da aplicação. |
| `GET /orders` duas vezes | `200`, `429` | O decorador adiciona uma regra mais restritiva à operação. |
| `GET /reports` duas vezes | `200`, `429` | O parâmetro verifica a regra antes de a função da rota rodar. |
| `GET /exports/csv`, `GET /exports/pdf`, `GET /exports/csv` | `200`, `200`, `429` | A regra do router usa `group` para compartilhar uma cota entre as exportações. |
| `GET /internal/a`, `GET /internal/b`, `GET /internal/a`, `GET /public/a` | `200`, `200`, `429`, `200` | Só a inclusão interna adiciona a regra de uma requisição. Suas operações têm contadores separados. |

Para ver a cota compartilhada das exportações:

```sh
curl -i http://127.0.0.1:8000/exports/csv
curl -i http://127.0.0.1:8000/exports/pdf
curl -i http://127.0.0.1:8000/exports/csv
```

A dependência da aplicação ou do router determina **onde a regra roda**. Por
padrão, cada operação tem seu próprio contador. Use
[`group`](rules.md#compartilhe-uma-cota-e-resolva-valores-por-requisicao) quando
as operações precisarem consumir a mesma cota. Se alguma regra recusar a
requisição, a resposta será `429` com `Retry-After`.

Por padrão, o FastAPI reaproveita o resultado de uma dependência dentro da
requisição. Ao usar a mesma função retornada por `limiter.limit(...)` em dois
níveis, a checagem pode rodar uma única vez. Para aplicar duas janelas na mesma
operação, crie duas regras, por exemplo `limiter.limit("2/second")` e
`limiter.limit("10/minute")`.

## Use dependências dentro de uma regra

O FastAPI resolve a chave do cliente, o identificador da rota, a cota dinâmica
e o custo dinâmico como dependências. Elas podem ler parâmetros da requisição,
receber valores de outras dependências e usar o cache e os overrides do
FastAPI. Veja o
[exemplo de contas e exportações](rules.md#compartilhe-uma-cota-e-resolva-valores-por-requisicao).
