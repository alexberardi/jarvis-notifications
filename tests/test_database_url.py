"""SQLAlchemy 2.1 defaults ``postgresql://`` to psycopg v3, which isn't installed."""

from app.config import pin_psycopg2


def test_bare_url_gets_psycopg2():
    assert pin_psycopg2("postgresql://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"


def test_explicit_driver_is_kept():
    assert pin_psycopg2("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert pin_psycopg2("postgresql+psycopg2://u:p@h/db") == "postgresql+psycopg2://u:p@h/db"


def test_non_postgres_url_is_kept():
    assert pin_psycopg2("sqlite:///:memory:") == "sqlite:///:memory:"
