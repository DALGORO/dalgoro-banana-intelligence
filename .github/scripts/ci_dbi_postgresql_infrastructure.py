"""Valida la infraestructura declarativa DBI sin conexiones externas."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra" / "dbi" / "postgresql"
MATRIX_PATH = INFRA / "environments.json"
SQL_PATH = INFRA / "bootstrap.sql.tmpl"
README_PATH = INFRA / "README.md"

EXPECTED = {
    "local": ("development", "dbi_development"),
    "ci": ("test", "dbi_test"),
    "staging": ("staging", "dbi_staging"),
    "production": ("production", "dbi_production"),
}
ROLE_KINDS = {"owner", "migrator", "api", "worker", "observer"}
TOKENS = {
    "{{DBI_DATABASE_NAME}}",
    "{{DBI_OWNER_ROLE}}",
    "{{DBI_MIGRATOR_ROLE}}",
    "{{DBI_API_ROLE}}",
    "{{DBI_WORKER_ROLE}}",
    "{{DBI_OBSERVER_ROLE}}",
}


def validate_matrix() -> None:
    data = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert set(data["environments"]) == set(EXPECTED)
    assert data["required_environment_variables"] == [
        "DBI_ENVIRONMENT",
        "DBI_DATABASE_URL",
    ]
    assert data["forbidden_environment_variables"] == ["DATABASE_URL"]

    all_roles: set[str] = set()
    for name, (dbi_environment, database_name) in EXPECTED.items():
        item = data["environments"][name]
        assert item["dbi_environment"] == dbi_environment
        assert item["database_name"] == database_name
        assert item["remote_execution_allowed"] is False
        assert set(item["roles"]) == ROLE_KINDS
        for kind, role in item["roles"].items():
            assert role == f"{database_name}_{kind}"
            assert re.fullmatch(r"[a-z][a-z0-9_]{2,62}", role)
            assert role not in all_roles
            all_roles.add(role)


def validate_sql_template() -> None:
    sql = SQL_PATH.read_text(encoding="utf-8")
    upper = sql.upper()
    for token in TOKENS:
        assert token in sql

    assert "CREATE EXTENSION IF NOT EXISTS postgis" in sql
    assert "CREATE SCHEMA IF NOT EXISTS dbi" in sql
    assert "WHERE NOT EXISTS" in sql
    assert "IF NOT EXISTS" in sql
    assert "REVOKE ALL ON DATABASE" in sql
    assert "REVOKE ALL ON SCHEMA dbi FROM PUBLIC" in sql
    assert "NOSUPERUSER" in sql
    assert "NOCREATEDB" in sql
    assert "NOCREATEROLE" in sql
    assert "NOLOGIN" in sql
    assert "GRANT SELECT ON ALL TABLES" in sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" in sql
    assert "GRANT SELECT, INSERT, UPDATE ON ALL TABLES" in sql
    assert "GRANT USAGE, CREATE ON SCHEMA dbi" in sql
    assert "GRANT USAGE ON SCHEMA dbi" in sql
    assert "ALTER DEFAULT PRIVILEGES" in sql
    assert 'GRANT "{{DBI_OWNER_ROLE}}" TO' not in sql

    forbidden = (
        "DROP DATABASE",
        "DROP ROLE",
        "DROP SCHEMA",
        "TRUNCATE ",
        "SUPERUSER;",
        "CREATEDB;",
        "CREATEROLE;",
        "DATABASE_URL",
        "PASSWORD '",
        'PASSWORD "',
        "REASSIGN OWNED",
        "DROP OWNED",
    )
    for fragment in forbidden:
        assert fragment not in upper

    secret_patterns = (
        r"postgres(?:ql)?://[^\s:{]+:[^\s@{]+@",
        r"(?i)(api[_-]?key|token|secret)\s*[=:]\s*['\"][^'{\"]+",
        r"(?i)host\s*=\s*(?!\{\{)[a-z0-9.-]+",
    )
    for pattern in secret_patterns:
        assert re.search(pattern, sql) is None


def validate_documentation() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    for context_name, (dbi_environment, database_name) in EXPECTED.items():
        assert context_name in text.lower()
        assert f"`{dbi_environment}`" in text
        assert f"`{database_name}`" in text
    for term in (
        "DBI_ENVIRONMENT",
        "DBI_DATABASE_URL",
        "DATABASE_URL",
        "Aprovisionamiento controlado",
        "Verificación mínima",
        "Reversión",
        "Rotación de credenciales",
        "DROP DATABASE",
        "migrator",
        "observer",
    ):
        assert term in text


def main() -> None:
    validate_matrix()
    validate_sql_template()
    validate_documentation()
    print("Infraestructura PostgreSQL/PostGIS DBI validada offline.")


if __name__ == "__main__":
    main()
