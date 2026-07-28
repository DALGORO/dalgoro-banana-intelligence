# backend/app/services/sst_requirements.py
from typing import List, Dict, Any
from app.services.sst_rules import (
    classify_by_workers,
    normalize_activity,
    normalize_risk,
)

Requirement = Dict[str, Any]

# Códigos que tienen plantilla generable en el sistema (iremos ampliando)
TEMPLATABLE_CODES = {
    # Base que ya ves en pantalla
    "RHS-01",        # Reglamento
    "PPRL-01",       # Programa de prevención (SGSST)
    "CAP-01",        # Plan anual de capacitación
    "EMG-01",        # Plan de emergencias y simulacros
    "INV-AT-01",     # Investigación de accidentes/incidentes
    "EPP-01",        # Matriz de EPP y entregas
    "AGRO-PLAG-01",  # Manejo de plaguicidas / HDS
    "AGRO-FUM-01",   # Procedimiento de fumigación
    "ORG-DEL-01",    # Delegado SST designado
    "ORG-COM-01",    # Comité Paritario SST
    
    # Adicionales que te recomendé
    "ORG-MON-SUT-01",  # Registro SUT Monitor SST (≤10)
    "ORG-TEC-SUT-01",  # Técnico/Servicio SST en SUT (>10 o por riesgo)
    "VIG-SAL-01",      # Programa de vigilancia de la salud
    "MON-AMB-01",      # Plan/Reportes de monitoreo ambiental (higiene)
    "PSICO-01",        # Programa de riesgos psicosociales
    "ACTA-APR-RHS-01",
}

# Orden sugerido para generación inicial del SGSST (prioridad normativa)
GENERATION_PRIORITY = [
    {"order": 1, "code": "ORG-DEL-01", "message": "Primero se debe designar al Delegado de SST. Sin esta figura, no se puede aprobar ni registrar documentos en el SUT."},
    {"order": 1, "code": "ORG-COM-01", "message": "Primero se debe conformar el Comité Paritario de SST. Es obligatorio para empresas de 50 o más trabajadores."},
    {"order": 2, "code": "RHS-01", "message": "El Reglamento Interno de SST establece las normas básicas del sistema de gestión y debe aprobarse internamente."},
    {"order": 2, "code": "IPERC-01", "message": "Completa la matriz IPERC para que el resto de documentos (capacitación, vigilancia, EPP, emergencias, permisos) se generen con datos reales."},
    {"order": 3, "code": "ACTA-APR-RHS-01", "message": "El acta de aprobación del Reglamento es requisito previo para su registro ante el Ministerio del Trabajo."},
    {"order": 4, "code": "PPRL-01", "message": "El Programa de Prevención de Riesgos Laborales define la estructura del SGSST y debe generarse tras aprobar el Reglamento."},
    {"order": 5, "code": "CAP-01", "message": "El Plan Anual de Capacitación es obligatorio para todo el personal y debe registrarse dentro del primer año de implementación."},
    {"order": 6, "code": "EMG-01", "message": "El Plan de Emergencias es esencial para la prevención y respuesta ante eventos críticos."},
    {"order": 7, "code": "EPP-01", "message": "La Matriz y Registro de EPP demuestran la entrega de equipos de protección personal al personal operativo."},
    {"order": 8, "code": "AGRO-PLAG-01", "message": "El manejo de plaguicidas y HDS es obligatorio por exposición química y control de BPA."},
    {"order": 9, "code": "INV-AT-01", "message": "Debe implementarse para registrar e investigar accidentes o incidentes laborales."},
    {"order": 10, "code": "VIG-SAL-01", "message": "Establece el control médico ocupacional de los trabajadores expuestos a agentes físicos o químicos."},
    {"order": 11, "code": "MON-AMB-01", "message": "Permite el control de factores ambientales como ruido, iluminación o contaminantes químicos."},
    {"order": 12, "code": "PSICO-01", "message": "Evalúa y gestiona los riesgos psicosociales conforme a la guía oficial del MSP/MT."},
    {"order": 13, "code": "ORG-MON-SUT-01", "message": "Se registra el Delegado de SST en el SUT para formalizar el sistema ante el Ministerio."},
    {"order": 13, "code": "ORG-TEC-SUT-01", "message": "Se registra el Técnico/Servicio de SST en el SUT para completar la formalización ante el Ministerio."},
]

# Requisitos base (ISO 45001 + Decreto 255) — comunes a toda actividad
COMMON_BASE: List[Requirement] = [
    {"code": "RHS-01",   "name": "Reglamento Interno de Seguridad y Salud",      "periodicity": "según cambios", "legal": "Decreto 255 Art. 14; Acuerdo Min. 196 Arts. 18–22 (SUT); ISO 45001 5.2"},
    {"code": "ACTA-APR-RHS-01", "name": "Acta de Aprobación del Reglamento de SST", "periodicity": "según evento", "legal": "Acuerdo Min. 196 (SUT); Decreto 255 Arts. 18–22"},
    {"code": "PPRL-01",  "name": "Programa de Prevención de Riesgos Laborales",  "periodicity": "anual",         "legal": "Decreto 255 Arts. 10–11; ISO 45001 6.1 y 6.2"},
    {"code": "ORG-01",   "name": "Delegado/Comité SST (según tamaño)",           "periodicity": "vigente",       "legal": "Decreto 255 Arts. 18–22; Acuerdo Min. 196 (registro en SUT)"},
    {"code": "CAP-01",   "name": "Plan Anual de Capacitación SST",               "periodicity": "anual",         "legal": "Decreto 255 Art. 16; ISO 45001 7.2"},
    {"code": "EMG-01",   "name": "Plan de Emergencias y Simulacros",             "periodicity": "anual",         "legal": "Decreto 255 Art. 13; ISO 45001 8.2"},
    {"code": "INV-AT-01","name": "Investigación de Accidentes/Incidentes",       "periodicity": "según evento",  "legal": "ISO 45001 10.2"},
    {"code": "EPP-01",   "name": "Matriz de EPP y registros de entrega",         "periodicity": "permanente",    "legal": "ISO 45001 8.1.2"},
    {"code": "IPERC-01", "name": "Matriz IPERC por proceso y puesto", "periodicity": "según cambios", "legal": "Decreto 255 (identificación y evaluación de riesgos); ISO 45001 6.1"},
]

# Adiciones por riesgo (ej. permisos críticos si ALTO)
RISK_ADDONS = {
    "BAJO": [
        {"code": "PSICO-01", "name": "Programa de riesgos psicosociales (diagnóstico, plan, seguimiento)", "periodicity": "anual", "legal": "Guía de riesgos psicosociales (MSP/MT); ISO 45001 6.1"},
    ],
    "MEDIO": [
        {"code": "VIG-SAL-01", "name": "Programa de vigilancia de la salud (exámenes ocupacionales)", "periodicity": "anual", "legal": "Decreto 255; ISO 45001 9.1"},
        {"code": "MON-AMB-01", "name": "Monitoreos higiénicos (ruido, iluminación, químicos) según IPERC", "periodicity": "según riesgo", "legal": "Decreto 255; ISO 45001 6.1.2 y 9.1"},
        {"code": "PSICO-01",   "name": "Programa de riesgos psicosociales (diagnóstico, plan, seguimiento)", "periodicity": "anual", "legal": "Guía de riesgos psicosociales (MSP/MT); ISO 45001 6.1"},
    ],
    "ALTO": [
        {"code": "VIG-SAL-01", "name": "Programa de vigilancia de la salud (exámenes ocupacionales)", "periodicity": "anual", "legal": "Decreto 255; ISO 45001 9.1"},
        {"code": "MON-AMB-01", "name": "Monitoreos higiénicos (ruido, iluminación, químicos) según IPERC", "periodicity": "según riesgo", "legal": "Decreto 255; ISO 45001 6.1.2 y 9.1"},
        {"code": "PSICO-01",   "name": "Programa de riesgos psicosociales (diagnóstico, plan, seguimiento)", "periodicity": "anual", "legal": "Guía de riesgos psicosociales (MSP/MT); ISO 45001 6.1"},
    ],
}

# Adiciones específicas por actividad (catálogo solicitado)
ACTIVITY_ADDONS = {
    "BANANERA": [
    {"code": "IPERC-01", "name": "Matriz IPERC por proceso y puesto", "periodicity": "según cambios", "legal": "Decreto 255 (identificación y evaluación de riesgos); ISO 45001 6.1"},
    {"code": "AGRO-PLAG-01", "name": "Manejo de plaguicidas / HDS", "periodicity": "permanente", "legal": "Ley de Plaguicidas (HDS/almacenamiento/uso); BPA; ISO 45001 8.1.2"},
    {"code": "AGRO-FUM-01",  "name": "Procedimiento de fumigación", "periodicity": "anual",      "legal": "Ley de Plaguicidas; BPA"},
    {"code": "ORG-MON-SUT-01", "name": "Registro en SUT del Monitor de SST", "periodicity": "vigente", "legal": "Acuerdo Min. 196 (SUT); D. 255 Arts. 18–22"},
    {"code": "ORG-TEC-SUT-01", "name": "Registro en SUT del Técnico/Servicio de SST", "periodicity": "vigente", "legal": "Acuerdo Min. 196 (SUT); D. 255 Arts. 18–22"},
],

    "CAMARONERA": [
        {"code": "BIOSEG-CR-01", "name": "Plan de Bioseguridad Camaronera", "periodicity": "anual", "legal": "BPM/BPA sector"},
    ],
    "GRANJA PORCINA": [
        {"code": "BIOSEG-POR-01","name": "Plan de Bioseguridad Porcina", "periodicity": "anual", "legal": "Sector agropecuario"},
    ],
    "GRANJA AVICOLA": [
        {"code": "BIOSEG-AVI-01","name": "Plan de Bioseguridad Avícola", "periodicity": "anual", "legal": "Sector agropecuario"},
    ],
    "MINERIA": [
        {"code": "MIN-SEG-01",   "name": "Procedimientos críticos (voladura, geotecnia, etc.)", "periodicity": "permanente", "legal": "Sector minero"},
    ],
    "HOTEL/ALOJAMIENTO": [
        {"code": "TUR-EMG-01",   "name": "Plan de Emergencias Hotelero", "periodicity": "anual", "legal": "Turismo/Bomberos/ISO"},
    ],
    "RESTAURANTE": [
        {"code": "BPM-COC-01",   "name": "BPM en cocina / POES", "periodicity": "anual", "legal": "ARCSA/BPM"},
    ],
    "OTROS": [],
}

# NUEVO: requerimientos adicionales por tamaño de empresa
SIZE_ADDONS = {
    "MICRO": [],
    "PEQUEÑA": [],
    "MEDIANA": [
        {
            "code": "AUD-INT-01",
            "name": "Auditoría interna del SGSST",
            "periodicity": "anual",
            "legal": "ISO 45001 9.2",
        },
        {
            "code": "BRI-EMG-01",
            "name": "Brigada de emergencias conformada y entrenada",
            "periodicity": "anual",
            "legal": "ISO 45001 8.2; Decreto 255 (emergencias)",
        },
        {
            "code": "CTR-EXT-01",
            "name": "Gestión de contratistas y subcontratistas",
            "periodicity": "permanente",
            "legal": "ISO 45001 8.1.4",
        },
    ],
    "GRANDE": [
        {
            "code": "AUD-INT-01",
            "name": "Auditoría interna del SGSST",
            "periodicity": "anual",
            "legal": "ISO 45001 9.2",
        },
        {
            "code": "BRI-EMG-01",
            "name": "Brigada de emergencias conformada y entrenada",
            "periodicity": "anual",
            "legal": "ISO 45001 8.2; Decreto 255 (emergencias)",
        },
        {
            "code": "CTR-EXT-01",
            "name": "Gestión de contratistas y subcontratistas",
            "periodicity": "permanente",
            "legal": "ISO 45001 8.1.4",
        },
    ],
}

def build_requirements(actividad: str, trabajadores: int, riesgo: str) -> dict:
    clasif = classify_by_workers(trabajadores)  # MICRO/PEQUEÑA/MEDIANA/GRANDE
    act = normalize_activity(actividad)
    risk = normalize_risk(riesgo)

    items: List[Requirement] = []
    items.extend(COMMON_BASE)
    items.extend(RISK_ADDONS.get(risk, []))
    items.extend(SIZE_ADDONS.get(clasif, []))      # ← NUEVO: diferencia por tamaño
    items.extend(ACTIVITY_ADDONS.get(act, []))

    items = [i for i in items if i["code"] != "ORG-01"]
    if clasif in ("MICRO", "PEQUEÑA"):
        items.append({
            "code": "ORG-DEL-01",
            "name": "Delegado de SST designado",
            "periodicity": "vigente",
            "legal": "Decreto 255 Arts. 18–22; Acuerdo Min. 196 (SUT)",
        })
    else:
        items.append({
            "code": "ORG-COM-01",
            "name": "Comité Paritario de SST",
            "periodicity": "vigente",
            "legal": "Decreto 255 Arts. 18–22; Acuerdo Min. 196 (SUT)",
        })
    
    # SUT: mostrar solo el que aplica por tamaño
    if clasif in ("MICRO", "PEQUEÑA"):
        items = [it for it in items if it["code"] != "ORG-TEC-SUT-01"]
    else:
        items = [it for it in items if it["code"] != "ORG-MON-SUT-01"]

    # Deduplicar por code (último gana)
    dedup: Dict[str, Requirement] = {}
    for it in items:
        dedup[it["code"]] = it
    items = list(dedup.values())

    # Enriquecer con prioridad (orden y mensaje) — AQUÍ SÍ HAY 'it'
    for it in items:
        p = next((p for p in GENERATION_PRIORITY if p["code"] == it["code"]), None)
        if p:
            it["priority_order"] = p["order"]
            it["priority_message"] = p["message"]

    # Ordenar por prioridad (los que tienen orden primero)
    items.sort(
        key=lambda x: (
            x.get("priority_order") is None,
            x.get("priority_order", 10**9),
            x.get("code", ""),
        )
    )

    # Marcar si hay plantilla generable
    for it in items:
        it["can_generate"] = it.get("code") in TEMPLATABLE_CODES
        if it["can_generate"]:
            it["template_code"] = it["code"]

    return {"clasificacion": clasif, "riesgo": risk, "actividad": act, "items": items}
