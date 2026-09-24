"""Isolated local PostgreSQL test configuration."""
import os

from .test_settings import *  # noqa: F403


POSTGRES_TEST_HOST = os.environ.get("TREASURELAND_TEST_DB_HOST", "127.0.0.1").strip()
POSTGRES_TEST_PORT = os.environ.get("TREASURELAND_TEST_DB_PORT", "5433").strip()
POSTGRES_TEST_NAME = os.environ.get("TREASURELAND_TEST_DB_NAME", "treasureland_test").strip()
POSTGRES_TEST_USER = os.environ.get("TREASURELAND_TEST_DB_USER", "treasureland_test").strip()

if POSTGRES_TEST_HOST not in {"127.0.0.1", "localhost"}:
    raise RuntimeError("PostgreSQL test settings require a local loopback host.")
if not (POSTGRES_TEST_NAME == "treasureland_test" or POSTGRES_TEST_NAME.startswith("test_") or POSTGRES_TEST_NAME.endswith("_test")):
    raise RuntimeError("PostgreSQL test settings require a test database name.")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": POSTGRES_TEST_NAME,
        "USER": POSTGRES_TEST_USER,
        "HOST": POSTGRES_TEST_HOST,
        "PORT": POSTGRES_TEST_PORT,
        "TEST": {"NAME": "test_treasureland_payment"},
        "OPTIONS": {"connect_timeout": 10},
    }
}