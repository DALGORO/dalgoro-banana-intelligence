# backend/scripts/sync_templates.py
from __future__ import annotations

import argparse
from pathlib import Path
import json
from typing import Any, Dict, Tuple, List

from app.db.session import SessionLocal
from app.models.document_template import DocumentTemplate
from app.services.sst_rules import normalize_activity


# -------------------------------------------------------------------
# Utilidades
# -------------------------------------------------------------------

def parse_version_num(v: str | int | None) -> int:
    """
    Convierte una versión tipo '1', '1.0', '2.3' a un entero para comparar.
    Si no se puede parsear, devuelve 0.
    """
    if v is None:
        return 0
    s = str(v).strip()
    if not s:
        return 0
    # Tomamos solo la parte entera antes del primer punto
    head = s.split(".")[0]
    try:
        return int(head)
    except Exception:
        return 0


def load_sidecar(
    sidecar: Path, *, filename_code: str, folder_activity: str
) -> Tuple[str, str, List[dict]]:
    """
    Devuelve (title, version_str, fields_json) desde el .json si existe.
    Si no existe, usa valores por defecto basados en el nombre del archivo.

    Además valida coherencia entre:
      - code del JSON vs nombre del archivo
      - activity del JSON vs carpeta (normalizada)
    """
    title = filename_code            # por defecto usamos el código
    version_str = "1"                # versión por defecto
    fields: List[dict] = []

    if sidecar.exists():
        try:
            data: Dict[str, Any] = json.loads(sidecar.read_text(encoding="utf-8"))

            code_json = str(data.get("code", "")).strip().upper()
            act_json_raw = data.get("activity")
            act_json_norm = normalize_activity(act_json_raw) if act_json_raw else None

            if code_json and code_json != filename_code.upper():
                print(
                    f"[WARN] code en JSON ({code_json}) "
                    f"no coincide con el nombre de archivo ({filename_code}) "
                    f"en {sidecar}"
                )

            if act_json_norm and act_json_norm != folder_activity:
                print(
                    f"[WARN] activity en JSON ({act_json_norm}) "
                    f"no coincide con la carpeta ({folder_activity}) "
                    f"en {sidecar}"
                )

            title = str(data.get("title") or title)
            version_raw = data.get("version") or version_str
            version_str = str(version_raw)
            fields = list(data.get("fields") or fields)

        except Exception as exc:
            # si el json está malformado, seguimos con defaults
            print(f"[WARN] No se pudo leer JSON {sidecar}: {exc}")

    return title, version_str, fields


def upsert_template(
    session,
    *,
    activity: str,
    code: str,
    title: str,
    version: str,
    fields_json: list,
    file_path: str,
) -> DocumentTemplate:
    """
    Crea/actualiza un registro de DocumentTemplate para (activity, code).
    - Si no existe: lo crea con los datos del sidecar.
    - Si existe:
        - actualiza file_path
        - actualiza versión si la nueva es mayor
        - actualiza siempre fields_json con lo que tenga el JSON
    """
    row: DocumentTemplate | None = (
        session.query(DocumentTemplate)
        .filter(DocumentTemplate.activity == activity, DocumentTemplate.code == code)
        .order_by(DocumentTemplate.created_at.desc())
        .first()
    )

    if row is None:
        row = DocumentTemplate(
            activity=activity,
            code=code,
            title=title,
            version=str(version),
            fields_json=fields_json,
            file_path=file_path,
        )
        session.add(row)
        print(f"[NEW] {activity} / {code} -> {file_path}")
    else:
        row.file_path = file_path

        # Actualizamos título si viene definido en el sidecar
        if title and title != row.title:
            row.title = title

        # Actualizamos versión solo si la nueva es mayor
        old_v = parse_version_num(row.version)
        new_v = parse_version_num(version)
        if new_v > old_v:
            row.version = str(version)

        # Siempre sincronizamos fields_json con el JSON
        if fields_json:
            row.fields_json = fields_json

        print(f"[UPD] {activity} / {code} -> {file_path}")

    return row


# -------------------------------------------------------------------
# Proceso principal
# -------------------------------------------------------------------

def sync(base_dir: Path) -> int:
    """
    Recorre base_dir/<ACTIVIDAD>/*.docx y *.xlsx y registra/actualiza en DB.
    Retorna cantidad de plantillas procesadas.
    """
    session = SessionLocal()
    count = 0

    try:
        for act_dir in base_dir.iterdir():
            if not act_dir.is_dir():
                continue

            # La carpeta se normaliza a clave de actividad (BANANERA, CAMARONERA, etc.)
            activity = normalize_activity(act_dir.name)

            # 1) Primero DOCX
            for tpl in act_dir.glob("*.docx"):
                code = tpl.stem.upper()
                sidecar = tpl.with_suffix(".json")

                title, version_str, fields = load_sidecar(
                    sidecar,
                    filename_code=code,
                    folder_activity=activity,
                )

                rel_path = tpl.relative_to(base_dir).as_posix()

                upsert_template(
                    session,
                    activity=activity,
                    code=code,
                    title=title,
                    version=version_str,
                    fields_json=fields,
                    file_path=rel_path,
                )
                count += 1

            # También sincronizar *.xlsx
            for tpl in act_dir.glob("*.xlsx"):
                code = tpl.stem.upper()            # IPERC-01.xlsx -> IPERC-01
                sidecar = tpl.with_suffix(".json") # IPERC-01.json (opcional)

                title, version_str, fields = load_sidecar(
                    sidecar,
                    filename_code=code,
                    folder_activity=activity,
                )

                rel_path = tpl.relative_to(base_dir).as_posix()

                upsert_template(
                    session,
                    activity=activity,
                    code=code,
                    title=title,
                    version=version_str,
                    fields_json=fields,
                    file_path=rel_path,
                )
                count += 1


        session.commit()
        return count
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description="Sincroniza plantillas DOCX/XLSX en la BD")
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Carpeta base de plantillas. Si no se pasa, usa app/static/templates",
    )
    args = parser.parse_args()

    here = Path(__file__).resolve()
    default_base = here.parents[1] / "app" / "static" / "templates"
    base_dir = Path(args.base_dir) if args.base_dir else default_base

    if not base_dir.exists():
        raise SystemExit(f"No existe la carpeta de plantillas: {base_dir}")

    total = sync(base_dir)
    print(f"[OK] Plantillas sincronizadas: {total} (base_dir={base_dir})")


if __name__ == "__main__":
    main()
