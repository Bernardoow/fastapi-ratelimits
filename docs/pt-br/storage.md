# Storage e estratégias

Escolha uma origem de storage para o `Limiter`. Com `storage_uri`, o limiter
cria e encerra seu próprio storage. Use `redis_client` para compartilhar o
pool do cliente Redis assíncrono da aplicação ou `storage` para fornecer um
storage assíncrono já configurado. A aplicação gerencia os recursos que fornece.

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
padrão da API por URI. Para outra implementação de cliente Redis, passe uma
instância de storage.

Consulte o [storage Redis assíncrono no limits](https://limits.readthedocs.io/en/stable/api.html#limits.aio.storage.RedisStorage)
para ver as opções do backend e as
[opções de conexão do redis-py](https://redis.readthedocs.io/en/v7.2.1/connections.html)
para parâmetros de conexão, como TLS e pool.

O redis-py pode se reconectar em um comando posterior. Se a aplicação repetir
a sonda no startup, configure timeouts de conexão e de operação e limite o
número de tentativas. Repetir `PING` preserva os contadores de cota. Repetir
um comando de cota pode aplicar a escrita de novo se o Redis o executou e a
resposta se perdeu.

Para compartilhar uma cota entre workers, acrescente `--workers 2` ao
comando do Redis. Limiters separados em apps ou workers compartilham
contadores quando coincidem o banco Redis, o prefixo de chaves, a estratégia,
o escopo da rota (ou grupo), a chave do cliente, a quantidade da cota e a
janela (unidade e multiplicador). Veja como as regras selecionam um contador em
[Regras e identidade](rules.md).

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

## Verifique a prontidão do storage

Defina `check_storage_on_startup=True` no `Limiter` para consultar o storage
configurado durante o lifespan do limiter, antes de a aplicação atender
requisições. A opção funciona com todas as origens de storage e o padrão é
`False`. O startup falha com `StorageStartupError` se a consulta retornar
`False` ou lançar uma exceção operacional reconhecida do storage. Quando há
uma exceção, ela fica disponível como causa.

```python
from fastapi import FastAPI

from fastapi_ratelimits import Limiter

limiter = Limiter(storage_uri="async+redis://localhost:6379/0", check_storage_on_startup=True)
app = FastAPI(lifespan=limiter.lifespan)
```

Importe `StorageStartupError` de `fastapi_ratelimits` para tratar uma falha
dessa checagem de startup.

Para uma sonda de prontidão ou uma política de startup da aplicação, chame
`await limiter.check_storage()` durante o lifespan ativo do limiter. O método
devolve o resultado de `Storage.check()` e propaga exceções do backend. Uma
chamada fora do lifespan ativo lança `RuntimeError`.

No Redis, a consulta usa `PING` e preserva os contadores de cota. Um resultado
positivo confirma que o Redis respondeu naquele instante. A avaliação das
regras de cota também depende dos comandos usados por cada estratégia. O
storage em memória retorna `True`.

## Compartilhe o cliente Redis da aplicação

Se a aplicação já tem uma instância de `redis.asyncio.Redis` chamada `client`,
passe-a diretamente ao limiter. O limiter usa o pool de conexões desse
cliente. A aplicação fecha o cliente e seu pool depois de encerrar o limiter.

```python
from fastapi_ratelimits import Limiter

limiter = Limiter(redis_client=client, storage_options={"key_prefix": "orders"})
```

O prefixo padrão das chaves é `LIMITS`. Use `key_prefix` para isolar as cotas
de aplicações que compartilham o banco. Configure opções de conexão como
`socket_timeout` ao criar o cliente ou o pool. Passar opções de conexão
em `storage_options` junto com `redis_client` gera um erro de configuração.

### Crie o cliente Redis no startup

Se as rotas são declaradas antes da criação do cliente, forneça uma função
síncrona que devolve o cliente da aplicação. O limiter chama a função uma vez
a cada entrada em `limiter.lifespan(app)`. O exemplo define `app.state.redis`
antes de entrar no lifespan do limiter. O contexto externo fecha o cliente
Redis e seu pool depois que o limiter encerra.

```python title="app.py"
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from redis.asyncio import Redis

from fastapi_ratelimits import Limiter

limiter = Limiter(redis_client=lambda app: app.state.redis)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with Redis.from_url(os.environ["REDIS_URL"], socket_timeout=0.5) as client:
        app.state.redis = client
        async with limiter.lifespan(app):
            yield


app = FastAPI(lifespan=lifespan)


@app.get("/orders", dependencies=[Depends(limiter.limit("2/minute"))])
async def orders() -> list[str]:
    return []
```

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
