from typing import Literal, TypedDict, Optional

Clasif = Literal["MICRO", "PEQUEÑA", "MEDIANA", "GRANDE"]
Risk = Literal["BAJO", "MEDIO", "ALTO"]

__all__ = [
    "Clasif",
    "Risk",
    "classify_by_workers",
    "decide_responsible",
    "decide_org",
    "normalize_risk",
    "normalize_activity",
    "REQUIRED_BY_ACTIVITY",
    "resolve_required_codes",
]

def normalize_activity(name: Optional[str]) -> str:
    """
    Devuelve una clave canónica para la actividad (mayúsculas, sin tildes problemáticas).
    Claves soportadas por la matriz:
      BANANERA, CAMARONERA, GRANJA PORCINA, GRANJA AVICOLA, MINERIA,
      HOTEL/ALOJAMIENTO, RESTAURANTE, OTROS
    """
    if not name:
        return "OTROS"
    s = str(name).strip().upper()
    # normalizaciones mínimas
    s = s.replace("Á", "A").replace("É", "E").replace("Í", "I").replace("Ó", "O").replace("Ú", "U")
    s = s.replace("AVICOLA", "AVICOLA")  # explícito para evitar variantes
    # mapeos frecuentes
    if s in {"GRANJA AVICOLA", "GRANJA AVÍCOLA"}:
        return "GRANJA AVICOLA"
    if s in {"HOTEL", "ALOJAMIENTO", "HOSPEDAJE"}:
        return "HOTEL/ALOJAMIENTO"
    # catálogo cerrado
    allowed = {
        "BANANERA",
        "CAMARONERA",
        "GRANJA PORCINA",
        "GRANJA AVICOLA",
        "MINERIA",
        "HOTEL/ALOJAMIENTO",
        "RESTAURANTE",
        "OTROS",
    }
    return s if s in allowed else "OTROS"

def normalize_risk(risk: Optional[str]) -> Risk:
    """
    Normaliza el riesgo a BAJO|MEDIO|ALTO, tolerando None o minúsculas.
    """
    if not risk:
        return "MEDIO"
    r = str(risk).strip().upper()
    if r not in ("BAJO", "MEDIO", "ALTO"):
        return "MEDIO"
    return r  # type: ignore[return-value]

def classify_by_workers(n: Optional[int]) -> Clasif:
    """
    Clasificación por Decreto 255 (base): 1–9 (MICRO); 10–49 (PEQUEÑA); 50–99 (MEDIANA); >=100 (GRANDE).
    """
    n = n or 0
    if n <= 9:
        return "MICRO"
    if n <= 49:
        return "PEQUEÑA"
    if n <= 99:
        return "MEDIANA"
    return "GRANDE"

def decide_responsible(clasif: Clasif, risk: Risk) -> Literal["MONITOR", "TÉCNICO"]:
    """
    Regla mínima (afinaremos con tu documento): ALTO -> TÉCNICO; BAJO/MEDIO -> MONITOR.
    """
    return "TÉCNICO" if normalize_risk(risk) == "ALTO" else "MONITOR"

def decide_org(clasif: Clasif) -> Literal["NINGUNO", "DELEGADO", "COMITÉ"]:
    """
    Regla mínima por #trabajadores (afinaremos con documento):
    MICRO -> NINGUNO; PEQUEÑA -> DELEGADO; MEDIANA|GRANDE -> COMITÉ.
    """
    if clasif == "MICRO":
        return "NINGUNO"
    if clasif == "PEQUEÑA":
        return "DELEGADO"
    return "COMITÉ"

# -----------------------------------------------------------------------------
# MATRIZ BASE DE REQUISITOS (códigos) por actividad
# Nota: esta es una base mínima alineada con lo que ya ves en la UI. Puedes
# ampliarla en el tiempo (agregar códigos, condicionales por tamaño/riesgo).
# -----------------------------------------------------------------------------

REQUIRED_BY_ACTIVITY: dict[str, list[str]] = {
    # Agro (Bananera / Camaronera comparten base + HDS/fumigación)
    "BANANERA": [
        "RHS-01",        # Reglamento Interno de Seguridad y Salud
        "PPRL-01",       # Programa de Prevención de Riesgos Laborales
        "CAP-01",        # Plan Anual de Capacitación SST
        "EMG-01",        # Plan de Emergencias y Simulacros
        "INV-AT-01",     # Investigación de Accidentes/Incidentes
        "EPP-01",        # Matriz de EPP y registros de entrega
        "AGRO-PLAG-01",  # Manejo de plaguicidas / HDS
        "AGRO-FUM-01",   # Procedimiento de fumigación
        "ORG-DEL-01",    # Delegado de SST designado (si aplica)
    ],
    "CAMARONERA": [
        "RHS-01","PPRL-01","CAP-01","EMG-01","INV-AT-01","EPP-01",
        "AGRO-PLAG-01","AGRO-FUM-01","ORG-DEL-01",
    ],
    # Granjas
    "GRANJA PORCINA": [
        "RHS-01","PPRL-01","CAP-01","EMG-01","INV-AT-01","EPP-01","ORG-DEL-01",
    ],
    "GRANJA AVICOLA": [
        "RHS-01","PPRL-01","CAP-01","EMG-01","INV-AT-01","EPP-01","ORG-DEL-01",
    ],
    # Industria extractiva
    "MINERIA": [
        "RHS-01","PPRL-01","CAP-01","EMG-01","INV-AT-01","EPP-01","ORG-DEL-01",
        # Aquí normalmente se agregan procedimientos específicos por D.S. minero
    ],
    # Servicios
    "HOTEL/ALOJAMIENTO": [
        "RHS-01","PPRL-01","CAP-01","EMG-01","INV-AT-01","EPP-01","ORG-DEL-01",
    ],
    "RESTAURANTE": [
        "RHS-01","PPRL-01","CAP-01","EMG-01","INV-AT-01","EPP-01","ORG-DEL-01",
    ],
    # Catch-all
    "OTROS": [
        "RHS-01","PPRL-01","CAP-01","EMG-01","INV-AT-01","EPP-01","ORG-DEL-01",
    ],
}

def resolve_required_codes(activity: Optional[str], clasif: Clasif, risk: Risk) -> list[str]:
    """
    Devuelve la lista de códigos requeridos en base a la actividad normalizada.
    En esta versión base no variamos por tamaño/riesgo (se puede extender).
    """
    act = normalize_activity(activity)
    base = REQUIRED_BY_ACTIVITY.get(act, REQUIRED_BY_ACTIVITY["OTROS"]).copy()

    # Extensiones (ejemplo de cómo crecer por tamaño/riesgo si hace falta):
    # if clasif in ("MEDIANA","GRANDE"):
    #     base.append("ORG-COM-01")  # Comité de SST
    # if risk == "ALTO":
    #     base.append("VIG-SALUD-01")  # Vigilancia específica

    return base
