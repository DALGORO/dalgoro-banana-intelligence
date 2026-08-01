"""Ejecutor cerrado de la integración administrativa DBI real."""

from __future__ import annotations

from ci_dbi_admin_integration import main as run_admin_integration
from ci_dbi_admin_privilege_diagnostics import (
    harden_and_validate_api_role,
)


def main() -> None:
    """Normaliza la ACL exacta y después ejecuta la integración funcional."""

    harden_and_validate_api_role()
    run_admin_integration()


if __name__ == "__main__":
    main()
