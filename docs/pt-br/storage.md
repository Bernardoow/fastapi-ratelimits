# Storage e estratégias

Configure exatamente um dos parâmetros `storage_uri` ou `storage` ao criar
um `Limiter`.

## Storage em memória

Use `Limiter(storage_uri="async+memory://")` para desenvolvimento local ou
quando cada instância da aplicação deve ter contadores independentes. Os
contadores são locais à instância e zeram ao encerrar seu lifespan. A URI de
memória não aceita `storage_options`.

## Redis

Para compartilhar cotas entre processos, aponte cada processo para o mesmo banco
Redis e use o mesmo prefixo, estratégia e regras. A partir do checkout do
repositório, instale o extra `redis`.

```sh
pip install '.[redis]'
```

```python
from fastapi_ratelimits import Limiter

limiter = Limiter(
    storage_uri="async+redis://localhost:6379/0",
    storage_options={"key_prefix": "orders-api", "socket_timeout": 0.5},
    strategy="moving-window",
)
```

Neste exemplo, as chaves Redis começam com `orders-api:`. A configuração por URI
aceita TCP (`async+redis`), TLS (`async+rediss`) e sockets Unix
(`async+redis+unix`). O `Limiter.lifespan` gerencia os recursos criados a
partir de uma URI.

## Forneça seu próprio storage

Passe uma instância de `limits.aio.storage.Storage` como
`Limiter(storage=my_storage)`. Ao usar essa forma, configure as opções e o
prefixo diretamente na instância de storage e gerencie seu ciclo de vida na
aplicação.

## Escolha uma estratégia

A estratégia se aplica a todas as regras criadas por um `Limiter`. Memória e
Redis suportam as três. Um backend fornecido pela aplicação precisa suportar a
estratégia escolhida.

| Estratégia | Como conta as requisições |
| --- | --- |
| `fixed-window` (padrão) | Conta requisições em um período fixo. O cliente pode usar a cota no fim de um período e novamente no início do próximo. |
| `moving-window` | Guarda os horários das requisições para contar as que ocorreram durante a última janela completa. |
| `sliding-window-counter` | Estima o uso com uma contagem ponderada das janelas atual e anterior. |

Use instâncias de `Limiter` separadas para estratégias diferentes. Os
contadores ficam separados mesmo quando o backend e o prefixo são os mesmos.
Se uma aplicação usa vários limiters, chame o lifespan de cada um no lifespan
da aplicação.
