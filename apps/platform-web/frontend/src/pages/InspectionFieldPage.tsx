import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import {
  createInspectionOutboxAction,
  type InspectionFieldObservationBody,
  type InspectionLocator,
  type InspectionObservedValue,
  type InspectionOutboxAction,
} from "@/features/inspectionField";
import {
  enqueueInspectionAction,
  listInspectionOutbox,
  syncInspectionOutbox,
} from "@/features/inspectionOffline";

type DevicePosition = {
  longitude: number;
  latitude: number;
  accuracyM: number;
  capturedAt: string;
};

function observed<T>(value: T): InspectionObservedValue<T> {
  return { state: "observed", value, reason: null };
}

function notMeasured<T>(reason: string): InspectionObservedValue<T> {
  return { state: "not_measured", value: null, reason };
}

function parseBoundedNumber(
  raw: string,
  *,
  label: string,
  min: number,
  max: number,
): InspectionObservedValue<number> {
  const value = raw.trim();
  if (!value) return notMeasured(`${label}_not_measured`);
  const number = Number(value);
  if (!Number.isFinite(number) || number < min || number > max) {
    throw new Error(`${label} debe estar entre ${min} y ${max}.`);
  }
  return observed(number);
}

function outboxStatusLabel(action: InspectionOutboxAction) {
  if (action.state === "syncing") return "Sincronizando";
  if (action.state === "conflict") return "Conflicto";
  if (action.state === "auth_required") return "Requiere sesión";
  if (action.state === "failed") return "Falló";
  return "Pendiente";
}

export default function InspectionFieldPage() {
  const { organizationRef, farmId, plotId } = useParams<{
    organizationRef: string;
    farmId: string;
    plotId: string;
  }>();
  const [searchParams] = useSearchParams();
  const tenantRef = searchParams.get("tenant")?.trim() || undefined;
  const samplingPointId = searchParams.get("sampling_point_id")?.trim() || null;

  const locator = useMemo<InspectionLocator | null>(() => {
    if (!organizationRef || !farmId || !plotId) return null;
    return { tenantRef, organizationRef, farmId, plotId };
  }, [farmId, organizationRef, plotId, tenantRef]);

  const syncingRef = useRef(false);
  const previousOnlineRef = useRef(navigator.onLine);

  const [isOnline, setIsOnline] = useState(() => navigator.onLine);
  const [outbox, setOutbox] = useState<InspectionOutboxAction[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [position, setPosition] = useState<DevicePosition | null>(null);
  const [gpsError, setGpsError] = useState<string | null>(null);

  const [foure, setFoure] = useState("3");
  const [yls, setYls] = useState("5");
  const [functionalLeaves, setFunctionalLeaves] = useState("8");
  const [motherCondition, setMotherCondition] = useState("vigorous");
  const [successorCondition, setSuccessorCondition] = useState("present");
  const [bunchPresent, setBunchPresent] = useState("yes");
  const [visibleAffection, setVisibleAffection] = useState("none_visible");
  const [severity, setSeverity] = useState("none");
  const [confidence, setConfidence] = useState("high");
  const [upId, setUpId] = useState("");
  const [note, setNote] = useState("");

  const refreshOutbox = useCallback(async () => {
    if (!locator) {
      setOutbox([]);
      return;
    }
    setOutbox(await listInspectionOutbox(locator));
  }, [locator]);

  const runSync = useCallback(async () => {
    if (!locator || !navigator.onLine || syncingRef.current) return;
    syncingRef.current = true;
    setSyncing(true);
    setError(null);
    try {
      const result = await syncInspectionOutbox(locator);
      await refreshOutbox();
      if (result.blockedState === "conflict") {
        setMessage("Sincronización detenida por conflicto; la observación queda preservada para revisión.");
      } else if (result.blockedState === "auth_required") {
        setMessage("La cola INSPECT requiere una sesión autorizada antes de continuar.");
      } else if (result.blockedState === "pending") {
        setMessage("La red volvió a fallar; las observaciones permanecen pendientes.");
      } else if (result.blockedState === "failed") {
        setMessage("Una observación falló y se conservó localmente para revisión/reintento.");
      } else if (result.synced > 0) {
        setMessage(`Se sincronizaron ${result.synced} observaciones INSPECT.`);
      }
    } catch (syncError) {
      setError(syncError instanceof Error ? syncError.message : "No se pudo sincronizar INSPECT.");
    } finally {
      syncingRef.current = false;
      setSyncing(false);
    }
  }, [locator, refreshOutbox]);

  useEffect(() => {
    const online = () => setIsOnline(true);
    const offline = () => setIsOnline(false);
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }, []);

  useEffect(() => {
    void refreshOutbox();
  }, [refreshOutbox]);

  useEffect(() => {
    const wasOnline = previousOnlineRef.current;
    previousOnlineRef.current = isOnline;
    if (isOnline && !wasOnline) void runSync();
  }, [isOnline, runSync]);

  const capturePosition = () => {
    setGpsError(null);
    if (!navigator.geolocation) {
      setGpsError("Este dispositivo/navegador no expone Geolocation API.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (gps) => {
        setPosition({
          longitude: Number(gps.coords.longitude.toFixed(7)),
          latitude: Number(gps.coords.latitude.toFixed(7)),
          accuracyM: Number(gps.coords.accuracy.toFixed(1)),
          capturedAt: new Date(gps.timestamp).toISOString(),
        });
      },
      (gpsFailure) => {
        if (gpsFailure.code === gpsFailure.PERMISSION_DENIED) {
          setGpsError("Permiso GPS denegado. Habilite ubicación para registrar evidencia espacial.");
        } else if (gpsFailure.code === gpsFailure.TIMEOUT) {
          setGpsError("El GPS no respondió dentro del tiempo esperado.");
        } else {
          setGpsError("No fue posible obtener una posición GPS válida.");
        }
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 15_000 },
    );
  };

  const buildObservation = (): InspectionFieldObservationBody => {
    const foureField = parseBoundedNumber(foure, {
      label: "Fouré",
      min: 0,
      max: 6,
    });
    const ylsField = parseBoundedNumber(yls, {
      label: "YLS",
      min: 0,
      max: 60,
    });
    const functionalLeavesField = parseBoundedNumber(functionalLeaves, {
      label: "Hojas funcionales",
      min: 0,
      max: 60,
    });

    const bunchField: InspectionObservedValue<boolean> =
      bunchPresent === "not_measured"
        ? notMeasured("bunch_not_measured")
        : observed(bunchPresent === "yes");

    return {
      observed_at: new Date().toISOString(),
      gps_fix: position
        ? {
            longitude: position.longitude,
            latitude: position.latitude,
            accuracy_m: position.accuracyM,
            captured_at: position.capturedAt,
          }
        : null,
      sampling_point_id: samplingPointId,
      up_id: upId.trim() || null,
      core: {
        foure: foureField,
        yls: ylsField,
        functional_leaves: functionalLeavesField,
        mother_condition: observed(motherCondition),
        successor_condition: observed(successorCondition),
        bunch_present: bunchField,
        visible_affection: observed(visibleAffection),
        severity: observed(severity),
        observer_confidence: observed(confidence),
        general_photo: {
          state: "not_measured",
          asset_id: null,
          reason: "pending_private_upload",
        },
        lesion_photo: {
          state: "not_measured",
          asset_id: null,
          reason: "pending_private_upload",
        },
        note: note.trim() || null,
      },
      structural: null,
      diagnostic: null,
    };
  };

  const saveObservation = async () => {
    if (!locator || saving) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const action = createInspectionOutboxAction(locator, buildObservation());
      await enqueueInspectionAction(action);
      await refreshOutbox();
      setMessage(
        `Observación ${action.observationId.slice(0, 8)}… guardada localmente con identidad estable.`,
      );
      if (navigator.onLine) await runSync();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "No se pudo guardar la observación.");
    } finally {
      setSaving(false);
    }
  };

  const conflicts = outbox.filter((action) => action.state === "conflict").length;

  return (
    <div className="space-y-4">
      <div className={`status-banner ${isOnline ? "status-banner-info" : "status-banner-warning"}`}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <div className="font-medium">
              {isOnline ? "Con conexión" : "Modo offline"} · INSPECT de campo
            </div>
            <p className="mt-1 text-sm">
              Cada captura recibe IDs estables antes de entrar a la cola; un reintento no crea una segunda verdad-terreno.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="chip">Pendientes: {outbox.length}</span>
            <span className="chip">Conflictos: {conflicts}</span>
            <button
              className="btn-secondary"
              disabled={!isOnline || syncing || outbox.length === 0}
              onClick={() => void runSync()}
            >
              {syncing ? "Sincronizando…" : "Sincronizar"}
            </button>
          </div>
        </div>
      </div>

      {message && <div className="status-banner text-sm">{message}</div>}
      {error && <div className="status-banner status-banner-danger">{error}</div>}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="card space-y-5">
          <div>
            <div className="eyebrow">Captura rápida INSPECT</div>
            <h1 className="mt-1">Observación de verdad-terreno</h1>
            <p className="muted mt-2 text-sm">
              CORE sanitario/fenológico. La UP es opcional y sólo debe indicarse cuando la asociación sea inequívoca.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <label className="text-sm">
              <span className="font-medium">Fouré 0–6</span>
              <select className="mt-2 w-full" value={foure} onChange={(event) => setFoure(event.target.value)}>
                <option value="">No medido</option>
                {[0, 1, 2, 3, 4, 5, 6].map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>

            <label className="text-sm">
              <span className="font-medium">YLS</span>
              <input
                className="mt-2 w-full"
                type="number"
                min="0"
                max="60"
                value={yls}
                onChange={(event) => setYls(event.target.value)}
                placeholder="Vacío = no medido"
              />
            </label>

            <label className="text-sm">
              <span className="font-medium">Hojas funcionales</span>
              <input
                className="mt-2 w-full"
                type="number"
                min="0"
                max="60"
                value={functionalLeaves}
                onChange={(event) => setFunctionalLeaves(event.target.value)}
                placeholder="Vacío = no medido"
              />
            </label>

            <label className="text-sm">
              <span className="font-medium">Condición madre</span>
              <select className="mt-2 w-full" value={motherCondition} onChange={(event) => setMotherCondition(event.target.value)}>
                <option value="vigorous">Vigorosa</option>
                <option value="stressed">Estresada</option>
                <option value="damaged">Dañada</option>
                <option value="uncertain">Incierta</option>
              </select>
            </label>

            <label className="text-sm">
              <span className="font-medium">Condición sucesor</span>
              <select className="mt-2 w-full" value={successorCondition} onChange={(event) => setSuccessorCondition(event.target.value)}>
                <option value="present">Presente</option>
                <option value="weak">Débil</option>
                <option value="absent">Ausente</option>
                <option value="uncertain">Incierta</option>
              </select>
            </label>

            <label className="text-sm">
              <span className="font-medium">Racimo visible</span>
              <select className="mt-2 w-full" value={bunchPresent} onChange={(event) => setBunchPresent(event.target.value)}>
                <option value="yes">Sí</option>
                <option value="no">No</option>
                <option value="not_measured">No medido</option>
              </select>
            </label>

            <label className="text-sm">
              <span className="font-medium">Afección visible</span>
              <select className="mt-2 w-full" value={visibleAffection} onChange={(event) => setVisibleAffection(event.target.value)}>
                <option value="none_visible">Ninguna visible</option>
                <option value="black_sigatoka_suspected">Sigatoka negra sospechada</option>
                <option value="other_visible">Otra visible</option>
                <option value="uncertain">Incierta</option>
              </select>
            </label>

            <label className="text-sm">
              <span className="font-medium">Severidad observada</span>
              <select className="mt-2 w-full" value={severity} onChange={(event) => setSeverity(event.target.value)}>
                <option value="none">Ninguna</option>
                <option value="low">Baja</option>
                <option value="moderate">Moderada</option>
                <option value="high">Alta</option>
                <option value="uncertain">Incierta</option>
              </select>
            </label>

            <label className="text-sm">
              <span className="font-medium">Confianza del observador</span>
              <select className="mt-2 w-full" value={confidence} onChange={(event) => setConfidence(event.target.value)}>
                <option value="high">Alta</option>
                <option value="medium">Media</option>
                <option value="low">Baja</option>
              </select>
            </label>
          </div>

          <div className="divider grid gap-4 pt-4 lg:grid-cols-2">
            <div>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-medium">GPS observado</div>
                  <p className="muted mt-1 text-xs">La posición es evidencia; nunca redefine por sí sola la identidad de una UP.</p>
                </div>
                <button className="btn-secondary" type="button" onClick={capturePosition}>Capturar GPS</button>
              </div>
              {position && (
                <div className="mt-3 rounded-xl border p-3 text-xs">
                  <div>{position.latitude.toFixed(7)}, {position.longitude.toFixed(7)}</div>
                  <div className="muted mt-1">Precisión reportada: ±{position.accuracyM.toFixed(1)} m</div>
                </div>
              )}
              {gpsError && <div className="mt-3 text-sm text-rose-600">{gpsError}</div>}
            </div>

            <div className="space-y-3">
              <label className="text-sm">
                <span className="font-medium">UP ID opcional</span>
                <input
                  className="mt-2 w-full"
                  value={upId}
                  onChange={(event) => setUpId(event.target.value)}
                  placeholder="Dejar vacío si la asociación no es inequívoca"
                />
              </label>
              {samplingPointId && (
                <div className="rounded-xl border p-3 text-xs">
                  <div className="muted">Punto Sampling vinculado</div>
                  <div className="mt-1 break-all font-medium">{samplingPointId}</div>
                </div>
              )}
            </div>
          </div>

          <label className="block text-sm">
            <span className="font-medium">Observación breve</span>
            <textarea
              className="mt-2 min-h-24 w-full"
              maxLength={1000}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              placeholder="Detalle estrictamente observado en campo"
            />
          </label>

          <div className="status-banner text-sm">
            En este corte la captura CORE puede trabajar completamente offline. Las fotos se registran explícitamente como pendientes de carga privada y podrán incorporarse mediante una corrección versionada; no se inventa evidencia fotográfica.
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              className="btn-primary"
              disabled={!locator || saving}
              onClick={() => void saveObservation()}
            >
              {saving ? "Guardando…" : "Guardar observación"}
            </button>
            <button
              className="btn-secondary"
              disabled={!isOnline || syncing || outbox.length === 0}
              onClick={() => void runSync()}
            >
              Sincronizar pendientes
            </button>
          </div>
        </section>

        <aside className="card">
          <div className="eyebrow">Cola offline INSPECT</div>
          <div className="mt-1 text-sm font-medium">{outbox.length} observaciones locales</div>
          <p className="muted mt-2 text-xs">
            La cola contiene payload observado e IDs técnicos; nunca almacena el token de sesión.
          </p>
          <div className="mt-4 max-h-[520px] space-y-2 overflow-auto">
            {outbox.length === 0 && <div className="muted text-sm">No hay observaciones pendientes.</div>}
            {outbox.map((action) => (
              <div key={action.actionId} className="rounded-xl border p-3 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{action.observationId.slice(0, 8)}…</span>
                  <span className="chip">{outboxStatusLabel(action)}</span>
                </div>
                <div className="muted mt-1">Intentos: {action.attemptCount}</div>
                {action.lastError && (
                  <div className="mt-2 text-amber-700 dark:text-amber-200">{action.lastError}</div>
                )}
              </div>
            ))}
          </div>
        </aside>
      </div>
    </div>
  );
}
