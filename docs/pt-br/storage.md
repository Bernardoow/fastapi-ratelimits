# Storage e estratégias

Passe exatamente uma opção entre `storage_uri` e `storage` para `Limiter`.
Com URI, o limiter é dono do storage e o gerencia pelo lifespan. Com
`storage=...`, a aplicação é responsável pela instância e pelo seu encerramento.

## Experimente memória, Redis e as três estratégias

Salve este exemplo como `app.py`. Ele inicia com storage em memória e a
estratégia padrão. Para usar Redis, execute `pip install '.[redis]'` a partir
do repositório, no ambiente do [início rápido](quickstart.md), e tenha um
servidor Redis disponível.

```python title="app.py"
import os

from fastapi import Depends, FastAPI

from fastapi_ratelimits import Limiter

uri = os.environ.get("RATE_LIMIT_URI", "async+memory://")
strategy = os.environ.get("RATE_LIMIT_STRATEGY", "fixed-window")
options: dict[str, str | float | bool] = {}

if uri.startswith(("async+redis://", "async+rediss://", "async+redis+unix://")):
    options = {
        "key_prefix": os.environ.get("RATE_LIMIT_PREFIX", "orders-demo"),
        "socket_connect_timeout": 1.0,
        "socket_timeout": 0.5,
    }
    if uri.startswith("async+rediss://"):
        options["ssl_ca_certs"] = os.environ["REDIS_CA_FILE"]
        options["ssl_cert_reqs"] = "required"
        options["ssl_check_hostname"] = True

limiter = Limiter(storage_uri=uri, storage_options=options or None, strategy=strategy)
app = FastAPI(lifespan=limiter.lifespan)


@app.get("/orders", dependencies=[Depends(limiter.limit("2/minute"))])
async def orders() -> list[str]:
    return []
```

### Storage em memória

Execute `python -m uvicorn app:app` sem variáveis de ambiente. Cada processo
tem contadores próprios. Eles são descartados no fim do lifespan. O storage
em memória não recebe `storage_options`.

### Redis

Use um dos comandos abaixo com um servidor que já aceite o transporte
escolhido. Troque o hostname e o caminho da CA do TLS ou o caminho do socket
Unix pelos valores do seu ambiente.

```sh
RATE_LIMIT_URI=async+redis://127.0.0.1:6379/0 python -m uvicorn app:app

RATE_LIMIT_URI=async+rediss://redis.example.com:6380/0 \
    REDIS_CA_FILE=/path/to/ca.pem python -m uvicorn app:app

RATE_LIMIT_URI='async+redis+unix:///run/redis/redis.sock?db=0' python -m uvicorn app:app
```

Nas URIs TCP e TLS, o caminho seleciona o banco `0`. Na URI por socket Unix,
use `?db=0`. Para um servidor com autenticação, obtenha a URI da
configuração de segredos da aplicação, com usuário e senha codificados para
URL. Mantenha a verificação do certificado TLS e do hostname ativada.

O exemplo usa `key_prefix` para separar as chaves Redis da aplicação,
`socket_connect_timeout` para limitar o tempo de conexão e `socket_timeout`
para limitar o tempo das operações no socket. O prefixo padrão é `LIMITS`.
Você também pode usar `storage_options={"wrap_exceptions": True}` para que o
backend encapsule erros ou declarar `"implementation": "redispy"`, que já é o
padrão da API por URI. Para outra implementação de cliente Redis ou um pool
de conexões existente, passe uma instância de storage.

Consulte o [storage Redis assíncrono no limits](https://limits.readthedocs.io/en/stable/api.html#limits.aio.storage.RedisStorage)
para ver as opções do backend e as
[opções de conexão do redis-py](https://redis.readthedocs.io/en/v7.2.1/connections.html)
para parâmetros de conexão, como TLS e pool.

Para compartilhar uma cota entre workers, acrescente `--workers 2` ao
comando do Redis. Use o mesmo banco Redis, prefixo de chaves, estratégia e
configuração de regras em todos os workers.

### Escolha uma estratégia

A estratégia vale para todas as regras criadas pelo limiter. Memória e
Redis suportam as três opções abaixo.

| Valor de `RATE_LIMIT_STRATEGY` | Como a aplicação conta a cota |
| --- | --- |
| `fixed-window` (padrão) | A primeira requisição inicia uma janela de duração fixa. A cota se renova quando essa janela expira. |
| `moving-window` | Registra horários para aplicar a cota ao período completo mais recente. |
| `sliding-window-counter` | Estima o uso recente somando o contador atual a uma fração do contador da janela anterior. |

```sh
RATE_LIMIT_STRATEGY=fixed-window python -m uvicorn app:app
RATE_LIMIT_STRATEGY=moving-window python -m uvicorn app:app
RATE_LIMIT_STRATEGY=sliding-window-counter python -m uvicorn app:app
```

Execute um comando por vez. Com um contador novo, faça estas requisições em
sequência. Espere `200`, `200` e `429`. Para repetir com Redis, aguarde a
janela expirar ou configure um novo `RATE_LIMIT_PREFIX`.

```sh
for i in 1 2 3; do
    curl -i http://127.0.0.1:8000/orders
done
```

Para usar estratégias diferentes na mesma aplicação, crie limiters separados
e [entre no lifespan de cada um](quickstart.md#use-um-lifespan-existente).
O nome da estratégia separa os contadores, mesmo quando usam o mesmo storage
e prefixo. Veja [como as estratégias contam](https://limits.readthedocs.io/en/stable/strategies.html)
para exemplos ao longo do tempo.

## Forneça um storage gerenciado pela aplicação

Use `storage=` com uma instância de `limits.aio.storage.Storage`. Configure
as opções e o prefixo na própria instância. O backend precisa suportar a
estratégia escolhida. Consulte os
[backends assíncronos do limits](https://limits.readthedocs.io/en/stable/async.html)
para outras implementações e seus requisitos.

Este app usa um pool de conexões Redis gerenciado pela aplicação. Salve como
`app.py` e instale o extra de Redis. A aplicação fecha o pool depois de
encerrar o limiter.

```python title="app.py"
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from limits.aio.storage import RedisStorage
from redis.asyncio import ConnectionPool

from fastapi_ratelimits import Limiter

uri = os.environ["REDIS_URL"]
pool = ConnectionPool.from_url(uri)
storage = RedisStorage(
    f"async+{uri}",
    implementation="redispy",
    connection_pool=pool,
    key_prefix="owned-orders-demo",
)
limiter = Limiter(storage=storage)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        async with limiter.lifespan(app):
            yield
    finally:
        await pool.aclose()


app = FastAPI(lifespan=lifespan)


@app.get("/orders", dependencies=[Depends(limiter.limit("2/minute"))])
async def orders() -> list[str]:
    return []
```

Defina `REDIS_URL` com uma URL `redis://` ou `rediss://` acessível e inicie
o app.

```sh
REDIS_URL=redis://127.0.0.1:6379/0 python -m uvicorn app:app
```

Com um contador novo, as três requisições anteriores retornam `200`, `200`
e `429`.
