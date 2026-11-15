# curriculo-api

API em FastAPI do analisador de currículos. Gerenciada por [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run uvicorn curriculo_api.main:app --reload --port 8010   # OpenAPI em http://localhost:8010/docs
uv run pytest
```
