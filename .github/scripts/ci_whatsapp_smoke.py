"""Smoke test del bot con Google Sheets sustituido por un doble local."""

from __future__ import annotations

import os
import sys
import types
from typing import Any, Callable


class _FakeSheetsManager:
    """Evita autenticación y operaciones reales durante la importación."""

    def __getattr__(self, _name: str) -> Callable[..., Any]:
        return lambda *_args, **_kwargs: None


def _install_fake_sheets_module() -> None:
    fake_module = types.ModuleType("google_sheets_utils")
    fake_module.sheets_manager = _FakeSheetsManager()
    sys.modules["google_sheets_utils"] = fake_module


def main() -> None:
    """Importa Flask y comprueba que el endpoint raíz responde localmente."""

    os.environ["GREEN_API_INSTANCE"] = "dbi-ci-instance"
    os.environ["GREEN_API_TOKEN"] = "dbi-ci-placeholder"
    os.environ["GOOGLE_SHEET_ID"] = "dbi-ci-sheet"
    os.environ["GOOGLE_CREDENTIALS_JSON"] = ""
    os.environ["ENVIAR_NOTIFICACIONES"] = "false"
    os.environ["ENVIAR_PDF_SERVICIOS"] = "false"

    _install_fake_sheets_module()

    from green_api_client import limpiar_numero
    from webhook import app

    response = app.test_client().get("/")

    assert response.status_code == 200
    assert response.get_data(as_text=True) == "DALGORO bot activo"
    assert limpiar_numero("+593 999 000 111@c.us") == "593999000111"

    print("WhatsApp smoke test: importación y endpoint local aprobados.")


if __name__ == "__main__":
    main()
