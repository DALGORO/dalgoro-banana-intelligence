from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.document import Document
from app.models.iperc_item import IPERCItem
from app.services.iperc_derivatives import derive_critical_epp
from app.services.sst_rules import (
    classify_by_workers,
    decide_org,
    decide_responsible,
    normalize_risk,
)

PROCEDURE_KIND = "INV-AT-01-PROC"
CASE_KIND = "INV-AT-01-CASE"
WORKER_KIND = "SST-WORKER"
WORKER_EPP_KIND = "SST-WORKER-EPP"
JSON_RECORD_MIME = "application/x-sst-record+json"

TECHNICAL_KEYWORDS = (
    "API",
    "ENDPOINT",
    "BACKEND",
    "FRONTEND",
    "CODIGO FUENTE",
    "SOURCE CODE",
    "BASE DE DATOS",
    "DATABASE",
    "TABLA SQL",
    "MIGRACION",
    "MIGRATION",
    "TOKEN",
    "JWT",
    "SECRET",
    "CREDENCIAL",
    "CREDENTIAL",
    "PROMPT",
    "SERVIDOR",
    "SERVER",
    "REACT",
    "FASTAPI",
    "AXIOS",
    "ROUTER",
    "ARQUITECTURA INTERNA",
    "RUTA INTERNA",
)

BASE_SOURCES = [
    "Acuerdo Ministerial 196 (2024)",
    "Anexo 1 - Lista de Verificación SST",
    "Anexo 3 - Norma Técnica de Seguridad e Higiene del Trabajo",
    "Decreto Ejecutivo 255 (2024)",
]


def _now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _normalize_text(value: str | None) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.upper()
    return re.sub(r"\s+", " ", raw).strip()


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _safe_meta(doc: Document) -> dict[str, Any]:
    return doc.meta if isinstance(doc.meta, dict) else {}


def _format_date(value: str | None) -> str:
    if not value:
        return "sin fecha registrada"
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", ""))
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return str(value)


def _company_context(company: Company) -> dict[str, Any]:
    workers = int(getattr(company, "workers", 0) or 0)
    risk = normalize_risk(getattr(company, "risk_level", None))
    classification = classify_by_workers(workers)

    return {
        "company_id": company.id,
        "name": getattr(company, "name", "Empresa"),
        "activity": getattr(company, "activity", "OTROS"),
        "workers": workers,
        "risk": risk,
        "classification": classification,
        "responsible": decide_responsible(classification, risk),
        "organ": decide_org(classification),
    }


def _is_related_inv_doc(doc: Document) -> bool:
    haystack = _normalize_text(
        " ".join(
            [
                str(getattr(doc, "kind", "") or ""),
                str(getattr(doc, "title", "") or ""),
                str(getattr(doc, "requirement_code", "") or ""),
            ]
        )
    )
    return (
        "INV-AT-01" in haystack
        or "INVESTIGACION" in haystack
        or "ACCIDENTE" in haystack
        or "INCIDENTE" in haystack
    )


def _serialize_related_doc(doc: Document) -> dict[str, Any]:
    return {
        "id": doc.id,
        "title": getattr(doc, "title", None),
        "kind": getattr(doc, "kind", None),
        "requirement_code": getattr(doc, "requirement_code", None),
        "created_at": getattr(doc, "created_at", None).isoformat() if getattr(doc, "created_at", None) else None,
        "has_file": bool(getattr(doc, "storage_path", None)),
    }


def _serialize_procedure(session: Session, company: Company, doc: Document | None) -> dict[str, Any]:
    context = _company_context(company)
    iperc = _get_iperc_snapshot(session, company.id)
    _, job_epp_map = _build_job_epp_catalog(session, company)

    meta = _safe_meta(doc) if doc else {}

    governance_doc = (
        "Plan de Prevención de Riesgos Laborales"
        if int(context["workers"] or 0) <= 10
        else "Reglamento de Higiene y Seguridad"
    )

    jobs_text = ", ".join(iperc["jobs"][:10]) if iperc["jobs"] else "sin puestos IPERC registrados"
    process_text = ", ".join(iperc["processes"][:8]) if iperc["processes"] else "sin procesos IPERC registrados"
    hazard_group_text = ", ".join(iperc["hazard_groups"][:8]) if iperc["hazard_groups"] else "sin grupos de peligro registrados"

    job_epp_lines: list[str] = []
    for job, items in sorted(job_epp_map.items()):
        if not items:
            continue
        job_epp_lines.append(f"{job}: {', '.join(items[:8])}")

    generated_sections = {
        "objetivo": (
            f"Establecer el procedimiento único de investigación de accidentes e incidentes de la empresa "
            f"{context['name']} para asegurar la notificación, registro, investigación, determinación de causas, "
            f"aplicación de acciones inmediatas, correctivas y preventivas, y el seguimiento documentado dentro del sistema."
        ),
        "alcance": (
            f"Aplica a todos los trabajadores propios y a los eventos ocurridos en los lugares y/o centros de trabajo "
            f"relacionados con la actividad {context['activity']}. Se articula con el {governance_doc} que corresponde "
            f"a la empresa según su número de trabajadores."
        ),
        "responsabilidades": "\n".join([
            f"- Máxima autoridad: aprobar el procedimiento y asegurar su cumplimiento.",
            f"- Responsable SST actual del sistema: {context['responsible']}.",
            f"- Figura organizativa SST del sistema: {context['organ']}.",
            "- Jefaturas/supervisores: notificar el evento, colaborar en la investigación y verificar el cierre de acciones.",
            "- Trabajadores: reportar el evento y cooperar en la investigación.",
        ]),
        "procedimiento_investigacion": "\n".join([
            "1. Atender a la persona afectada y controlar de inmediato la condición peligrosa.",
            "2. Notificar internamente el evento.",
            "3. Registrar el caso dentro del módulo 'Investigación y consultas SST'.",
            "4. Identificar trabajador, puesto, lugar, fecha, hora, descripción y consecuencias.",
            "5. Levantar testigos y evidencia disponible.",
            "6. Analizar causas inmediatas y causas básicas.",
            "7. Registrar acciones inmediatas, correctivas y preventivas.",
            "8. Reportar a la autoridad competente cuando corresponda.",
            "9. Hacer seguimiento hasta el cierre del caso y reflejar el evento en los indicadores del sistema.",
        ]),
        "documentacion_registro": "\n".join([
            "- Procedimiento documentado aprobado por la empresa.",
            "- Registro interno del incidente o accidente.",
            "- Informe de investigación del caso.",
            "- Ficha del trabajador involucrado.",
            "- Evidencia de entrega de EPP asociada al trabajador, cuando aplique.",
            "- Soportes complementarios: fotografías, testigos, observaciones y seguimiento.",
        ]),
        "acciones_correctivas_preventivas": (
            "Toda investigación debe concluir en medidas de control y/o correctivas para evitar recurrencia, "
            "con responsable, fecha compromiso y verificación de cierre dentro del sistema."
        ),
        "consideraciones_actividad": "\n".join([
            f"- Actividad registrada: {context['activity']}.",
            f"- Número de trabajadores: {context['workers']}.",
            f"- Nivel de riesgo registrado: {context['risk']}.",
            f"- Procesos detectados en IPERC: {process_text}.",
            f"- Puestos detectados en IPERC: {jobs_text}.",
            f"- Grupos de peligro detectados: {hazard_group_text}.",
            "- El procedimiento debe aplicarse priorizando los procesos, puestos y riesgos realmente existentes en la IPERC vigente de la empresa.",
        ]),
        "epp_por_puesto": (
            "\n".join(job_epp_lines)
            if job_epp_lines
            else "Todavía no se dispone de una matriz derivada de EPP por puesto desde la IPERC vigente."
        ),
        "ejecucion_en_sistema": "\n".join([
            "1. Revisar este procedimiento autogenerado.",
            "2. Registrar o actualizar la aprobación de la máxima autoridad.",
            "3. Registrar trabajadores vinculados a puestos IPERC.",
            "4. Registrar entregas de EPP por trabajador.",
            "5. Registrar el incidente o accidente del trabajador.",
            "6. Dar seguimiento y cierre al caso.",
        ]),
    }

    generated_summary = (
        f"Procedimiento único por empresa para {context['activity']}, con {context['workers']} trabajadores, "
        f"riesgo {context['risk']}, responsable SST tipo {context['responsible']} y foco en los puestos y riesgos "
        f"vigentes en la IPERC del sistema."
    )

    return {
        "exists": bool(doc),
        "document_id": doc.id if doc else None,
        "title": doc.title if doc else "INV-AT-01 Procedimiento documentado de investigación de accidentes",
        "updated_at": meta.get("updated_at") or (doc.created_at.isoformat() if doc and doc.created_at else None),
        "fields": {
            "approved_by": str(meta.get("approved_by", "") or ""),
            "approved_role": str(meta.get("approved_role", "") or ""),
            "approved_at": str(meta.get("approved_at", "") or ""),
            "notes": str(meta.get("notes", "") or ""),
        },
        "generated_summary": generated_summary,
        "generated_sections": generated_sections,
    }


def _serialize_case(doc: Document) -> dict[str, Any]:
    meta = _safe_meta(doc)

    return {
        "document_id": doc.id,
        "title": doc.title,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "event_type": str(meta.get("event_type", "INCIDENTE") or "INCIDENTE"),
        "status": str(meta.get("status", "ABIERTO") or "ABIERTO"),
        "happened_at": str(meta.get("happened_at", "") or ""),
        "worker_document_id": int(meta.get("worker_document_id", 0) or 0),
        "worker_name": str(meta.get("worker_name", "") or ""),
        "id_number": str(meta.get("id_number", "") or ""),
        "job_title": str(meta.get("job_title", "") or ""),
        "place": str(meta.get("place", "") or ""),
        "description": str(meta.get("description", "") or ""),
        "consequences": str(meta.get("consequences", "") or ""),
        "witnesses": str(meta.get("witnesses", "") or ""),
        "causes": str(meta.get("causes", "") or ""),
        "immediate_actions": str(meta.get("immediate_actions", "") or ""),
        "corrective_actions": str(meta.get("corrective_actions", "") or ""),
        "preventive_actions": str(meta.get("preventive_actions", "") or ""),
        "reported_to_authority": bool(meta.get("reported_to_authority", False)),
    }


def _serialize_worker(
    doc: Document,
    incident_count: int = 0,
    epp_count: int = 0,
    recommended_epp: list[str] | None = None,
) -> dict[str, Any]:
    meta = _safe_meta(doc)
    return {
        "document_id": doc.id,
        "title": doc.title,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "full_name": str(meta.get("full_name", "") or ""),
        "id_number": str(meta.get("id_number", "") or ""),
        "job": str(meta.get("job", "") or ""),
        "start_date": str(meta.get("start_date", "") or ""),
        "status": str(meta.get("status", "ACTIVO") or "ACTIVO"),
        "notes": str(meta.get("notes", "") or ""),
        "incident_count": incident_count,
        "epp_delivery_count": epp_count,
        "recommended_epp": recommended_epp or [],
    }
    

def _serialize_epp_delivery(doc: Document) -> dict[str, Any]:
    meta = _safe_meta(doc)
    return {
        "document_id": doc.id,
        "title": doc.title,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "worker_document_id": int(meta.get("worker_document_id", 0) or 0),
        "worker_name": str(meta.get("worker_name", "") or ""),
        "id_number": str(meta.get("id_number", "") or ""),
        "job": str(meta.get("job", "") or ""),
        "delivery_date": str(meta.get("delivery_date", "") or ""),
        "items_text": str(meta.get("items_text", "") or ""),
        "return_notes": str(meta.get("return_notes", "") or ""),
        "observations": str(meta.get("observations", "") or ""),
        "worker_receipt_name": str(meta.get("worker_receipt_name", "") or ""),
        "employer_receipt_name": str(meta.get("employer_receipt_name", "") or ""),
    }


def _get_iperc_jobs(session: Session, company_id: int) -> list[str]:
    rows = (
        session.query(IPERCItem.job)
        .filter(IPERCItem.company_id == company_id)
        .distinct()
        .all()
    )
    jobs = sorted(
        {
            str(row[0]).strip()
            for row in rows
            if row and row[0] and str(row[0]).strip()
        }
    )
    return jobs


def _unique_clean(values: list[str], limit: int | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = str(value or "").strip()
        norm = _normalize_text(text)
        if not text or norm in seen:
            continue
        seen.add(norm)
        out.append(text)

    if limit is not None:
        return out[:limit]
    return out


def _get_iperc_snapshot(session: Session, company_id: int) -> dict[str, list[str]]:
    rows = (
        session.query(
            IPERCItem.process,
            IPERCItem.job,
            IPERCItem.hazard_group,
            IPERCItem.hazard,
        )
        .filter(IPERCItem.company_id == company_id)
        .all()
    )

    processes = _unique_clean([str(r[0] or "") for r in rows])
    jobs = _unique_clean([str(r[1] or "") for r in rows])
    hazard_groups = _unique_clean([str(r[2] or "") for r in rows])
    hazards = _unique_clean([str(r[3] or "") for r in rows], limit=12)

    return {
        "processes": processes,
        "jobs": jobs,
        "hazard_groups": hazard_groups,
        "hazards": hazards,
    }

def _normalize_epp_items(value: Any) -> list[str]:
    raw: list[Any] = []

    if isinstance(value, list):
        raw = value
    elif isinstance(value, dict):
        raw = (
            value.get("items")
            or value.get("values")
            or value.get("epp")
            or []
        )
    elif value is not None:
        raw = [value]

    out: list[str] = []
    seen: set[str] = set()

    for item in raw:
        text = str(item or "").strip()
        norm = _normalize_text(text)
        if not text:
            continue
        if "NO APLICA" in norm:
            continue
        if norm in seen:
            continue
        seen.add(norm)
        out.append(text)

    return out


def _build_job_epp_catalog(session: Session, company: Company) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    activity_norm = _normalize_text(getattr(company, "activity", None)) or None
    derived = derive_critical_epp(
        db=session,
        company_id=company.id,
        activity=activity_norm,
    )

    job_map: dict[str, list[str]] = {}

    for row in derived:
        job = str(row.get("puesto", "") or "").strip()
        if not job:
            continue

        items = _normalize_epp_items(row.get("epp"))
        if not items:
            continue

        bucket = job_map.setdefault(job, [])
        seen = {_normalize_text(x) for x in bucket}

        for item in items:
            norm = _normalize_text(item)
            if norm not in seen:
                bucket.append(item)
                seen.add(norm)

    catalog = [{"job": job, "items": items} for job, items in sorted(job_map.items())]
    return catalog, job_map


def _get_company_docs(session: Session, company_id: int) -> list[Document]:
    return (
        session.query(Document)
        .filter(Document.company_id == company_id)
        .order_by(Document.created_at.desc())
        .all()
    )


def _split_docs(docs: list[Document]) -> tuple[Document | None, list[Document], list[Document], list[Document], list[Document]]:
    procedure_doc = None
    case_docs: list[Document] = []
    worker_docs: list[Document] = []
    epp_docs: list[Document] = []
    generated_docs: list[Document] = []

    for doc in docs:
        kind = str(getattr(doc, "kind", "") or "").upper()

        if kind == PROCEDURE_KIND:
            if procedure_doc is None:
                procedure_doc = doc
            continue

        if kind == CASE_KIND:
            case_docs.append(doc)
            continue

        if kind == WORKER_KIND:
            worker_docs.append(doc)
            continue

        if kind == WORKER_EPP_KIND:
            epp_docs.append(doc)
            continue

        if _is_related_inv_doc(doc):
            generated_docs.append(doc)

    return procedure_doc, case_docs, worker_docs, epp_docs, generated_docs


def _get_worker_doc(session: Session, company_id: int, worker_document_id: int) -> Document:
    worker = session.get(Document, worker_document_id)
    if not worker or worker.company_id != company_id or str(getattr(worker, "kind", "") or "").upper() != WORKER_KIND:
        raise ValueError("Trabajador no encontrado")
    return worker


def _validate_job_in_iperc(session: Session, company_id: int, job: str) -> None:
    jobs = _get_iperc_jobs(session, company_id)
    if not jobs:
        raise ValueError("Primero debes registrar puestos en la matriz IPERC.")
    if str(job or "").strip() not in jobs:
        raise ValueError("El puesto seleccionado no existe en la matriz IPERC.")


def get_incident_module_state(session: Session, company: Company) -> dict[str, Any]:
    context = _company_context(company)
    docs = _get_company_docs(session, company.id)
    procedure_doc, case_docs, worker_docs, epp_docs, generated_docs = _split_docs(docs)
    iperc_jobs = _get_iperc_jobs(session, company.id)
    job_epp_catalog, job_epp_map = _build_job_epp_catalog(session, company)

    serialized_cases = [_serialize_case(doc) for doc in case_docs]
    serialized_cases.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)

    incident_count_by_worker: dict[int, int] = {}
    for item in serialized_cases:
        worker_id = int(item.get("worker_document_id", 0) or 0)
        if worker_id > 0:
            incident_count_by_worker[worker_id] = incident_count_by_worker.get(worker_id, 0) + 1

    serialized_epp = [_serialize_epp_delivery(doc) for doc in epp_docs]
    serialized_epp.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)

    epp_count_by_worker: dict[int, int] = {}
    for item in serialized_epp:
        worker_id = int(item.get("worker_document_id", 0) or 0)
        if worker_id > 0:
            epp_count_by_worker[worker_id] = epp_count_by_worker.get(worker_id, 0) + 1

    serialized_workers = [
        _serialize_worker(
            doc,
            incident_count=incident_count_by_worker.get(doc.id, 0),
            epp_count=epp_count_by_worker.get(doc.id, 0),
            recommended_epp=job_epp_map.get(str(_safe_meta(doc).get("job", "") or "").strip(), []),
        )
        for doc in worker_docs
    ]
    serialized_workers.sort(key=lambda x: str(x.get("full_name") or "").upper())

    total_cases = len(serialized_cases)
    total_accidents = sum(1 for c in serialized_cases if str(c.get("event_type", "")).upper() == "ACCIDENTE")
    total_incidents = sum(1 for c in serialized_cases if str(c.get("event_type", "")).upper() != "ACCIDENTE")
    open_cases = sum(1 for c in serialized_cases if str(c.get("status", "")).upper() != "CERRADO")
    closed_cases = sum(1 for c in serialized_cases if str(c.get("status", "")).upper() == "CERRADO")

    current_year = datetime.utcnow().year
    cases_this_year = 0
    for c in serialized_cases:
        happened_at = str(c.get("happened_at") or "")
        try:
            dt = datetime.fromisoformat(happened_at.replace("Z", ""))
            if dt.year == current_year:
                cases_this_year += 1
        except Exception:
            pass

    latest_case = serialized_cases[0] if serialized_cases else None

    blocking_message = None
    can_register_workers = True
    can_register_cases = True

    if len(iperc_jobs) == 0:
        can_register_workers = False
        can_register_cases = False
        blocking_message = "Debes registrar primero los puestos en la matriz IPERC. Sin puestos IPERC no se habilita el registro de trabajadores ni la investigación."
    elif len(serialized_workers) == 0:
        can_register_cases = False
        blocking_message = "Debes registrar al menos un trabajador con un puesto existente en IPERC antes de crear una investigación."

    return {
        "company": context,
        "iperc_jobs": iperc_jobs,
        "procedure": _serialize_procedure(session, company, procedure_doc),
        "stats": {
            "total_cases": total_cases,
            "total_accidents": total_accidents,
            "total_incidents": total_incidents,
            "open_cases": open_cases,
            "closed_cases": closed_cases,
            "cases_this_year": cases_this_year,
        },
        "latest_case": latest_case,
        "cases": serialized_cases,
        "workers": serialized_workers,
        "job_epp_catalog": job_epp_catalog,
        "epp_deliveries": serialized_epp,
        "can_register_workers": can_register_workers,
        "can_register_cases": can_register_cases,
        "blocking_message": blocking_message,
        "generated_documents": [_serialize_related_doc(d) for d in generated_docs[:10]],
    }


def upsert_incident_procedure(session: Session, company: Company, payload: dict[str, Any]) -> dict[str, Any]:
    docs = _get_company_docs(session, company.id)
    procedure_doc, _, _, _, _ = _split_docs(docs)

    if procedure_doc is None:
        procedure_doc = Document(
            company_id=company.id,
            kind=PROCEDURE_KIND,
            title="INV-AT-01 Procedimiento documentado de investigación de accidentes",
            requirement_code="INV-AT-01",
            mime=JSON_RECORD_MIME,
            storage_path="",
            period_year=datetime.utcnow().year,
            seq=1,
            meta={},
        )
        session.add(procedure_doc)

    meta = dict(_safe_meta(procedure_doc))
    meta.update(
        {
            "record_type": "procedure",
            "approved_by": str(payload.get("approved_by", "") or ""),
            "approved_role": str(payload.get("approved_role", "") or ""),
            "approved_at": str(payload.get("approved_at", "") or ""),
            "notes": str(payload.get("notes", "") or ""),
            "updated_at": _now_iso(),
        }
    )
    procedure_doc.meta = meta

    session.commit()
    session.refresh(procedure_doc)
    return _serialize_procedure(session, company, procedure_doc)

def _next_document_seq(session: Session, company_id: int, kind: str) -> int:
    rows = (
        session.query(Document)
        .filter(Document.company_id == company_id, Document.kind == kind)
        .all()
    )

    max_seq = 0
    for row in rows:
        try:
            value = int(getattr(row, "seq", 0) or 0)
            if value > max_seq:
                max_seq = value
        except Exception:
            continue

    return max_seq + 1


def _render_procedure_pdf_html(company: Company, procedure: dict[str, Any]) -> str:
    from html import escape

    context = _company_context(company)
    fields = procedure.get("fields", {}) or {}
    sections = procedure.get("generated_sections", {}) or {}

    def fmt(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return "—"
        return "<br>".join(escape(text).splitlines())

    generated_on = datetime.utcnow().strftime("%Y-%m-%d %H:%M")

    return f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
      <meta charset="utf-8" />
      <style>
        @page {{
          size: A4;
          margin: 2cm;
        }}
        body {{
          font-family: Arial, Helvetica, sans-serif;
          color: #1f2937;
          font-size: 11pt;
          line-height: 1.45;
        }}
        h1 {{
          font-size: 18pt;
          margin-bottom: 4px;
        }}
        h2 {{
          font-size: 12pt;
          margin-top: 18px;
          margin-bottom: 6px;
          padding-bottom: 4px;
          border-bottom: 1px solid #d1d5db;
        }}
        .muted {{
          color: #6b7280;
          font-size: 10pt;
        }}
        .box {{
          border: 1px solid #d1d5db;
          border-radius: 8px;
          padding: 10px 12px;
          margin-top: 8px;
        }}
        .grid {{
          width: 100%;
          border-collapse: collapse;
          margin-top: 8px;
        }}
        .grid td {{
          border: 1px solid #d1d5db;
          padding: 8px;
          vertical-align: top;
        }}
        .label {{
          width: 180px;
          font-weight: bold;
          background: #f3f4f6;
        }}
      </style>
    </head>
    <body>
      <h1>{escape(str(procedure.get("title") or "INV-AT-01 Procedimiento documentado"))}</h1>
      <div class="muted">
        Empresa: {escape(str(getattr(company, "name", "") or ""))} |
        RUC: {escape(str(getattr(company, "ruc", "") or ""))} |
        Actividad: {escape(str(context.get("activity", "") or ""))} |
        Trabajadores: {escape(str(context.get("workers", "") or ""))} |
        Riesgo: {escape(str(context.get("risk", "") or ""))}
      </div>

      <div class="box">
        <strong>Resumen autogenerado del procedimiento</strong><br>
        {fmt(procedure.get("generated_summary", ""))}
      </div>

      <h2>Objetivo</h2>
      <div>{fmt(sections.get("objetivo", ""))}</div>

      <h2>Alcance</h2>
      <div>{fmt(sections.get("alcance", ""))}</div>

      <h2>Responsabilidades</h2>
      <div>{fmt(sections.get("responsabilidades", ""))}</div>

      <h2>Procedimiento de investigación</h2>
      <div>{fmt(sections.get("procedimiento_investigacion", ""))}</div>

      <h2>Documentación y registro</h2>
      <div>{fmt(sections.get("documentacion_registro", ""))}</div>

      <h2>Acciones correctivas y preventivas</h2>
      <div>{fmt(sections.get("acciones_correctivas_preventivas", ""))}</div>

      <h2>Consideraciones por actividad</h2>
      <div>{fmt(sections.get("consideraciones_actividad", ""))}</div>

      <h2>EPP por puesto</h2>
      <div>{fmt(sections.get("epp_por_puesto", ""))}</div>

      <h2>Ejecución en el sistema</h2>
      <div>{fmt(sections.get("ejecucion_en_sistema", ""))}</div>

      <h2>Aprobación</h2>
      <table class="grid">
        <tr>
          <td class="label">Aprobado por</td>
          <td>{fmt(fields.get("approved_by", ""))}</td>
        </tr>
        <tr>
          <td class="label">Cargo</td>
          <td>{fmt(fields.get("approved_role", ""))}</td>
        </tr>
        <tr>
          <td class="label">Fecha de aprobación</td>
          <td>{fmt(fields.get("approved_at", ""))}</td>
        </tr>
        <tr>
          <td class="label">Observaciones</td>
          <td>{fmt(fields.get("notes", ""))}</td>
        </tr>
      </table>

      <div class="muted" style="margin-top: 18px;">
        Documento generado desde el módulo Investigación y consultas SST el {escape(generated_on)}.
      </div>
    </body>
    </html>
    """


def generate_incident_procedure_pdf(
    session: Session,
    company: Company,
    user_id: int = 0,
) -> dict[str, Any]:
    from weasyprint import HTML
    from app.services.storage import save_bytes

    docs = _get_company_docs(session, company.id)
    procedure_doc, _, _, _, _ = _split_docs(docs)

    if procedure_doc is None:
        raise ValueError("Primero debes guardar la aprobación del procedimiento dentro del módulo.")

    procedure = _serialize_procedure(session, company, procedure_doc)
    fields = procedure.get("fields", {}) or {}

    approved_by = str(fields.get("approved_by", "") or "").strip()
    approved_role = str(fields.get("approved_role", "") or "").strip()
    approved_at = str(fields.get("approved_at", "") or "").strip()

    if not approved_by:
        raise ValueError("Debes completar 'Aprobado por' antes de generar el PDF.")
    if not approved_role:
        raise ValueError("Debes completar el cargo de quien aprueba antes de generar el PDF.")
    if not approved_at:
        raise ValueError("Debes completar la fecha de aprobación antes de generar el PDF.")

    html = _render_procedure_pdf_html(company, procedure)
    pdf_bytes = HTML(string=html).write_pdf()

    seq = _next_document_seq(session, company.id, "INV-AT-01")
    date_label = datetime.utcnow().strftime("%Y-%m-%d")

    title = f"INV-AT-01 Procedimiento documentado {date_label} V{seq:03d}"
    filename = f"INV-AT-01_PROCEDIMIENTO_{date_label}_V{seq:03d}.pdf"

    path = save_bytes(
        company_id=company.id,
        filename=filename,
        content=pdf_bytes,
        user_id=user_id,
        doc_type="DOCS",
    )

    generated_doc = Document(
        company_id=company.id,
        kind="INV-AT-01",
        title=title,
        storage_path=path,
        mime="application/pdf",
        requirement_code="INV-AT-01",
        period_year=datetime.utcnow().year,
        seq=seq,
        meta={
            "record_type": "procedure_pdf",
            "source_procedure_document_id": procedure_doc.id,
            "approved_by": approved_by,
            "approved_role": approved_role,
            "approved_at": approved_at,
            "notes": str(fields.get("notes", "") or ""),
            "generated_summary": str(procedure.get("generated_summary", "") or ""),
            "generated_sections": procedure.get("generated_sections", {}) or {},
            "updated_at": _now_iso(),
        },
    )

    session.add(generated_doc)
    session.commit()
    session.refresh(generated_doc)

    return {
        "id": generated_doc.id,
        "title": generated_doc.title,
        "mime": generated_doc.mime,
        "created_at": generated_doc.created_at.isoformat() if generated_doc.created_at else None,
    }
    
def create_worker_profile(session: Session, company: Company, payload: dict[str, Any]) -> dict[str, Any]:
    full_name = str(payload.get("full_name", "") or "").strip()
    id_number = str(payload.get("id_number", "") or "").strip()
    job = str(payload.get("job", "") or "").strip()

    if not full_name:
        raise ValueError("Debes ingresar el nombre completo del trabajador.")
    if not job:
        raise ValueError("Debes seleccionar un puesto.")
    _validate_job_in_iperc(session, company.id, job)

    title = f"Trabajador - {full_name}"

    doc = Document(
        company_id=company.id,
        kind=WORKER_KIND,
        title=title,
        requirement_code="SST-WORKER-01",
        mime=JSON_RECORD_MIME,
        storage_path="",
        period_year=datetime.utcnow().year,
        seq=1,
        meta={
            "record_type": "worker",
            "full_name": full_name,
            "id_number": id_number,
            "job": job,
            "start_date": str(payload.get("start_date", "") or ""),
            "status": str(payload.get("status", "ACTIVO") or "ACTIVO").upper(),
            "notes": str(payload.get("notes", "") or ""),
            "updated_at": _now_iso(),
        },
    )

    session.add(doc)
    session.commit()
    session.refresh(doc)
    return _serialize_worker(doc)


def create_worker_epp_delivery(session: Session, company: Company, payload: dict[str, Any]) -> dict[str, Any]:
    worker_document_id = int(payload.get("worker_document_id", 0) or 0)
    if worker_document_id <= 0:
        raise ValueError("Debes seleccionar un trabajador.")

    worker = _get_worker_doc(session, company.id, worker_document_id)
    worker_meta = _safe_meta(worker)

    worker_name = str(worker_meta.get("full_name", "") or "")
    id_number = str(worker_meta.get("id_number", "") or "")
    job = str(worker_meta.get("job", "") or "")

    _, job_epp_map = _build_job_epp_catalog(session, company)

    items_text = str(payload.get("items_text", "") or "").strip()
    if not items_text:
        suggested = job_epp_map.get(job, [])
        if suggested:
            items_text = "\n".join(suggested)
    title = f"EPP - {worker_name} - {_format_date(str(payload.get('delivery_date', '') or ''))}"

    doc = Document(
        company_id=company.id,
        kind=WORKER_EPP_KIND,
        title=title,
        requirement_code="EPP-01",
        mime=JSON_RECORD_MIME,
        storage_path="",
        period_year=datetime.utcnow().year,
        seq=1,
        meta={
            "record_type": "worker_epp_delivery",
            "worker_document_id": worker_document_id,
            "worker_name": worker_name,
            "id_number": id_number,
            "job": job,
            "delivery_date": str(payload.get("delivery_date", "") or ""),
            "items_text": items_text,
            "return_notes": str(payload.get("return_notes", "") or ""),
            "observations": str(payload.get("observations", "") or ""),
            "worker_receipt_name": str(payload.get("worker_receipt_name", "") or ""),
            "employer_receipt_name": str(payload.get("employer_receipt_name", "") or ""),
            "updated_at": _now_iso(),
        },
    )

    session.add(doc)
    session.commit()
    session.refresh(doc)
    return _serialize_epp_delivery(doc)


def create_incident_case(session: Session, company: Company, payload: dict[str, Any]) -> dict[str, Any]:
    state = get_incident_module_state(session, company)
    if not state["can_register_cases"]:
        raise ValueError(state["blocking_message"] or "No se puede registrar el caso todavía.")

    worker_document_id = int(payload.get("worker_document_id", 0) or 0)
    if worker_document_id <= 0:
        raise ValueError("Debes seleccionar un trabajador registrado.")

    worker = _get_worker_doc(session, company.id, worker_document_id)
    worker_meta = _safe_meta(worker)

    worker_name = str(worker_meta.get("full_name", "") or "").strip()
    id_number = str(worker_meta.get("id_number", "") or "").strip()
    job_title = str(worker_meta.get("job", "") or "").strip()
    _validate_job_in_iperc(session, company.id, job_title)

    event_type = str(payload.get("event_type", "INCIDENTE") or "INCIDENTE").upper()
    happened_at = str(payload.get("happened_at", "") or "").strip()
    status = str(payload.get("status", "ABIERTO") or "ABIERTO").upper()

    date_label = "sin-fecha"
    if happened_at:
        try:
            date_label = datetime.fromisoformat(happened_at.replace("Z", "")).strftime("%Y-%m-%d")
        except Exception:
            date_label = happened_at[:10] or "sin-fecha"

    suffix = worker_name if worker_name else event_type
    title = f"INV-AT-01 Caso {date_label} - {suffix}"

    doc = Document(
        company_id=company.id,
        kind=CASE_KIND,
        title=title,
        requirement_code="INV-AT-01",
        mime=JSON_RECORD_MIME,
        storage_path="",
        period_year=datetime.utcnow().year,
        seq=1,
        meta={
            "record_type": "case",
            "event_type": event_type,
            "status": status,
            "happened_at": happened_at,
            "worker_document_id": worker_document_id,
            "worker_name": worker_name,
            "id_number": id_number,
            "job_title": job_title,
            "place": str(payload.get("place", "") or ""),
            "description": str(payload.get("description", "") or ""),
            "consequences": str(payload.get("consequences", "") or ""),
            "witnesses": str(payload.get("witnesses", "") or ""),
            "causes": str(payload.get("causes", "") or ""),
            "immediate_actions": str(payload.get("immediate_actions", "") or ""),
            "corrective_actions": str(payload.get("corrective_actions", "") or ""),
            "preventive_actions": str(payload.get("preventive_actions", "") or ""),
            "reported_to_authority": bool(payload.get("reported_to_authority", False)),
            "updated_at": _now_iso(),
        },
    )

    session.add(doc)
    session.commit()
    session.refresh(doc)
    return _serialize_case(doc)


def update_incident_case(session: Session, company: Company, document_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    doc = session.get(Document, document_id)
    if not doc or doc.company_id != company.id:
        raise ValueError("Caso no encontrado")

    if str(getattr(doc, "kind", "") or "").upper() != CASE_KIND:
        raise ValueError("El documento indicado no es un caso editable del módulo")

    worker_document_id = int(payload.get("worker_document_id", 0) or 0)
    if worker_document_id <= 0:
        raise ValueError("Debes seleccionar un trabajador registrado.")

    worker = _get_worker_doc(session, company.id, worker_document_id)
    worker_meta = _safe_meta(worker)

    worker_name = str(worker_meta.get("full_name", "") or "").strip()
    id_number = str(worker_meta.get("id_number", "") or "").strip()
    job_title = str(worker_meta.get("job", "") or "").strip()
    _validate_job_in_iperc(session, company.id, job_title)

    meta = dict(_safe_meta(doc))
    meta.update(
        {
            "record_type": "case",
            "event_type": str(payload.get("event_type", meta.get("event_type", "INCIDENTE")) or "INCIDENTE").upper(),
            "status": str(payload.get("status", meta.get("status", "ABIERTO")) or "ABIERTO").upper(),
            "happened_at": str(payload.get("happened_at", meta.get("happened_at", "")) or ""),
            "worker_document_id": worker_document_id,
            "worker_name": worker_name,
            "id_number": id_number,
            "job_title": job_title,
            "place": str(payload.get("place", meta.get("place", "")) or ""),
            "description": str(payload.get("description", meta.get("description", "")) or ""),
            "consequences": str(payload.get("consequences", meta.get("consequences", "")) or ""),
            "witnesses": str(payload.get("witnesses", meta.get("witnesses", "")) or ""),
            "causes": str(payload.get("causes", meta.get("causes", "")) or ""),
            "immediate_actions": str(payload.get("immediate_actions", meta.get("immediate_actions", "")) or ""),
            "corrective_actions": str(payload.get("corrective_actions", meta.get("corrective_actions", "")) or ""),
            "preventive_actions": str(payload.get("preventive_actions", meta.get("preventive_actions", "")) or ""),
            "reported_to_authority": bool(payload.get("reported_to_authority", meta.get("reported_to_authority", False))),
            "updated_at": _now_iso(),
        }
    )

    happened_at = str(meta.get("happened_at", "") or "").strip()
    date_label = "sin-fecha"
    if happened_at:
        try:
            date_label = datetime.fromisoformat(happened_at.replace("Z", "")).strftime("%Y-%m-%d")
        except Exception:
            date_label = happened_at[:10] or "sin-fecha"

    suffix = worker_name if worker_name else "CASO"
    doc.title = f"INV-AT-01 Caso {date_label} - {suffix}"
    doc.meta = meta

    session.commit()
    session.refresh(doc)
    return _serialize_case(doc)


def _detect_question_type(question: str) -> str:
    if _contains_any(question, ("SIN LESION", "SIN LESIONES", "CASI ACCIDENTE", "NEAR MISS")):
        return "near_miss"
    if _contains_any(question, ("IMPLEMENTAR", "IMPLEMENTACION", "PROCEDIMIENTO", "FORMATO", "ESTRUCTURAR")):
        return "implementation"
    if _contains_any(question, ("TRABAJADOR", "TRABAJADORES", "FICHA", "PUESTO", "EPP")):
        return "worker"
    if _contains_any(question, ("NORMATIVA", "SUSTENTO", "ARTICULO", "ART.", "OBLIGACION", "REQUISITO")):
        return "normative"
    if _contains_any(question, ("ACCIDENTE", "LESION", "HERIDO")):
        return "accident"
    if _contains_any(question, ("INCIDENTE",)):
        return "incident"
    return "general"


def _build_existing_state_text(state: dict[str, Any]) -> str:
    lines: list[str] = []

    procedure = state.get("procedure", {}) or {}
    stats = state.get("stats", {}) or {}
    latest_case = state.get("latest_case")
    workers = state.get("workers", []) or []
    iperc_jobs = state.get("iperc_jobs", []) or []

    if len(iperc_jobs) > 0:
        lines.append(f"- La matriz IPERC ya contiene {len(iperc_jobs)} puesto(s) utilizables en este módulo.")
    else:
        lines.append("- La matriz IPERC todavía no tiene puestos cargados para habilitar este flujo.")

    if procedure.get("exists"):
        lines.append(
            f"- Ya existe un procedimiento guardado en el sistema: {procedure.get('title')} "
            f"(última actualización: {_format_date(procedure.get('updated_at'))})."
        )
    else:
        lines.append("- Aún no existe un procedimiento guardado dentro del sistema para este módulo.")

    if len(workers) > 0:
        lines.append(f"- Ya existen {len(workers)} trabajador(es) registrados con ficha dentro del sistema.")
    else:
        lines.append("- Todavía no existen trabajadores registrados en este módulo.")

    total_cases = int(stats.get("total_cases", 0) or 0)
    if total_cases > 0:
        lines.append(
            f"- Ya existen {total_cases} registros internos en el sistema "
            f"({stats.get('total_accidents', 0)} accidentes y {stats.get('total_incidents', 0)} incidentes)."
        )
    else:
        lines.append("- Todavía no existen registros internos de incidentes o accidentes dentro del sistema.")

    if latest_case:
        lines.append(
            f"- El caso más reciente es: {latest_case.get('title')} "
            f"con estado {latest_case.get('status')}."
        )

    if state.get("blocking_message"):
        lines.append(f"- Estado actual del módulo: {state.get('blocking_message')}")

    return "\n".join(lines)


def _build_system_actions(question_type: str, state: dict[str, Any]) -> str:
    procedure_exists = bool((state.get("procedure") or {}).get("exists"))
    has_jobs = len(state.get("iperc_jobs", []) or []) > 0
    has_workers = len(state.get("workers", []) or []) > 0

    if not has_jobs:
        return "\n".join(
            [
                "1. Primero entra al módulo IPERC de esta empresa y registra al menos un puesto en la columna 'Puesto'.",
                "2. Vuelve a este módulo; recién ahí se habilitará el registro de trabajadores.",
                "3. Después registra al trabajador con uno de esos puestos IPERC.",
                "4. Solo luego podrás registrar incidentes o accidentes para ese trabajador.",
            ]
        )

    if not has_workers:
        return "\n".join(
            [
                "1. En este mismo módulo, ve al bloque 'Fichas de trabajadores' y registra al primer trabajador.",
                "2. Selecciona obligatoriamente un puesto existente en IPERC.",
                "3. Guarda la ficha del trabajador.",
                "4. Luego usa 'Registrar incidente o accidente' y selecciona ese trabajador.",
            ]
        )

    if question_type in {"worker", "implementation", "normative"}:
        parts = []
        if not procedure_exists:
            parts.append(
                "1. En este mismo módulo, guarda el procedimiento documentado de investigación."
            )
        else:
            parts.append(
                "1. Revisa o actualiza el procedimiento documentado si hace falta."
            )
        parts.append("2. Registra o revisa las fichas de trabajadores vinculadas a puestos IPERC.")
        parts.append("3. Usa el bloque de entrega de EPP para dejar trazabilidad interna por trabajador.")
        parts.append("4. Cuando ocurra un evento, registra el caso seleccionando al trabajador existente.")
        parts.append("5. Revisa el resumen del módulo y los casos para seguimiento.")
        return "\n".join(parts)

    return "\n".join(
        [
            "1. Selecciona un trabajador ya registrado en el sistema.",
            "2. El sistema traerá automáticamente su puesto desde la ficha vinculada a IPERC.",
            "3. Completa la investigación, guarda y da seguimiento al caso.",
            "4. Si corresponde, deja también la trazabilidad de EPP en el mismo módulo.",
        ]
    )


def _render_blocked_answer(state: dict[str, Any]) -> str:
    return "\n\n".join(
        [
            "Lo que aplica en tu caso",
            "Este espacio está diseñado para ayudarte con cumplimiento SST, trabajadores, EPP, investigaciones y uso funcional del sistema, no con programación interna.",
            "Base normativa",
            "El módulo está orientado a resolver dentro del sistema el procedimiento documentado, el registro interno de incidentes o accidentes, la vinculación con puesto de trabajo, la trazabilidad de trabajadores y el seguimiento de EPP.",
            "Lo que ya existe en el sistema",
            _build_existing_state_text(state),
            "Qué hacer ahora en el sistema",
            "Formula la consulta desde el punto de vista SST u operativo. Por ejemplo: qué trabajador registrar, cómo usar puestos IPERC, cómo dejar trazabilidad de EPP o cómo investigar un caso.",
        ]
    )


def answer_company_question(session: Session, company: Company, question: str) -> dict[str, Any]:
    normalized_question = _normalize_text(question)
    state = get_incident_module_state(session, company)
    context = state.get("company", {}) or {}
    question_type = _detect_question_type(normalized_question)

    if _contains_any(normalized_question, TECHNICAL_KEYWORDS):
        return {
            "answer": _render_blocked_answer(state),
            "blocked": True,
            "sources": BASE_SOURCES.copy(),
            "system_state": state,
        }

    intro = (
        f"La empresa {context.get('name')} está registrada con actividad {context.get('activity')}, "
        f"{context.get('workers')} trabajadores y riesgo {context.get('risk')}. "
        f"En tu estructura actual del sistema figura responsable SST tipo {context.get('responsible')} "
        f"y organismo {context.get('organ')}."
    )

    normative = "\n".join(
        [
            "- El Acuerdo Ministerial 196 exige investigar y analizar accidentes, incidentes y enfermedades profesionales, dotar EPP según el riesgo y garantizar vigilancia de la salud de todos los trabajadores.",
            "- El Anexo 1 exige que la gestión use procedimiento documentado, registro interno del evento y soportes relacionados con accidentes e incidentes.",
            "- El mismo Anexo 1 exige una matriz de EPP por puesto de trabajo y un registro de entrega-recepción de EPP a los trabajadores con identificación del trabajador y detalle del equipo.",
            "- El Anexo 3 exige identificar qué puestos requieren EPP y especificar, para cada puesto, los riesgos y el tipo de protección aplicable.",
            "- El Decreto 255 y el Acuerdo 196 exigen mantener respaldos y archivo de la gestión SST.",
        ]
    )

    procedure = state.get("procedure", {}) or {}

    procedure_text = str(procedure.get("generated_summary", "") or "")
    if not procedure_text:
        procedure_text = "El sistema todavía no ha consolidado una base de procedimiento para esta empresa."

    answer = "\n\n".join(
        [
            "Lo que aplica en tu caso",
            intro,
            "Base normativa",
            normative,
            "Procedimiento vigente en el sistema",
            procedure_text,
            "Lo que ya existe en el sistema",
            _build_existing_state_text(state),
            "Qué hacer ahora en el sistema",
            _build_system_actions(question_type, state),
        ]
    )
    
    return {
        "answer": answer,
        "blocked": False,
        "sources": BASE_SOURCES.copy(),
        "system_state": state,
    }