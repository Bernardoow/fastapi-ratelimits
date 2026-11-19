# Compatibilidade

O fastapi-ratelimits requer Python 3.11 ou superior, FastAPI 0.95.1 ou superior
e `limits>=5.8,<6`. O requisito do FastAPI permite manter uma versão antiga
que funcione com o Python e as dependências da sua aplicação. Quando a versão
estável atual do FastAPI aumenta o mínimo de Python, a próxima release do
fastapi-ratelimits adota esse novo mínimo.

## Aplicações FastAPI existentes

Use uma versão do Pydantic compatível com o seu FastAPI. No Python 3.11,
o FastAPI 0.100.0 passou na suíte com o Pydantic 2.0.3. Com o Pydantic 2.14.3,
essa versão do FastAPI pode falhar ao registrar rotas que usam
`Annotated[str, Header()]`. O FastAPI espera o atributo `in_` do cabeçalho,
que o `FieldInfo` genérico retornado pelo Pydantic não tem.

O FastAPI corrigiu uma vulnerabilidade de negação de serviço no processamento
de parâmetros de requisição na versão 0.163.2. Confira se a versão que você usa
é afetada no [aviso de segurança do FastAPI](https://github.com/fastapi/fastapi/security/advisories/GHSA-f56c-v883-vx8r).

## Como testamos a compatibilidade

O GitHub Actions roda a suíte com Redis no Python 3.11 a 3.15. Em cada versão de
Python, usa o lockfile de desenvolvimento, as versões mínimas declaradas das
dependências de execução e as versões mais recentes compatíveis. A matriz roda
em pull requests, em pushes para `main` e antes da publicação no PyPI.
