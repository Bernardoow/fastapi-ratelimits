# fastapi-ratelimits

Controle quantas vezes cada cliente pode chamar os endpoints do FastAPI. Adicione
limites como dependências e mantenha os contadores em memória ou no Redis com as
estratégias assíncronas de [limits](https://limits.readthedocs.io/en/stable/async.html).
Requer Python 3.11 ou superior.

[Configure seu primeiro limite](quickstart.md){ .md-button .md-button--primary }

- [Dependências do FastAPI](dependencies.md) mostra como usar `Depends` em
  operações, routers e na aplicação inteira.
- [Regras e identidade](rules.md) explica cotas por rota, cotas compartilhadas e
  custos dinâmicos.
- [Storage e estratégias](storage.md) mostra como usar Redis entre processos e
  escolher uma estratégia.
- [Respostas e cabeçalhos](responses.md) mostra como tratar `429` e `503` e
  disponibilizar informações sobre a cota.
- A [referência da API (em inglês)](https://bernardoow.github.io/fastapi-ratelimits/reference/)
  documenta a interface pública da biblioteca.
