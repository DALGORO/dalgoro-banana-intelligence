import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  askIncidentAssistant,
  createIncidentCase,
  createIncidentWorker,
  createWorkerEppDelivery,
  generateIncidentProcedurePdf,
  getIncidentAssistantState,
  saveIncidentProcedure,
  updateIncidentCase,
} from "../app/api";

type ProcedureFields = {
  approved_by: string;
  approved_role: string;
  approved_at: string;
  notes: string;
};

type WorkerProfile = {
  document_id: number;
  full_name: string;
  id_number: string;
  job: string;
  start_date: string;
  status: string;
  notes: string;
  incident_count: number;
  epp_delivery_count: number;
  recommended_epp: string[];
};

type EPPDelivery = {
  document_id: number;
  worker_document_id: number;
  worker_name: string;
  id_number: string;
  job: string;
  delivery_date: string;
  items_text: string;
  return_notes: string;
  observations: string;
  worker_receipt_name: string;
  employer_receipt_name: string;
};

type CaseRecord = {
  document_id: number;
  title: string;
  created_at?: string | null;
  event_type: string;
  status: string;
  happened_at: string;
  worker_document_id: number;
  worker_name: string;
  id_number: string;
  job_title: string;
  place: string;
  description: string;
  consequences: string;
  witnesses: string;
  causes: string;
  immediate_actions: string;
  corrective_actions: string;
  preventive_actions: string;
  reported_to_authority: boolean;
};

type ModuleState = {
  company: {
    company_id: number;
    name: string;
    activity: string;
    workers: number;
    risk: string;
    classification: string;
    responsible: string;
    organ: string;
  };
  iperc_jobs: string[];
  procedure: {
  exists: boolean;
  document_id?: number | null;
  title?: string | null;
  updated_at?: string | null;
  fields: ProcedureFields;
  generated_summary: string;
  generated_sections: {
    objetivo: string;
    alcance: string;
    responsabilidades: string;
    procedimiento_investigacion: string;
    documentacion_registro: string;
    acciones_correctivas_preventivas: string;
    consideraciones_actividad: string;
    epp_por_puesto: string;
    ejecucion_en_sistema: string;
  };
};
  stats: {
    total_cases: number;
    total_accidents: number;
    total_incidents: number;
    open_cases: number;
    closed_cases: number;
    cases_this_year: number;
  };
  latest_case?: CaseRecord | null;
  cases: CaseRecord[];
  workers: WorkerProfile[];
  job_epp_catalog: Array<{
    job: string;
    items: string[];
  }>;
  epp_deliveries: EPPDelivery[];
  can_register_workers: boolean;
  can_register_cases: boolean;
  blocking_message?: string | null;
  generated_documents: Array<{
    id: number;
    title: string;
    kind: string;
    requirement_code?: string | null;
    created_at?: string | null;
    has_file?: boolean;
  }>;
};

type AssistantResponse = {
  answer: string;
  blocked?: boolean;
  sources?: string[];
  system_state?: ModuleState;
};

const QUICK_PROMPTS = [
  "¿Qué debo hacer ante un incidente sin lesión?",
  "¿Qué debo hacer ahora en el sistema?",
  "¿Cómo registro al trabajador correctamente?",
  "¿Cómo relaciono esto con IPERC y EPP?",
  "¿Qué sustento normativo aplica?",
];

const EMPTY_PROCEDURE: ProcedureFields = {
  approved_by: "",
  approved_role: "",
  approved_at: "",
  notes: "",
};

const EMPTY_WORKER = {
  full_name: "",
  id_number: "",
  job: "",
  start_date: "",
  status: "ACTIVO",
  notes: "",
};

const EMPTY_EPP = {
  worker_document_id: 0,
  delivery_date: "",
  items_text: "",
  return_notes: "",
  observations: "",
  worker_receipt_name: "",
  employer_receipt_name: "",
};

const EMPTY_CASE: CaseRecord = {
  document_id: 0,
  title: "",
  created_at: "",
  event_type: "INCIDENTE",
  status: "ABIERTO",
  happened_at: "",
  worker_document_id: 0,
  worker_name: "",
  id_number: "",
  job_title: "",
  place: "",
  description: "",
  consequences: "",
  witnesses: "",
  causes: "",
  immediate_actions: "",
  corrective_actions: "",
  preventive_actions: "",
  reported_to_authority: false,
};

export default function IncidentAssistant() {
  const { id } = useParams();
  const companyId = Number(id);
  const navigate = useNavigate();

  const [moduleState, setModuleState] = useState<ModuleState | null>(null);
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [blocked, setBlocked] = useState(false);

  const [procedureForm, setProcedureForm] = useState<ProcedureFields>(EMPTY_PROCEDURE);
  const [workerForm, setWorkerForm] = useState(EMPTY_WORKER);
  const [eppForm, setEppForm] = useState(EMPTY_EPP);
  const [caseForm, setCaseForm] = useState<CaseRecord>(EMPTY_CASE);
  const [editingCaseId, setEditingCaseId] = useState<number | null>(null);
  const [selectedWorkerProfileId, setSelectedWorkerProfileId] = useState<number>(0);

  const [loadingState, setLoadingState] = useState(true);
  const [loadingAnswer, setLoadingAnswer] = useState(false);
  const [savingProcedureState, setSavingProcedureState] = useState(false);
  const [generatingProcedurePdfState, setGeneratingProcedurePdfState] = useState(false);
  const [savingWorkerState, setSavingWorkerState] = useState(false);
  const [savingEppState, setSavingEppState] = useState(false);
  const [savingCaseState, setSavingCaseState] = useState(false);
  const workerProfileSectionRef = useRef<HTMLDivElement | null>(null);
  const eppSectionRef = useRef<HTMLFormElement | null>(null);
  const caseSectionRef = useRef<HTMLFormElement | null>(null);  

  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [pendingScrollTarget, setPendingScrollTarget] = useState<"profile" | "epp" | "case" | null>(null);  

  const invalidCompanyId = !Number.isFinite(companyId) || companyId <= 0;

  const workers = moduleState?.workers ?? [];
  const ipercJobs = moduleState?.iperc_jobs ?? [];

  const selectedWorker = useMemo(
    () => workers.find((w) => w.document_id === Number(caseForm.worker_document_id)) ?? null,
    [workers, caseForm.worker_document_id]
  );

  const selectedEppWorker = useMemo(
    () => workers.find((w) => w.document_id === Number(eppForm.worker_document_id)) ?? null,
    [workers, eppForm.worker_document_id]
  );
  
  const selectedWorkerForProfile = useMemo(
    () => workers.find((w) => w.document_id === Number(selectedWorkerProfileId)) ?? null,
    [workers, selectedWorkerProfileId]
  );

  const selectedJobRecommendation = useMemo(
    () =>
      moduleState?.job_epp_catalog?.find(
        (item) => item.job === workerForm.job
      ) ?? null,
    [moduleState, workerForm.job]
  );

  const selectedWorkerCases = useMemo(
    () =>
      moduleState?.cases?.filter(
        (item) => item.worker_document_id === Number(selectedWorkerProfileId)
      ) ?? [],
    [moduleState, selectedWorkerProfileId]
  );

  const scrollToRef = (ref: React.RefObject<HTMLElement | null>) => {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const openWorkerProfile = (workerId: number) => {
    setSelectedWorkerProfileId(workerId);
    setPendingScrollTarget("profile");
    setSuccess(null);
    setError(null);
  };

  const startCaseForWorker = (workerId: number) => {
    setEditingCaseId(null);
    setCaseForm({
      ...EMPTY_CASE,
      worker_document_id: workerId,
    });
    setPendingScrollTarget("case");
    setSuccess(null);
    setError(null);
  };

  const startEppForWorker = (workerId: number) => {
    setEppForm({
      ...EMPTY_EPP,
      worker_document_id: workerId,
    });
    setPendingScrollTarget("epp");
    setSuccess(null);
    setError(null);
  };

  const selectedWorkerEppDeliveries = useMemo(
    () =>
      moduleState?.epp_deliveries?.filter(
        (item) => item.worker_document_id === Number(selectedWorkerProfileId)
      ) ?? [],
    [moduleState, selectedWorkerProfileId]
  );

  const loadState = async () => {
    if (invalidCompanyId) return;

    setLoadingState(true);
    setError(null);

    try {
      const response = await getIncidentAssistantState(companyId);
      const payload = response.data as ModuleState;
      setModuleState(payload);
      setProcedureForm(payload?.procedure?.fields ?? EMPTY_PROCEDURE);
    } catch {
      setError("No se pudo cargar el estado del módulo.");
    } finally {
      setLoadingState(false);
    }
  };

  useEffect(() => {
    void loadState();
  }, [companyId]);

  useEffect(() => {
    if (selectedWorker) {
      setCaseForm((prev) => ({
        ...prev,
        worker_name: selectedWorker.full_name,
        id_number: selectedWorker.id_number,
        job_title: selectedWorker.job,
      }));
    } else {
      setCaseForm((prev) => ({
        ...prev,
        worker_name: "",
        id_number: "",
        job_title: "",
      }));
    }
  }, [selectedWorker]);

  useEffect(() => {
    if (!selectedEppWorker) return;

    setEppForm((prev) => {
      if ((prev.items_text || "").trim()) return prev;

      const suggested = Array.isArray(selectedEppWorker.recommended_epp)
        ? selectedEppWorker.recommended_epp
        : [];

      if (!suggested.length) return prev;

      return {
        ...prev,
        items_text: suggested.join("\n"),
        worker_receipt_name: prev.worker_receipt_name || selectedEppWorker.full_name,
      };
    });
  }, [selectedEppWorker]);

  useEffect(() => {
  if (!pendingScrollTarget) return;

  const run = () => {
    if (pendingScrollTarget === "profile") {
      scrollToRef(workerProfileSectionRef);
    } else if (pendingScrollTarget === "epp") {
      scrollToRef(eppSectionRef);
    } else if (pendingScrollTarget === "case") {
      scrollToRef(caseSectionRef);
    }

    setPendingScrollTarget(null);
  };

  const id = window.requestAnimationFrame(() => {
    window.requestAnimationFrame(run);
  });

  return () => window.cancelAnimationFrame(id);
}, [pendingScrollTarget, selectedWorkerProfileId, caseForm.worker_document_id, eppForm.worker_document_id]);

  const runQuery = async (nextQuestion?: string) => {
    const finalQuestion = String(nextQuestion ?? question).trim();
    if (!finalQuestion || invalidCompanyId || loadingAnswer) return;

    setLoadingAnswer(true);
    setError(null);
    setSuccess(null);

    try {
      const response = await askIncidentAssistant(companyId, finalQuestion);
      const payload = (response.data ?? {}) as AssistantResponse;

      setQuestion(finalQuestion);
      setAnswer(String(payload.answer ?? ""));
      setSources(Array.isArray(payload.sources) ? payload.sources : []);
      setBlocked(Boolean(payload.blocked));

      if (payload.system_state) {
        setModuleState(payload.system_state);
        setProcedureForm(payload.system_state.procedure?.fields ?? EMPTY_PROCEDURE);
      }
    } catch {
      setError("No se pudo procesar la consulta en este momento.");
    } finally {
      setLoadingAnswer(false);
    }
  };

  const saveProcedureHandler = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (invalidCompanyId || savingProcedureState) return;

    setSavingProcedureState(true);
    setError(null);
    setSuccess(null);

    try {
      await saveIncidentProcedure(companyId, procedureForm);
      setSuccess("El procedimiento quedó guardado en el sistema.");
      await loadState();
    } catch {
      setError("No se pudo guardar el procedimiento.");
    } finally {
      setSavingProcedureState(false);
    }
  };

  const generateProcedurePdfHandler = async () => {
    if (invalidCompanyId || generatingProcedurePdfState) return;

    setGeneratingProcedurePdfState(true);
    setError(null);
    setSuccess(null);

    try {
      await saveIncidentProcedure(companyId, procedureForm);

      const response = await generateIncidentProcedurePdf(companyId);
      const data = response.data ?? {};

      setSuccess("El PDF del procedimiento fue generado correctamente.");
      await loadState();

      if (data?.id) {
        navigate(`/documents/${data.id}`, {
          state: {
            title: data?.title ?? "INV-AT-01 Procedimiento documentado",
            mime: "application/pdf",
          },
        });
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || "No se pudo generar el PDF del procedimiento.");
    } finally {
      setGeneratingProcedurePdfState(false);
    }
  };

  const saveWorkerHandler = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (invalidCompanyId || savingWorkerState) return;

    setSavingWorkerState(true);
    setError(null);
    setSuccess(null);

    try {
      await createIncidentWorker(companyId, workerForm);
      setSuccess("La ficha del trabajador fue registrada correctamente.");
      setWorkerForm(EMPTY_WORKER);
      await loadState();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "No se pudo registrar al trabajador.");
    } finally {
      setSavingWorkerState(false);
    }
  };

  const saveEppHandler = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (invalidCompanyId || savingEppState) return;

    setSavingEppState(true);
    setError(null);
    setSuccess(null);

    try {
      await createWorkerEppDelivery(companyId, eppForm);
      setSuccess("La entrega de EPP fue registrada correctamente.");
      setEppForm(EMPTY_EPP);
      await loadState();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "No se pudo registrar la entrega de EPP.");
    } finally {
      setSavingEppState(false);
    }
  };

  const saveCaseHandler = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (invalidCompanyId || savingCaseState) return;

    setSavingCaseState(true);
    setError(null);
    setSuccess(null);

    const payload = {
      event_type: caseForm.event_type,
      status: caseForm.status,
      happened_at: caseForm.happened_at,
      worker_document_id: caseForm.worker_document_id,
      place: caseForm.place,
      description: caseForm.description,
      consequences: caseForm.consequences,
      witnesses: caseForm.witnesses,
      causes: caseForm.causes,
      immediate_actions: caseForm.immediate_actions,
      corrective_actions: caseForm.corrective_actions,
      preventive_actions: caseForm.preventive_actions,
      reported_to_authority: Boolean(caseForm.reported_to_authority),
    };

    try {
      if (editingCaseId) {
        await updateIncidentCase(companyId, editingCaseId, payload);
        setSuccess("El caso fue actualizado correctamente.");
      } else {
        await createIncidentCase(companyId, payload);
        setSuccess("El caso fue registrado correctamente.");
      }

      setCaseForm(EMPTY_CASE);
      setEditingCaseId(null);
      await loadState();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "No se pudo guardar el caso.");
    } finally {
      setSavingCaseState(false);
    }
  };

  const loadCaseIntoForm = (item: CaseRecord) => {
    setEditingCaseId(item.document_id);
    setCaseForm(item);
    setSuccess(null);
    setError(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  if (invalidCompanyId) {
    return (
      <div className="status-banner status-banner-danger text-sm">
        No se pudo identificar la empresa actual.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="section-head flex-wrap">
        <div className="page-title-block">
          <span className="page-kicker">Empresa actual</span>
          <h1>Investigación y consultas SST</h1>
          <p className="page-subtitle">
            Resuelve la consulta, registra trabajadores, deja trazabilidad de EPP y ejecuta
            investigaciones amarradas a puestos reales de la matriz IPERC.
          </p>
        </div>

        <div className="flex gap-2 flex-wrap">
          <Link to={`/companies/${companyId}/iperc`} className="btn-secondary">
            Ir a IPERC
          </Link>
          <Link to={`/companies/${companyId}`} className="btn-ghost">
            ← Volver a la empresa
          </Link>
        </div>
      </div>

      {error && <div className="status-banner status-banner-danger text-sm">{error}</div>}
      {success && <div className="status-banner status-banner-success text-sm">{success}</div>}

      {loadingState ? (
        <div className="surface text-sm text-slate-600 dark:text-slate-300">
          Cargando estado del módulo...
        </div>
      ) : moduleState ? (
        <>
          {moduleState.blocking_message && (
            <div className="status-banner text-sm">
              {moduleState.blocking_message}
            </div>
          )}

          <div ref={workerProfileSectionRef} className="surface space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                Resumen del módulo
              </h2>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
                {moduleState.company.name} · {moduleState.company.activity} · Riesgo {moduleState.company.risk}
              </p>
            </div>

            <div className="grid gap-3 md:grid-cols-4">
              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Puestos IPERC</div>
                <div className="mt-2 text-base font-semibold text-slate-900 dark:text-white">{moduleState.iperc_jobs.length}</div>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Trabajadores</div>
                <div className="mt-2 text-base font-semibold text-slate-900 dark:text-white">{moduleState.workers.length}</div>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Casos</div>
                <div className="mt-2 text-base font-semibold text-slate-900 dark:text-white">{moduleState.stats.total_cases}</div>
              </div>
              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Entregas EPP</div>
                <div className="mt-2 text-base font-semibold text-slate-900 dark:text-white">{moduleState.epp_deliveries.length}</div>
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <span className="chip">Accidentes: {moduleState.stats.total_accidents}</span>
              <span className="chip">Incidentes: {moduleState.stats.total_incidents}</span>
              <span className="chip">Abiertos: {moduleState.stats.open_cases}</span>
              <span className="chip">Cerrados: {moduleState.stats.closed_cases}</span>
            </div>
          </div>

          <div className="surface space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                Consulta guiada
              </h2>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                El asistente responde con normativa, con lo que ya existe en el sistema y con
                la acción siguiente que debes ejecutar dentro del sistema.
              </p>
            </div>

            <div className="flex flex-wrap gap-2">
              {QUICK_PROMPTS.map((prompt) => (
                <button
                  key={prompt}
                  type="button"
                  className="btn-secondary text-sm"
                  disabled={loadingAnswer}
                  onClick={() => void runQuery(prompt)}
                >
                  {prompt}
                </button>
              ))}
            </div>

            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={5}
              placeholder="Ejemplo: ocurrió un incidente sin lesión, el trabajador ya está registrado y quiero saber qué debo hacer ahora dentro del sistema."
              className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-800 shadow-sm outline-none transition focus:border-slate-400 focus:ring-2 focus:ring-slate-200 dark:border-white/10 dark:bg-slate-900/70 dark:text-white dark:focus:border-white/20 dark:focus:ring-white/10"
            />

            <div className="flex gap-2 flex-wrap">
              <button
                type="button"
                className="btn-primary disabled:opacity-60"
                disabled={loadingAnswer || !question.trim()}
                onClick={() => void runQuery()}
              >
                {loadingAnswer ? "Consultando..." : "Consultar"}
              </button>

              <button
                type="button"
                className="btn-secondary"
                onClick={() => {
                  setQuestion("");
                  setAnswer("");
                  setSources([]);
                  setBlocked(false);
                }}
              >
                Limpiar
              </button>
            </div>

            {answer && (
              <div className="space-y-3">
                {blocked && (
                  <div className="status-banner text-sm">
                    La consulta fue respondida sin mostrar detalles técnicos internos.
                  </div>
                )}

                <div className="rounded-2xl border border-slate-200/80 bg-white/70 p-4 text-sm leading-7 text-slate-700 dark:border-white/10 dark:bg-slate-900/50 dark:text-slate-200 whitespace-pre-wrap">
                  {answer}
                </div>

                {sources.length > 0 && (
                  <div className="flex flex-wrap gap-2">
                    {sources.map((source) => (
                      <span key={source} className="chip">
                        {source}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          <form onSubmit={saveProcedureHandler} className="surface space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                Procedimiento documentado
              </h2>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                Este procedimiento es único para la empresa y se genera con base en la actividad,
                número de trabajadores, estructura SST e IPERC vigente.
              </p>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 text-sm dark:border-white/10 dark:bg-slate-900/50">
              {moduleState.procedure.generated_summary}
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Objetivo</div>
                <div className="text-sm whitespace-pre-wrap text-slate-700 dark:text-slate-200">
                  {moduleState.procedure.generated_sections.objetivo}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Alcance</div>
                <div className="text-sm whitespace-pre-wrap text-slate-700 dark:text-slate-200">
                  {moduleState.procedure.generated_sections.alcance}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Responsabilidades</div>
                <div className="text-sm whitespace-pre-wrap text-slate-700 dark:text-slate-200">
                  {moduleState.procedure.generated_sections.responsabilidades}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Procedimiento de investigación</div>
                <div className="text-sm whitespace-pre-wrap text-slate-700 dark:text-slate-200">
                  {moduleState.procedure.generated_sections.procedimiento_investigacion}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Documentación y registro</div>
                <div className="text-sm whitespace-pre-wrap text-slate-700 dark:text-slate-200">
                  {moduleState.procedure.generated_sections.documentacion_registro}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Acciones correctivas y preventivas</div>
                <div className="text-sm whitespace-pre-wrap text-slate-700 dark:text-slate-200">
                  {moduleState.procedure.generated_sections.acciones_correctivas_preventivas}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Consideraciones por actividad</div>
                <div className="text-sm whitespace-pre-wrap text-slate-700 dark:text-slate-200">
                  {moduleState.procedure.generated_sections.consideraciones_actividad}
                </div>
              </div>

              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">EPP por puesto</div>
                <div className="text-sm whitespace-pre-wrap text-slate-700 dark:text-slate-200">
                  {moduleState.procedure.generated_sections.epp_por_puesto}
                </div>
              </div>
            </div>

            <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
              <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">Ejecución en el sistema</div>
              <div className="text-sm whitespace-pre-wrap text-slate-700 dark:text-slate-200">
                {moduleState.procedure.generated_sections.ejecucion_en_sistema}
              </div>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <input
                type="text"
                placeholder="Aprobado por"
                className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70"
                value={procedureForm.approved_by}
                onChange={(e) => setProcedureForm((prev) => ({ ...prev, approved_by: e.target.value }))}
              />

              <input
                type="text"
                placeholder="Cargo de quien aprueba"
                className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70"
                value={procedureForm.approved_role}
                onChange={(e) => setProcedureForm((prev) => ({ ...prev, approved_role: e.target.value }))}
              />

              <input
                type="date"
                className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70"
                value={procedureForm.approved_at}
                onChange={(e) => setProcedureForm((prev) => ({ ...prev, approved_at: e.target.value }))}
              />
            </div>

            <textarea
              rows={4}
              placeholder="Observaciones de la empresa sobre el procedimiento"
              className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70"
              value={procedureForm.notes}
              onChange={(e) => setProcedureForm((prev) => ({ ...prev, notes: e.target.value }))}
            />

            <div className="flex gap-2 flex-wrap">
              <button
                type="submit"
                className="btn-primary disabled:opacity-60"
                disabled={savingProcedureState}
              >
                {savingProcedureState ? "Guardando..." : "Guardar aprobación del procedimiento"}
              </button>

              <button
                type="button"
                className="btn-secondary disabled:opacity-60"
                disabled={generatingProcedurePdfState}
                onClick={generateProcedurePdfHandler}
              >
                {generatingProcedurePdfState ? "Generando PDF..." : "Generar PDF del procedimiento"}
              </button>
            </div>
          </form>

          <form onSubmit={saveWorkerHandler} className="surface space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Fichas de trabajadores</h2>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                El trabajador se registra con un puesto existente en IPERC. No se permite crear puestos nuevos aquí.
              </p>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <input type="text" placeholder="Nombres y apellidos" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={workerForm.full_name} onChange={(e) => setWorkerForm((prev) => ({ ...prev, full_name: e.target.value }))} disabled={!moduleState.can_register_workers} />
              <input type="text" placeholder="Número de cédula" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={workerForm.id_number} onChange={(e) => setWorkerForm((prev) => ({ ...prev, id_number: e.target.value }))} disabled={!moduleState.can_register_workers} />
              <select className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={workerForm.job} onChange={(e) => setWorkerForm((prev) => ({ ...prev, job: e.target.value }))} disabled={!moduleState.can_register_workers}>
                <option value="">Selecciona un puesto IPERC</option>
                {ipercJobs.map((job) => (
                  <option key={job} value={job}>{job}</option>
                ))}
              </select>

              <input type="date" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={workerForm.start_date} onChange={(e) => setWorkerForm((prev) => ({ ...prev, start_date: e.target.value }))} disabled={!moduleState.can_register_workers} />
            </div>
            {selectedJobRecommendation && selectedJobRecommendation.items.length > 0 && (
              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 text-sm dark:border-white/10 dark:bg-slate-900/50 md:col-span-2">
                <div className="mb-2 font-medium text-slate-900 dark:text-white">
                  EPP sugerido para este puesto
                </div>
                <div className="flex flex-wrap gap-2">
                  {selectedJobRecommendation.items.map((item) => (
                    <span key={item} className="chip">
                      {item}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <textarea rows={3} placeholder="Observaciones" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={workerForm.notes} onChange={(e) => setWorkerForm((prev) => ({ ...prev, notes: e.target.value }))} disabled={!moduleState.can_register_workers} />

            <button type="submit" className="btn-primary disabled:opacity-60" disabled={savingWorkerState || !moduleState.can_register_workers}>
              {savingWorkerState ? "Guardando..." : "Registrar trabajador"}
            </button>
          </form>

          <form ref={eppSectionRef} onSubmit={saveEppHandler} className="surface space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Entrega de EPP</h2>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                La entrega queda asociada al trabajador y, por arrastre, a su puesto de trabajo.
              </p>
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <select className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={eppForm.worker_document_id} onChange={(e) => setEppForm((prev) => ({ ...prev, worker_document_id: Number(e.target.value) }))} disabled={workers.length === 0}>
                <option value={0}>Selecciona un trabajador</option>
                {workers.map((worker) => (
                  <option key={worker.document_id} value={worker.document_id}>
                    {worker.full_name} · {worker.job}
                  </option>
                ))}
              </select>

              <input type="date" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={eppForm.delivery_date} onChange={(e) => setEppForm((prev) => ({ ...prev, delivery_date: e.target.value }))} disabled={workers.length === 0} />
            </div>

            {selectedEppWorker && (
              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 text-sm dark:border-white/10 dark:bg-slate-900/50 space-y-3">
                <div><strong>Trabajador:</strong> {selectedEppWorker.full_name}</div>
                <div><strong>Puesto:</strong> {selectedEppWorker.job}</div>
                <div><strong>Cédula:</strong> {selectedEppWorker.id_number || "sin registrar"}</div>

                <div>
                  <div className="mb-2 font-medium text-slate-900 dark:text-white">
                    EPP sugerido por el puesto
                  </div>

                  {selectedEppWorker.recommended_epp?.length ? (
                    <div className="flex flex-wrap gap-2">
                      {selectedEppWorker.recommended_epp.map((item) => (
                        <span key={item} className="chip">
                          {item}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="muted text-xs">
                      Este puesto todavía no tiene EPP sugerido desde la IPERC.
                    </div>
                  )}
                </div>

                {selectedEppWorker.recommended_epp?.length > 0 && (
                  <div>
                    <button
                      type="button"
                      className="btn-secondary text-sm"
                      onClick={() =>
                        setEppForm((prev) => ({
                          ...prev,
                          items_text: selectedEppWorker.recommended_epp.join("\n"),
                          worker_receipt_name: prev.worker_receipt_name || selectedEppWorker.full_name,
                        }))
                      }
                    >
                      Cargar EPP sugerido del puesto
                    </button>
                  </div>
                )}
              </div>
            )}

            <textarea rows={4} placeholder="Detalle del EPP y/o ropa de trabajo entregado" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={eppForm.items_text} onChange={(e) => setEppForm((prev) => ({ ...prev, items_text: e.target.value }))} disabled={workers.length === 0} />
            <textarea rows={3} placeholder="Registro de devoluciones / reposición" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={eppForm.return_notes} onChange={(e) => setEppForm((prev) => ({ ...prev, return_notes: e.target.value }))} disabled={workers.length === 0} />
            <textarea rows={3} placeholder="Observaciones" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={eppForm.observations} onChange={(e) => setEppForm((prev) => ({ ...prev, observations: e.target.value }))} disabled={workers.length === 0} />

            <div className="grid gap-3 md:grid-cols-2">
              <input type="text" placeholder="Nombre de quien recibe" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={eppForm.worker_receipt_name} onChange={(e) => setEppForm((prev) => ({ ...prev, worker_receipt_name: e.target.value }))} disabled={workers.length === 0} />
              <input type="text" placeholder="Nombre de quien entrega" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={eppForm.employer_receipt_name} onChange={(e) => setEppForm((prev) => ({ ...prev, employer_receipt_name: e.target.value }))} disabled={workers.length === 0} />
            </div>

            <button type="submit" className="btn-primary disabled:opacity-60" disabled={savingEppState || workers.length === 0}>
              {savingEppState ? "Guardando..." : "Registrar entrega de EPP"}
            </button>
          </form>

          <form ref={caseSectionRef} onSubmit={saveCaseHandler} className="surface space-y-4">
            <div className="flex items-start justify-between gap-3 flex-wrap">
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                  {editingCaseId ? "Actualizar caso" : "Registrar incidente o accidente"}
                </h2>
                <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                  El trabajador y el puesto salen del sistema. Ya no se permiten nombres o puestos manuales.
                </p>
              </div>

              {editingCaseId && (
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    setEditingCaseId(null);
                    setCaseForm(EMPTY_CASE);
                  }}
                >
                  Nuevo caso
                </button>
              )}
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <select className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.event_type} onChange={(e) => setCaseForm((prev) => ({ ...prev, event_type: e.target.value }))} disabled={!moduleState.can_register_cases}>
                <option value="INCIDENTE">Incidente</option>
                <option value="ACCIDENTE">Accidente</option>
              </select>

              <select className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.status} onChange={(e) => setCaseForm((prev) => ({ ...prev, status: e.target.value }))} disabled={!moduleState.can_register_cases}>
                <option value="ABIERTO">Abierto</option>
                <option value="EN SEGUIMIENTO">En seguimiento</option>
                <option value="CERRADO">Cerrado</option>
              </select>

              <select className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.worker_document_id} onChange={(e) => setCaseForm((prev) => ({ ...prev, worker_document_id: Number(e.target.value) }))} disabled={!moduleState.can_register_cases}>
                <option value={0}>Selecciona un trabajador registrado</option>
                {workers.map((worker) => (
                  <option key={worker.document_id} value={worker.document_id}>
                    {worker.full_name} · {worker.job}
                  </option>
                ))}
              </select>

              <input type="datetime-local" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.happened_at} onChange={(e) => setCaseForm((prev) => ({ ...prev, happened_at: e.target.value }))} disabled={!moduleState.can_register_cases} />
            </div>

            {selectedWorker && (
              <div className="rounded-2xl border border-slate-200 bg-white/70 p-4 text-sm dark:border-white/10 dark:bg-slate-900/50">
                <div><strong>Trabajador:</strong> {selectedWorker.full_name}</div>
                <div><strong>Cédula:</strong> {selectedWorker.id_number || "sin registrar"}</div>
                <div><strong>Puesto de trabajo:</strong> {selectedWorker.job}</div>
              </div>
            )}

            <input type="text" placeholder="Lugar del evento" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.place} onChange={(e) => setCaseForm((prev) => ({ ...prev, place: e.target.value }))} disabled={!moduleState.can_register_cases} />

            <div className="grid gap-3 md:grid-cols-2">
              <textarea rows={4} placeholder="Descripción del evento" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.description} onChange={(e) => setCaseForm((prev) => ({ ...prev, description: e.target.value }))} disabled={!moduleState.can_register_cases} />
              <textarea rows={4} placeholder="Consecuencias" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.consequences} onChange={(e) => setCaseForm((prev) => ({ ...prev, consequences: e.target.value }))} disabled={!moduleState.can_register_cases} />
              <textarea rows={4} placeholder="Testigos" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.witnesses} onChange={(e) => setCaseForm((prev) => ({ ...prev, witnesses: e.target.value }))} disabled={!moduleState.can_register_cases} />
              <textarea rows={4} placeholder="Causas" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.causes} onChange={(e) => setCaseForm((prev) => ({ ...prev, causes: e.target.value }))} disabled={!moduleState.can_register_cases} />
              <textarea rows={4} placeholder="Acciones inmediatas" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.immediate_actions} onChange={(e) => setCaseForm((prev) => ({ ...prev, immediate_actions: e.target.value }))} disabled={!moduleState.can_register_cases} />
              <textarea rows={4} placeholder="Acciones correctivas" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.corrective_actions} onChange={(e) => setCaseForm((prev) => ({ ...prev, corrective_actions: e.target.value }))} disabled={!moduleState.can_register_cases} />
            </div>

            <textarea rows={4} placeholder="Acciones preventivas" className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70" value={caseForm.preventive_actions} onChange={(e) => setCaseForm((prev) => ({ ...prev, preventive_actions: e.target.value }))} disabled={!moduleState.can_register_cases} />

            <label className="inline-flex items-center gap-2 text-sm text-slate-700 dark:text-slate-200">
              <input type="checkbox" checked={Boolean(caseForm.reported_to_authority)} onChange={(e) => setCaseForm((prev) => ({ ...prev, reported_to_authority: e.target.checked }))} disabled={!moduleState.can_register_cases} />
              Reportado a la autoridad competente
            </label>

            <button type="submit" className="btn-primary disabled:opacity-60" disabled={savingCaseState || !moduleState.can_register_cases}>
              {savingCaseState ? "Guardando..." : editingCaseId ? "Actualizar caso" : "Registrar caso"}
            </button>
          </form>
          <div className="surface space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                Ficha individual del trabajador
              </h2>
              <p className="mt-2 text-sm text-slate-600 dark:text-slate-300">
                Aquí puedes revisar el historial completo del trabajador dentro del sistema.
              </p>
            </div>

            <select
              className="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm dark:border-white/10 dark:bg-slate-900/70"
              value={selectedWorkerProfileId}
              onChange={(e) => setSelectedWorkerProfileId(Number(e.target.value))}
              disabled={workers.length === 0}
            >
              <option value={0}>Selecciona un trabajador</option>
              {workers.map((worker) => (
                <option key={worker.document_id} value={worker.document_id}>
                  {worker.full_name} · {worker.job}
                </option>
              ))}
            </select>

            {selectedWorkerForProfile && (
              <div className="space-y-4 rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">
                      Trabajador
                    </div>
                    <div className="mt-1 font-medium text-slate-900 dark:text-white">
                      {selectedWorkerForProfile.full_name}
                    </div>
                  </div>

                  <div>
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">
                      Puesto
                    </div>
                    <div className="mt-1 font-medium text-slate-900 dark:text-white">
                      {selectedWorkerForProfile.job}
                    </div>
                  </div>

                  <div>
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">
                      Cédula
                    </div>
                    <div className="mt-1 font-medium text-slate-900 dark:text-white">
                      {selectedWorkerForProfile.id_number || "sin registrar"}
                    </div>
                  </div>

                  <div>
                    <div className="text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">
                      Fecha de ingreso
                    </div>
                    <div className="mt-1 font-medium text-slate-900 dark:text-white">
                      {selectedWorkerForProfile.start_date || "sin registrar"}
                    </div>
                  </div>
                </div>
                <div className="flex gap-2 flex-wrap">
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => startCaseForWorker(selectedWorkerForProfile.document_id)}
                  >
                    Registrar investigación
                  </button>

                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={() => startEppForWorker(selectedWorkerForProfile.document_id)}
                  >
                    Registrar entrega EPP
                  </button>
                </div>
                <div>
                  <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">
                    EPP sugerido por el puesto
                  </div>

                  {selectedWorkerForProfile.recommended_epp?.length ? (
                    <div className="flex flex-wrap gap-2">
                      {selectedWorkerForProfile.recommended_epp.map((item) => (
                        <span key={item} className="chip">
                          {item}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <div className="muted text-sm">
                      Este puesto todavía no tiene EPP sugerido desde la IPERC.
                    </div>
                  )}
                </div>

                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">
                      Incidentes / accidentes
                    </div>
                    {selectedWorkerCases.length === 0 ? (
                      <div className="muted text-sm">No hay casos registrados para este trabajador.</div>
                    ) : (
                      <div className="space-y-2">
                        {selectedWorkerCases.map((item) => (
                          <div
                            key={item.document_id}
                            className="rounded-xl border border-slate-200 bg-white/70 p-3 text-sm dark:border-white/10 dark:bg-slate-900/50"
                          >
                            <div className="font-medium text-slate-900 dark:text-white">
                              {item.event_type} · {item.status}
                            </div>
                            <div className="muted mt-1 text-xs">
                              {item.happened_at || "sin fecha"} · {item.place || "sin lugar"}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  <div>
                    <div className="mb-2 text-xs uppercase tracking-[0.18em] text-slate-500 dark:text-white/50">
                      Entregas de EPP
                    </div>
                    {selectedWorkerEppDeliveries.length === 0 ? (
                      <div className="muted text-sm">No hay entregas de EPP registradas para este trabajador.</div>
                    ) : (
                      <div className="space-y-2">
                        {selectedWorkerEppDeliveries.map((item) => (
                          <div
                            key={item.document_id}
                            className="rounded-xl border border-slate-200 bg-white/70 p-3 text-sm dark:border-white/10 dark:bg-slate-900/50"
                          >
                            <div className="font-medium text-slate-900 dark:text-white">
                              {item.delivery_date || "sin fecha"}
                            </div>
                            <div className="muted mt-1 text-xs whitespace-pre-wrap">
                              {item.items_text || "sin detalle"}
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
          <div className="surface space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Trabajadores registrados</h2>
            </div>

            {workers.length === 0 ? (
              <div className="empty-state">
                <div className="text-base font-medium text-slate-900 dark:text-white">Todavía no hay trabajadores registrados.</div>
                <div className="muted mt-2">Primero completa IPERC y luego registra trabajadores en este módulo.</div>
              </div>
            ) : (
              <div className="space-y-3">
                {workers.map((worker) => (
                  <div
                    key={worker.document_id}
                    className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50"
                  >
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div>
                        <div className="font-medium text-slate-900 dark:text-white">
                          {worker.full_name}
                        </div>
                        <div className="muted mt-1 text-xs">
                          {worker.job} · {worker.id_number || "sin cédula"} ·
                          {" "}Incidentes/accidentes: {worker.incident_count} ·
                          {" "}Entregas EPP: {worker.epp_delivery_count}
                        </div>
                      </div>

                      <div className="flex gap-2 flex-wrap">
                        <button
                          type="button"
                          className="btn-secondary text-sm"
                          onClick={() => openWorkerProfile(worker.document_id)}
                        >
                          Ver ficha
                        </button>

                        <button
                          type="button"
                          className="btn-primary text-sm"
                          onClick={() => startCaseForWorker(worker.document_id)}
                        >
                          Registrar investigación
                        </button>

                        <button
                          type="button"
                          className="btn-secondary text-sm"
                          onClick={() => startEppForWorker(worker.document_id)}
                        >
                          Registrar EPP
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="surface space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Casos registrados</h2>
            </div>

            {moduleState.cases.length === 0 ? (
              <div className="empty-state">
                <div className="text-base font-medium text-slate-900 dark:text-white">Todavía no hay casos registrados.</div>
              </div>
            ) : (
              <div className="space-y-3">
                {moduleState.cases.map((item) => (
                  <div key={item.document_id} className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div>
                        <div className="font-medium text-slate-900 dark:text-white">{item.title}</div>
                        <div className="muted mt-1 text-xs">
                          {item.event_type} · {item.status} · {item.worker_name} · {item.job_title}
                        </div>
                      </div>
                      <button type="button" className="btn-secondary text-sm" onClick={() => loadCaseIntoForm(item)}>
                        Cargar en formulario
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="surface space-y-4">
            <div>
              <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Entregas de EPP registradas</h2>
            </div>

            {moduleState.epp_deliveries.length === 0 ? (
              <div className="empty-state">
                <div className="text-base font-medium text-slate-900 dark:text-white">Todavía no hay entregas de EPP registradas.</div>
              </div>
            ) : (
              <div className="space-y-3">
                {moduleState.epp_deliveries.map((item) => (
                  <div key={item.document_id} className="rounded-2xl border border-slate-200 bg-white/70 p-4 dark:border-white/10 dark:bg-slate-900/50">
                    <div className="font-medium text-slate-900 dark:text-white">{item.worker_name}</div>
                    <div className="muted mt-1 text-xs">
                      {item.job} · {item.delivery_date || "sin fecha"} · {item.items_text}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      ) : null}
    </div>
  );
}