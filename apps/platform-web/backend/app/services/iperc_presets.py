# app/services/iperc_presets.py
# Catálogo mínimo y extensible de presets IPERC por ACTIVIDAD.
# Clave: actividad normalizada (MAYÚSCULAS)
# Estructura de cada proceso (usar SOLO estos campos en defaults):
#   job, task, hazard_group, hazard, event, consequence,
#   nd, ne, nc, requires_work_permit, needs_health_surveillance, needs_env_monitoring

from typing import Dict, List, Optional


PRESETS: Dict[str, Dict] = {
    "BANANERA": {
        "procesos": [
            # Operación / Agro
            {
                "name": "PREPARACIÓN DE TERRENO",
                "defaults": {
                    "job": "Peón agrícola",
                    "task": "Desbroce y nivelación",
                    "hazard_group": "FÍSICOS",
                    "hazard": "Exposición a ruido, vibraciones, polvo y radiación solar",
                    "event": "Uso de machete/desbrozadora, nivelación con equipo ligero, tránsito sobre terreno irregular",
                    "consequence": "Hipoacusia inducida por ruido, TME, irritación respiratoria y golpes/caídas al mismo nivel",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": True,
                },
            },
            {
                "name": "VIVERO / PROPAGACIÓN",
                "defaults": {
                    "job": "Aux. vivero",
                    "task": "Siembra y manejo de plántulas",
                    "hazard_group": "BIOLÓGICOS",
                    "hazard": "Exposición a hongos, bacterias y materia orgánica en descomposición",
                    "event": "Manipulación de sustratos húmedos y residuos vegetales",
                    "consequence": "Dermatitis, rinitis alérgica, micosis superficiales",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            {
                "name": "SIEMBRA / TRASPLANTE",
                "defaults": {
                    "job": "Peón agrícola",
                    "task": "Trasplante",
                    "hazard_group": "ERGONÓMICOS",
                    "hazard": "Sobreesfuerzo por posturas forzadas y manejo manual de cargas ligeras",
                    "event": "Flexión sostenida, movimientos repetitivos de manos y muñecas, traslado de plántulas y herramientas",
                    "consequence": "Trastornos musculoesqueléticos (lumbar, hombro, muñeca)",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            {
                "name": "FERTILIZACIÓN",
                "defaults": {
                    "job": "Fertirriego",
                    "task": "Aplicación de fertilizantes",
                    "hazard_group": "QUÍMICOS",
                    "hazard": "Exposición a fertilizantes (polvos/líquidos cáusticos o irritantes)",
                    "event": "Preparación de mezcla y aplicación manual o con equipo",
                    "consequence": "Irritación piel/ojos y vías respiratorias, intoxicación leve",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": True,
                },
            },
            {
                "name": "RIEGO / FERTIRRIEGO",
                "defaults": {
                    "job": "Operario de riego",
                    "task": "Operación de sistema de riego",
                    "hazard_group": "ELÉCTRICOS",
                    "hazard": "Contacto con partes energizadas de bombas y tableros en ambiente húmedo",
                    "event": "Mantenimiento/maniobra de tableros, conexiones y bombas con humedad",
                    "consequence": "Choque eléctrico y quemaduras",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": True,
                    "needs_health_surveillance": False,
                    "needs_env_monitoring": True,
                },
            },
            {
                "name": "CONTROL DE MALEZAS",
                "defaults": {
                    "job": "Aplicador",
                    "task": "Aplicación de herbicidas / deshierba",
                    "hazard_group": "QUÍMICOS",
                    "hazard": "Exposición a herbicidas por contacto e inhalación",
                    "event": "Mezcla y aplicación con mochila o equipo manual",
                    "consequence": "Irritación dérmica/ocular, intoxicación aguda",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": True,
                },
            },
            {
                "name": "FUMIGACIÓN TERRESTRE",
                "defaults": {
                    "job": "Fumigador",
                    "task": "Aplicación de plaguicidas",
                    "hazard_group": "QUÍMICOS",
                    "hazard": "Exposición a plaguicidas",
                    "event": "Contacto/inhalación durante mezcla y aplicación",
                    "consequence": "Intoxicación aguda y daño sistémico",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": True,
                },
            },
            {
                "name": "FUMIGACIÓN AÉREA (SI APLICA)",
                "defaults": {
                    "job": "Supervisor",
                    "task": "Vigilancia y control",
                    "hazard_group": "QUÍMICOS",
                    "hazard": "Exposición por deriva de aplicación aérea",
                    "event": "Permanencia en campo durante operaciones aéreas, contacto con residuos",
                    "consequence": "Intoxicación aguda, irritación respiratoria/ocular",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": True,
                },
            },
            {
                "name": "DESHOJE / DESCHANCLE / DESHIJE",
                "defaults": {
                    "job": "Deshojador",
                    "task": "Corte de hojas",
                    "hazard_group": "ERGONÓMICOS",
                    "hazard": "Posturas forzadas y agarres sostenidos durante corte manual",
                    "event": "Corte continuo por encima del hombro y manipulación repetitiva",
                    "consequence": "TME en hombro, codo y muñeca",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            {
                "name": "CORTE / DESFLORILLADO",
                "defaults": {
                    "job": "Cortador",
                    "task": "Corte de racimos",
                    "hazard_group": "ERGONÓMICOS",
                    "hazard": "Sobreesfuerzo y manipulación manual de cargas pesadas",
                    "event": "Sujeción y traslado de racimos, uso de herramientas de corte",
                    "consequence": "TME lumbar y de miembros superiores",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            {
                "name": "TRANSPORTE INTERNO / TRASLADO",
                "defaults": {
                    "job": "Cosechador",
                    "task": "Traslado de racimos",
                    "hazard_group": "ERGONÓMICOS",
                    "hazard": "Manipulación manual de cargas y empujes/arrastres",
                    "event": "Transporte de racimos por caminos internos, uso de carretillas o cables aéreos",
                    "consequence": "TME y caídas al mismo nivel",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            {
                "name": "ACOPIO / LAVADO DE RACIMOS",
                "defaults": {
                    "job": "Acopiador",
                    "task": "Lavado y desmane",
                    "hazard_group": "FÍSICOS",
                    "hazard": "Exposición a humedad, superficies resbalosas y ruido de equipos",
                    "event": "Lavado continuo, manejo de ganchos y mesas húmedas",
                    "consequence": "Caídas al mismo nivel, dermatitis irritativa y hipoacusia",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": True,
                },
            },
            # Empaque y despacho
            {
                "name": "SELECCIÓN / CLASIFICACIÓN",
                "defaults": {
                    "job": "Seleccionadora",
                    "task": "Clasificación de fruta",
                    "hazard_group": "ERGONÓMICOS",
                    "hazard": "Movimientos repetitivos y posturas estáticas prolongadas",
                    "event": "Selección en mesa de trabajo con ciclos cortos",
                    "consequence": "TME en cuello-hombro-muñeca y fatiga",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            {
                "name": "EMPACADO",
                "defaults": {
                    "job": "Operario de empacado",
                    "task": "Embalaje",
                    "hazard_group": "ERGONÓMICOS",
                    "hazard": "Repetitividad y manipulación de bultos",
                    "event": "Armado de cajas, llenado y cierre en línea",
                    "consequence": "TME de miembro superior y lumbar",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            {
                "name": "PALETIZADO",
                "defaults": {
                    "job": "Paletizador",
                    "task": "Formación de pallets",
                    "hazard_group": "ERGONÓMICOS",
                    "hazard": "Levantamiento y apilamiento de cargas",
                    "event": "Acomodo manual de cajas sobre pallets",
                    "consequence": "TME lumbar y hombro",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            {
                "name": "CÁMARA FRÍA (SI APLICA)",
                "defaults": {
                    "job": "Operario de frío",
                    "task": "Ingreso/egreso de pallets",
                    "hazard_group": "FRÍO",
                    "hazard": "Exposición a bajas temperaturas",
                    "event": "Operación y permanencia intermitente en cámara fría",
                    "consequence": "Hipotermia leve, lesiones por frío y agravamiento de afecciones respiratorias",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": True,
                },
            },
            {
                "name": "CARGA Y DESPACHO",
                "defaults": {
                    "job": "Estibador",
                    "task": "Carga a camión/cont.",
                    "hazard_group": "ERGONÓMICOS",
                    "hazard": "Levantamiento y transporte manual de cargas",
                    "event": "Estiba y desestiba de bultos, uso de fajas y carros",
                    "consequence": "TME lumbar, golpes y caídas del mismo nivel",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            {
                "name": "TRANSPORTE / LOGÍSTICA EXTERNA",
                "defaults": {
                    "job": "Chofer",
                    "task": "Traslado a destino",
                    "hazard_group": "SEGURIDAD VIAL",
                    "hazard": "Riesgo de siniestro vial por conducción prolongada y condiciones de ruta",
                    "event": "Conducción de camión/tractomula en vías públicas",
                    "consequence": "Lesiones graves o fatales por colisiones",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            # Apoyo / infraestructura
            {
                "name": "MANTENIMIENTO / TALLER",
                "defaults": {
                    "job": "Técnico",
                    "task": "Mantenimiento de equipos",
                    "hazard_group": "MECÁNICOS",
                    "hazard": "Atrapamientos, cortes y golpes por herramientas y equipos en movimiento",
                    "event": "Ajustes, reparaciones y pruebas de maquinaria",
                    "consequence": "Laceraciones, contusiones y amputaciones",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": True,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            {
                "name": "LIMPIEZA Y DESINFECCIÓN",
                "defaults": {
                    "job": "Limpieza",
                    "task": "Limpieza general",
                    "hazard_group": "QUÍMICOS",
                    "hazard": "Exposición a detergentes, desinfectantes y vapores",
                    "event": "Preparación de soluciones y aplicación por rociado/frotado",
                    "consequence": "Dermatitis y/o irritación ocular/respiratoria",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": True,
                },
            },
            {
                "name": "GESTIÓN DE RESIDUOS / ENVASES",
                "defaults": {
                    "job": "Auxiliar",
                    "task": "Manejo y disposición",
                    "hazard_group": "QUÍMICOS",
                    "hazard": "Exposición a residuos peligrosos y envases contaminados",
                    "event": "Recolección, segregación, triple lavado y almacenamiento temporal",
                    "consequence": "Irritación dérmica/respiratoria y riesgo de intoxicación",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": True,
                },
            },
            {
                "name": "BODEGA / ALMACÉN (INSUMOS)",
                "defaults": {
                    "job": "Bodeguero",
                    "task": "Recepción y almacenamiento",
                    "hazard_group": "QUÍMICOS",
                    "hazard": "Derrames y vapores de insumos químicos",
                    "event": "Recepción, trasiego y estiba de productos químicos",
                    "consequence": "Irritación y/o intoxicación por exposición incidental",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": True,
                },
            },
            {
                "name": "LABORATORIO (SI APLICA)",
                "defaults": {
                    "job": "Analista",
                    "task": "Análisis de muestras",
                    "hazard_group": "QUÍMICOS",
                    "hazard": "Manipulación de reactivos corrosivos/irritantes",
                    "event": "Preparación de reactivos, titulación y calentamiento controlado",
                    "consequence": "Quemaduras químicas, irritación ocular/respiratoria",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": True,
                },
            },
            # Administrativo / gestión
            {
                "name": "ADMINISTRACIÓN / OFICINA",
                "defaults": {
                    "job": "Administrativo",
                    "task": "Gestión documental",
                    "hazard_group": "ERGONÓMICOS",
                    "hazard": "Posturas estáticas prolongadas y uso de pantalla",
                    "event": "Trabajo sedentario en puesto de oficina",
                    "consequence": "TME cervical/lumbar y fatiga visual",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
            {
                "name": "SEGURIDAD Y SALUD / SUPERVISIÓN",
                "defaults": {
                    "job": "SST",
                    "task": "Inspecciones / capacitaciones",
                    "hazard_group": "PSICOSOCIALES",
                    "hazard": "Carga mental por múltiples frentes y exposición a eventos críticos",
                    "event": "Planificación, inspecciones en campo y coordinación con áreas",
                    "consequence": "Estrés laboral, ansiedad y fatiga",
                    "nd": None, "ne": None, "nc": None,
                    "requires_work_permit": False,
                    "needs_health_surveillance": True,
                    "needs_env_monitoring": False,
                },
            },
        ],
        "bands": {
            "np": {"MA": [24, 40], "A": [10, 20], "M": [6, 8], "B": [2, 4]},
            "nr": {"I": [600, 4000], "II": [150, 500], "III": [40, 120], "IV": [20, 20]},
        },
        "colors": {"I": "#e74c3c", "II": "#e67e22", "III": "#f1c40f", "IV": "#2ecc71"},
    },
    # Cuando quieras, añade "CAMARONERA": {...}, etc.
}


def get_activity_presets(activity_norm: str) -> Dict:
    """Devuelve el bloque de presets por actividad (o vacío)."""
    return PRESETS.get(activity_norm.upper(), {"procesos": []})


def list_process_names(activity_norm: str) -> List[str]:
    blk = get_activity_presets(activity_norm)
    return [p["name"] for p in blk.get("procesos", [])]


def find_process(activity_norm: str, process_name: str) -> Optional[Dict]:
    blk = get_activity_presets(activity_norm)
    for p in blk.get("procesos", []):
        if p["name"].upper() == (process_name or "").upper():
            return p
    return None
