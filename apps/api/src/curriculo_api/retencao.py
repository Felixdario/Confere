"""`make limpar-vencidos`: a retenção (ADR 0004) à mão, o mesmo código do cron do worker."""

from __future__ import annotations

import asyncio
import sys

from arq import create_pool
from arq.connections import RedisSettings

from curriculo_api.config import obter_settings
from curriculo_api.db.sessao import criar_fabrica, criar_motor
from curriculo_api.logs import configurar_logs
from curriculo_api.servicos.privacidade import limpar_vencidos


async def _principal() -> int:
    configurar_logs()
    settings = obter_settings()
    motor = criar_motor(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        async with criar_fabrica(motor)() as db:
            resultado = await limpar_vencidos(db, redis, settings)
    finally:
        await redis.aclose()
        await motor.dispose()
    print(
        f"Retenção ({settings.retencao_dias} dias): {resultado.versoes} versões com conteúdo "
        f"apagado, {resultado.arquivos} arquivos, {resultado.analises} análises limpas, "
        f"{resultado.sessoes} sessões vencidas."
    )
    return 0


def main() -> int:
    return asyncio.run(_principal())


if __name__ == "__main__":
    sys.exit(main())
