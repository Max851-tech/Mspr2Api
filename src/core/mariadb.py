"""
Connexion async à la MariaDB existante (TPRE501) via aiomysql.
Pool de connexions partagé sur toute la durée de vie de l'app.
"""
import aiomysql
import logging
from src.config.settings import settings

logger = logging.getLogger(__name__)
_pool: aiomysql.Pool | None = None


async def init_pool():
    """Initialise le pool de connexions MariaDB. Appelé au démarrage de l'app."""
    global _pool
    try:
        _pool = await aiomysql.create_pool(
            host=settings.MARIADB_HOST,
            port=settings.MARIADB_PORT,
            user=settings.MARIADB_USER,
            password=settings.MARIADB_PASSWORD,
            db=settings.MARIADB_DB,
            charset="utf8mb4",
            autocommit=True,
            minsize=2,
            maxsize=10,
        )
        logger.info("Pool MariaDB initialisé avec succès.")
    except Exception as e:
        logger.warning(f"MariaDB non disponible (mode standalone activé): {e}")
        _pool = None


async def close_pool():
    """Ferme le pool proprement à l'arrêt de l'app."""
    global _pool
    if _pool:
        _pool.close()
        await _pool.wait_closed()
        _pool = None


def get_pool() -> aiomysql.Pool | None:
    return _pool


def is_available() -> bool:
    return _pool is not None
