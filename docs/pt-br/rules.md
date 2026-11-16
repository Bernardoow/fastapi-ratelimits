# Regras e identidade

## Identidade do cliente e escopo da rota

Por padrão, `key_by_ip` usa `request.client.host`. Se a aplicação estiver atrás
de um proxy reverso, configure o servidor ASGI para aceitar endereços de clientes
encaminhados apenas por proxies confiáveis.

O identificador padrão da rota é o `operation_id` explícito ou o `unique_id`
que o FastAPI gera para a operação. Use identificadores distintos para operações
com cotas independentes. Para mudar a identificação da rota, passe `route_id_func`
ao `Limiter`. Para mudar a identidade do cliente, passe `key_func` ao `Limiter`
ou a uma regra específica com `limiter.limit(..., key_func=...)`. Ambas as
funções devem retornar uma string não vazia.

## Cotas compartilhadas e custos dinâmicos

Use `group` para compartilhar uma cota entre rotas. O grupo substitui o escopo
da rota e preserva a identidade do cliente. As regras compartilham um contador
quando usam o mesmo grupo, identidade, estratégia, quantidade e janela no mesmo
storage.

O exemplo dá a cada conta uma cota horária compartilhada para exportações e um
limite separado por rota. O parâmetro de consulta `items` determina quanto da
cota horária cada exportação consome. O custo de uma regra tem valor padrão `1`
e pode ser um inteiro positivo fixo ou o resultado de uma dependência.

```python
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query

from fastapi_ratelimits import Limiter


async def account(x_account: Annotated[str, Header()]) -> str:
    return x_account


async def export_quota(user: Annotated[str, Depends(account)]) -> str:
    return "1000/hour" if user == "demo-pro" else "100/hour"


async def export_cost(items: Annotated[int, Query(ge=1)] = 1) -> int:
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

O exemplo usa `X-Account` para demonstrar a identificação. Em produção, obtenha
a conta e o nível da cota a partir dos dados autenticados da aplicação.

O FastAPI resolve `key_func`, `route_id_func`, limites dinâmicos e custos
dinâmicos como dependências, inclusive subdependências, cache e
`dependency_overrides`. Prefira `async def` com I/O assíncrono. Uma função `def`
roda em uma thread de trabalho e emite `SynchronousCallbackWarning` na
configuração.

## Ordem das regras e consumo de cota

Adicione uma dependência por regra e liste-as na ordem de avaliação. A primeira
recusa interrompe a sequência, e a cota que uma regra anterior consumiu permanece
consumida. A estratégia de janela fixa também pode incrementar o contador em
uma tentativa recusada.

Uma requisição admitida consome cota antes da execução do endpoint, inclusive
para endpoints síncronos. O consumo permanece se o endpoint falhar. Declare as
dependências do FastAPI nos níveis de aplicação, router ou rota para escolher
onde cada regra se aplica.
