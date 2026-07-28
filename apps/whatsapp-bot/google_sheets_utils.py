import gspread
import os
import json
from oauth2client.service_account import ServiceAccountCredentials
from config import Config
from time_utils import ahora_txt, ahora_id

SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

CONTACTOS_HEADERS = [
    "Telefono", "Nombre", "Origen", "Actividad", "Motivo", "Ultima_Etapa",
    "Estado_Comercial", "Ultima_Interaccion", "Observacion"
]

MENSAJES_HEADERS = [
    "Telefono", "Mensaje", "Tipo", "Canal", "Fecha_Hora"
]

CITAS_HEADERS = [
    "ID_Cita", "Telefono", "Nombre", "Origen", "Actividad", "Motivo",
    "Tipo_Atencion", "Finca_Proyecto", "Ubicacion", "Fecha", "Hora",
    "Estado", "Mensaje_Original", "Fecha_Registro", "Fecha_Ultima_Actualizacion"
]

SIN_CIERRE_HEADERS = [
    "Telefono", "Nombre", "Origen", "Actividad", "Motivo", "Ultima_Etapa",
    "Ultimo_Mensaje", "Accion_Sugerida", "Fecha_Hora"
]

ESTADOS_HEADERS = [
    "Telefono", "Estado_JSON", "Fecha_Ultima_Actualizacion"
]


def obtener_credenciales():
    """
    Lee la credencial de Google desde la variable GOOGLE_CREDENTIALS_JSON.
    En Render debe estar como variable de entorno.
    En local puede ser cargada por un script auxiliar antes de importar este módulo.
    """
    cred_json = Config.GOOGLE_CREDENTIALS_JSON or os.getenv("GOOGLE_CREDENTIALS_JSON")

    if not cred_json:
        raise ValueError("La variable de entorno GOOGLE_CREDENTIALS_JSON no está definida.")

    cred_dict = json.loads(cred_json)
    return ServiceAccountCredentials.from_json_keyfile_dict(cred_dict, SCOPE)


class SheetsManager:
    def __init__(self):
        creds = obtener_credenciales()
        self.cliente = gspread.authorize(creds)
        self.libro = self.cliente.open_by_key(Config.GOOGLE_SHEET_ID)

        self.contactos = self._obtener_o_crear_hoja("Contactos", CONTACTOS_HEADERS)
        self.mensajes = self._obtener_o_crear_hoja("Mensajes", MENSAJES_HEADERS)
        self.citas = self._obtener_o_crear_hoja("Citas", CITAS_HEADERS)
        self.sin_cierre = self._obtener_o_crear_hoja("Conversaciones_Sin_Cierre", SIN_CIERRE_HEADERS)
        self.estados = self._obtener_o_crear_hoja("Estados_Conversacion", ESTADOS_HEADERS)

    # ======================================================
    # UTILIDADES GENERALES
    # ======================================================

    def _normalizar_telefono(self, telefono):
        """
        Limpia y estandariza números para comparar registros.
        Acepta:
        - 593984770663
        - +593984770663
        - 593984770663@c.us
        - 0984770663
        """
        telefono = str(telefono or "").strip()
        telefono = telefono.replace("@c.us", "")
        telefono = telefono.replace("+", "")
        telefono = telefono.replace(" ", "")
        telefono = telefono.replace("-", "")
        telefono = telefono.replace("(", "")
        telefono = telefono.replace(")", "")

        solo_digitos = "".join(c for c in telefono if c.isdigit())

        # Ecuador: si se ingresa como 09xxxxxxxx, convertir a 5939xxxxxxxx.
        if solo_digitos.startswith("0") and len(solo_digitos) == 10:
            solo_digitos = "593" + solo_digitos[1:]

        return solo_digitos

    def _obtener_o_crear_hoja(self, nombre, encabezados):
        try:
            hoja = self.libro.worksheet(nombre)
        except gspread.exceptions.WorksheetNotFound:
            hoja = self.libro.add_worksheet(
                title=nombre,
                rows=1000,
                cols=max(20, len(encabezados))
            )
            hoja.append_row(encabezados)
            return hoja

        self._asegurar_encabezados(hoja, encabezados)
        return hoja

    def _asegurar_encabezados(self, hoja, encabezados):
        actuales = hoja.row_values(1)

        if not actuales:
            hoja.append_row(encabezados)
            return

        nuevos = list(actuales)
        cambio = False

        for encabezado in encabezados:
            if encabezado not in nuevos:
                nuevos.append(encabezado)
                cambio = True

        if cambio:
            hoja.update("1:1", [nuevos])

    def _append_dict(self, hoja, encabezados, datos):
        self._asegurar_encabezados(hoja, encabezados)
        encabezados_reales = hoja.row_values(1)
        fila = [datos.get(h, "") for h in encabezados_reales]
        hoja.append_row(fila)

    def _buscar_fila_por_telefono(self, hoja, telefono):
        telefono_objetivo = self._normalizar_telefono(telefono)
        registros = hoja.get_all_records()

        for idx, registro in enumerate(registros, start=2):
            telefono_registro = (
                registro.get("Telefono")
                or registro.get("Teléfono")
                or registro.get("telefono")
                or ""
            )
            telefono_registro = self._normalizar_telefono(telefono_registro)

            if telefono_registro == telefono_objetivo:
                return idx, registro

        return None, None

    def _eliminar_filas_por_telefono(self, hoja, telefono):
        """
        Elimina todas las filas de una hoja que correspondan a un teléfono.
        No elimina encabezados.
        """
        telefono_objetivo = self._normalizar_telefono(telefono)

        if not telefono_objetivo:
            return 0

        registros = hoja.get_all_records()
        filas_a_eliminar = []

        for idx, registro in enumerate(registros, start=2):
            telefono_registro = (
                registro.get("Telefono")
                or registro.get("Teléfono")
                or registro.get("telefono")
                or ""
            )
            telefono_registro = self._normalizar_telefono(telefono_registro)

            if telefono_registro == telefono_objetivo:
                filas_a_eliminar.append(idx)

        for fila in sorted(filas_a_eliminar, reverse=True):
            hoja.delete_rows(fila)

        return len(filas_a_eliminar)

    # ======================================================
    # CONTACTOS Y MENSAJES
    # ======================================================

    def update_contact(self, telefono, datos=None):
        datos = datos or {}
        telefono = self._normalizar_telefono(telefono)
        self._asegurar_encabezados(self.contactos, CONTACTOS_HEADERS)
        encabezados = self.contactos.row_values(1)

        fila_existente, _ = self._buscar_fila_por_telefono(self.contactos, telefono)

        base = {
            "Telefono": telefono,
            "Nombre": datos.get("nombre", ""),
            "Origen": datos.get("origen", ""),
            "Actividad": datos.get("actividad", ""),
            "Motivo": datos.get("motivo", ""),
            "Ultima_Etapa": datos.get("etapa", ""),
            "Estado_Comercial": datos.get("estado_comercial", ""),
            "Ultima_Interaccion": ahora_txt(),
            "Observacion": datos.get("observacion", "")
        }

        if fila_existente:
            for campo, valor in base.items():
                if campo in encabezados and valor != "":
                    col = encabezados.index(campo) + 1
                    self.contactos.update_cell(fila_existente, col, valor)
        else:
            self._append_dict(self.contactos, CONTACTOS_HEADERS, base)

    def log_message(self, telefono, mensaje, tipo, canal="WhatsApp"):
        try:
            self._append_dict(self.mensajes, MENSAJES_HEADERS, {
                "Telefono": self._normalizar_telefono(telefono),
                "Mensaje": mensaje,
                "Tipo": tipo,
                "Canal": canal,
                "Fecha_Hora": ahora_txt()
            })
            return True
        except Exception as e:
            print("Error al registrar mensaje:", e)
            return False

    # ======================================================
    # CITAS / LLAMADAS / COORDINACIONES
    # ======================================================

    def registrar_cita(self, datos):
        try:
            datos = dict(datos)
            datos["Telefono"] = self._normalizar_telefono(datos.get("Telefono", ""))

            if not datos.get("ID_Cita"):
                datos["ID_Cita"] = f"CITA-{ahora_id()}-{datos.get('Telefono', '')}"

            datos.setdefault("Fecha_Registro", ahora_txt())
            datos.setdefault("Fecha_Ultima_Actualizacion", ahora_txt())
            datos.setdefault("Estado", "Agendada")

            self._append_dict(self.citas, CITAS_HEADERS, datos)
            return datos["ID_Cita"]
        except Exception as e:
            print("Error al registrar cita:", e)
            return None

    def _buscar_ultima_cita_activa(self, telefono, id_cita=None):
        telefono = self._normalizar_telefono(telefono)
        registros = self.citas.get_all_records()
        encontrada = None

        for idx, registro in enumerate(registros, start=2):
            tel = self._normalizar_telefono(registro.get("Telefono", ""))

            if tel != telefono:
                continue

            if id_cita and registro.get("ID_Cita") != id_cita:
                continue

            if str(registro.get("Estado", "")).lower() == "cancelada":
                continue

            encontrada = (idx, registro)

        return encontrada if encontrada else (None, None)

    def actualizar_ultima_cita(self, datos):
        try:
            datos = dict(datos)
            telefono = self._normalizar_telefono(datos.get("Telefono", ""))
            datos["Telefono"] = telefono
            id_cita = datos.get("ID_Cita") or None

            fila, registro = self._buscar_ultima_cita_activa(telefono, id_cita)

            if not fila:
                return self.registrar_cita(datos)

            encabezados = self.citas.row_values(1)
            datos_actualizar = dict(datos)
            datos_actualizar["Fecha_Ultima_Actualizacion"] = ahora_txt()

            for campo, valor in datos_actualizar.items():
                if campo in encabezados and valor != "":
                    col = encabezados.index(campo) + 1
                    self.citas.update_cell(fila, col, valor)

            return registro.get("ID_Cita") or datos.get("ID_Cita")
        except Exception as e:
            print("Error al actualizar cita:", e)
            return None

    def cancelar_ultima_cita(self, datos):
        datos = dict(datos)
        datos["Estado"] = "Cancelada"
        return self.actualizar_ultima_cita(datos)

    # ======================================================
    # CONVERSACIONES SIN CIERRE
    # ======================================================

    def registrar_sin_cierre(self, datos):
        try:
            datos = dict(datos)
            datos["Telefono"] = self._normalizar_telefono(datos.get("Telefono", ""))
            datos.setdefault("Fecha_Hora", ahora_txt())
            self._append_dict(self.sin_cierre, SIN_CIERRE_HEADERS, datos)
            return True
        except Exception as e:
            print("Error al registrar conversación sin cierre:", e)
            return False

    # ======================================================
    # ESTADO DE CONVERSACIÓN
    # ======================================================

    def obtener_estado_conversacion(self, telefono):
        try:
            telefono = self._normalizar_telefono(telefono)
            fila, registro = self._buscar_fila_por_telefono(self.estados, telefono)

            if not fila or not registro.get("Estado_JSON"):
                return None

            return json.loads(registro.get("Estado_JSON"))
        except Exception as e:
            print("Error al obtener estado de conversación:", e)
            return None

    def guardar_estado_conversacion(self, telefono, estado):
        try:
            telefono = self._normalizar_telefono(telefono)
            self._asegurar_encabezados(self.estados, ESTADOS_HEADERS)
            encabezados = self.estados.row_values(1)
            fila, _ = self._buscar_fila_por_telefono(self.estados, telefono)

            estado_json = json.dumps(estado, ensure_ascii=False)
            base = {
                "Telefono": telefono,
                "Estado_JSON": estado_json,
                "Fecha_Ultima_Actualizacion": ahora_txt()
            }

            if fila:
                for campo, valor in base.items():
                    if campo in encabezados:
                        col = encabezados.index(campo) + 1
                        self.estados.update_cell(fila, col, valor)
            else:
                self._append_dict(self.estados, ESTADOS_HEADERS, base)

            return True
        except Exception as e:
            print("Error al guardar estado de conversación:", e)
            return False

    # ======================================================
    # REINICIO / LIMPIEZA PARA PRUEBAS
    # ======================================================

    def reiniciar_numero(
        self,
        telefono,
        borrar_contacto=True,
        borrar_mensajes=True,
        borrar_citas=True,
        borrar_sin_cierre=True,
        borrar_estado=True
    ):
        """
        Reinicia la conversación de un número específico.
        Se usa para pruebas controladas sin afectar otros clientes.
        """
        telefono_limpio = self._normalizar_telefono(telefono)

        resultado = {
            "telefono": telefono_limpio,
            "Contactos": 0,
            "Mensajes": 0,
            "Citas": 0,
            "Conversaciones_Sin_Cierre": 0,
            "Estados_Conversacion": 0,
        }

        if not telefono_limpio:
            print("❌ No se recibió un número válido para reiniciar.")
            return resultado

        if borrar_contacto:
            resultado["Contactos"] = self._eliminar_filas_por_telefono(self.contactos, telefono_limpio)

        if borrar_mensajes:
            resultado["Mensajes"] = self._eliminar_filas_por_telefono(self.mensajes, telefono_limpio)

        if borrar_citas:
            resultado["Citas"] = self._eliminar_filas_por_telefono(self.citas, telefono_limpio)

        if borrar_sin_cierre:
            resultado["Conversaciones_Sin_Cierre"] = self._eliminar_filas_por_telefono(self.sin_cierre, telefono_limpio)

        if borrar_estado:
            resultado["Estados_Conversacion"] = self._eliminar_filas_por_telefono(self.estados, telefono_limpio)

        return resultado

    # ======================================================
    # ANALÍTICA BÁSICA
    # ======================================================

    def get_analytics_data(self):
        mensajes = self.mensajes.get_all_records()
        return {
            "total_mensajes": len(mensajes),
            "enviados": sum(1 for m in mensajes if m.get("Tipo") == "Enviado"),
            "recibidos": sum(1 for m in mensajes if m.get("Tipo") == "Recibido")
        }


sheets_manager = SheetsManager()
