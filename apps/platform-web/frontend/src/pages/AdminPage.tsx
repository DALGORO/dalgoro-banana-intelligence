import { useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  createAdminUser,
  deleteAdminCompany,
  deleteAdminUser,
  getAdminAuditLogs,
  getAdminUserDetail,
  getAdminUsers,
  getAdminUserSubscription,
  hardDeleteAdminCompany,
  hardDeleteAdminUser,
  reassignAdminUserCompany,
  resetAdminUserPassword,
  restoreAdminCompany,
  restoreAdminUser,
  updateAdminUser,
  updateAdminUserSubscription,
} from "../app/api";

type SubscriptionInfo = {
  id?: number;
  plan?: string;
  status?: string;
  companies_quota?: number;
  free_trial_until?: string | null;
  current_period_end?: string | null;
  last_payment_at?: string | null;
  provider?: string | null;
  customer_ref?: string | null;
} | null;

type SubscriptionFormState = {
  plan: string;
  status: string;
  companies_quota: string;
  free_trial_until: string;
  current_period_end: string;
  last_payment_at: string;
  provider: string;
  customer_ref: string;
};

type CompanyRow = {
  id: number;
  ruc?: string;
  name?: string;
  activity?: string;
  workers?: number;
  risk_level?: string;
  is_deleted?: boolean;
  deleted_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

type AuditRow = {
  id: number;
  admin_user_id?: number | null;
  admin_email?: string | null;
  action: string;
  entity_type: string;
  entity_id?: number | null;
  target_user_id?: number | null;
  target_user_email?: string | null;
  company_id?: number | null;
  company_name?: string | null;
  description?: string | null;
  payload?: Record<string, any> | null;
  created_at?: string | null;
};

type UserRow = {
  id: number;
  full_name?: string | null;
  email: string;
  id_number?: string | null;
  phone?: string | null;
  is_active: boolean;
  role: string;
  is_deleted?: boolean;
  deleted_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  companies_count?: number;
  subscription?: SubscriptionInfo;
};

type UserDetail = UserRow & {
  companies: CompanyRow[];
  archived_companies: CompanyRow[];
};

type UserFormState = {
  full_name: string;
  email: string;
  id_number: string;
  phone: string;
  role: string;
  is_active: boolean;
  password: string;
};

const EMPTY_FORM: UserFormState = {
  full_name: "",
  email: "",
  id_number: "",
  phone: "",
  role: "SUBSCRIBER",
  is_active: true,
  password: "",
};

const EMPTY_SUBSCRIPTION_FORM: SubscriptionFormState = {
  plan: "",
  status: "ACTIVE",
  companies_quota: "1",
  free_trial_until: "",
  current_period_end: "",
  last_payment_at: "",
  provider: "KUSHKI",
  customer_ref: "",
};

function toDateTimeLocal(value?: string | null) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hours = String(d.getHours()).padStart(2, "0");
  const minutes = String(d.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day}T${hours}:${minutes}`;
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("es-EC");
}

function compactText(value?: string | null) {
  const text = String(value ?? "").trim();
  return text || "—";
}

function subscriptionSummary(sub?: SubscriptionInfo) {
  if (!sub) return "Sin suscripción";
  const plan = String(sub.plan ?? "Sin plan");
  const status = String(sub.status ?? "Sin estado");
  return `${plan} · ${status}`;
}

function buildUpdatePayload(form: UserFormState) {
  return {
    full_name: form.full_name.trim() || null,
    email: form.email.trim() || null,
    id_number: form.id_number.trim() || null,
    phone: form.phone.trim() || null,
    role: form.role.trim() || null,
    is_active: !!form.is_active,
  };
}

export default function AdminPage() {
  const navigate = useNavigate();

  const [authorized, setAuthorized] = useState<"checking" | "yes" | "no">("checking");

  const [users, setUsers] = useState<UserRow[]>([]);
  const [loadingUsers, setLoadingUsers] = useState(false);

  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState<"" | "true" | "false">("");

  const [archivedModeFilter, setArchivedModeFilter] = useState<"active" | "archived" | "all">("active");

  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [detail, setDetail] = useState<UserDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const [formMode, setFormMode] = useState<"create" | "edit" | null>(null);
  const [editingUserId, setEditingUserId] = useState<number | null>(null);
  const [form, setForm] = useState<UserFormState>(EMPTY_FORM);
  const [savingForm, setSavingForm] = useState(false);

  const [passwordTarget, setPasswordTarget] = useState<UserRow | null>(null);
  const [passwordValue, setPasswordValue] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [reassigningCompanyId, setReassigningCompanyId] = useState<number | null>(null);
  const [deletingCompanyId, setDeletingCompanyId] = useState<number | null>(null);
  const [editingSubscription, setEditingSubscription] = useState(false);
  const [savingSubscription, setSavingSubscription] = useState(false);
  const [subscriptionForm, setSubscriptionForm] = useState<SubscriptionFormState>(EMPTY_SUBSCRIPTION_FORM);

  const [auditLogs, setAuditLogs] = useState<AuditRow[]>([]);
  const [loadingAuditLogs, setLoadingAuditLogs] = useState(false);
  const [auditQuery, setAuditQuery] = useState("");
  const [auditActionFilter, setAuditActionFilter] = useState("");
  
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const selectedUser = useMemo(
    () => users.find((u) => u.id === selectedUserId) ?? null,
    [users, selectedUserId]
  );

  const resetMessages = () => {
    setError(null);
    setSuccess(null);
  };

  const loadUsers = async () => {
    setLoadingUsers(true);
    resetMessages();

    try {
      const params: {
        q?: string;
        role?: string;
        is_active?: boolean;
        archived_mode?: "active" | "archived" | "all";
      } = {
        archived_mode: archivedModeFilter,
      };

      if (query.trim()) params.q = query.trim();
      if (roleFilter.trim()) params.role = roleFilter.trim();
      if (statusFilter === "true") params.is_active = true;
      if (statusFilter === "false") params.is_active = false;

      const { data } = await getAdminUsers(params);
      const rows = Array.isArray(data) ? data : [];
      setUsers(rows);

      if (rows.length === 0) {
        setSelectedUserId(null);
        setDetail(null);
        return;
      }

      if (!selectedUserId || !rows.some((u: UserRow) => u.id === selectedUserId)) {
        setSelectedUserId(rows[0].id);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo cargar la lista de usuarios.");
    } finally {
      setLoadingUsers(false);
    }
  };

  const loadAuditLogs = async () => {
    setLoadingAuditLogs(true);

    try {
      const params: {
        q?: string;
        action?: string;
        limit?: number;
        target_user_id?: number;
      } = {
        limit: 100,
      };

      if (auditQuery.trim()) params.q = auditQuery.trim();
      if (auditActionFilter.trim()) params.action = auditActionFilter.trim();
      if (selectedUserId) params.target_user_id = selectedUserId;

      const { data } = await getAdminAuditLogs(params);
      setAuditLogs(Array.isArray(data) ? data : []);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo cargar la bitácora administrativa.");
    } finally {
      setLoadingAuditLogs(false);
    }
  };

  const loadUserDetail = async (userId: number) => {
    setLoadingDetail(true);

    try {
      const { data } = await getAdminUserDetail(userId);
      setDetail(data ?? null);

      const sub = data?.subscription ?? null;
      setSubscriptionForm({
        plan: sub?.plan ?? "",
        status: sub?.status ?? "ACTIVE",
        companies_quota: String(sub?.companies_quota ?? 1),
        free_trial_until: toDateTimeLocal(sub?.free_trial_until),
        current_period_end: toDateTimeLocal(sub?.current_period_end),
        last_payment_at: toDateTimeLocal(sub?.last_payment_at),
        provider: sub?.provider ?? "KUSHKI",
        customer_ref: sub?.customer_ref ?? "",
      });
    } catch (err: any) {
      setDetail(null);
      setError(err?.response?.data?.detail ?? "No se pudo cargar el detalle del usuario.");
    } finally {
      setLoadingDetail(false);
    }
  };

  useEffect(() => {
    let active = true;

    api.get("/api/v1/auth/me")
      .then((r) => {
        if (!active) return;
        const roles = Array.isArray(r.data?.roles) ? r.data.roles : [];
        setAuthorized(roles.includes("ADMIN") ? "yes" : "no");
      })
      .catch(() => {
        if (!active) return;
        setAuthorized("no");
      });

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (authorized !== "yes") return;
    loadUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authorized]);

  useEffect(() => {
    if (authorized !== "yes") return;
    if (!selectedUserId) return;
    loadUserDetail(selectedUserId);
  }, [authorized, selectedUserId]);

  useEffect(() => {
    if (authorized !== "yes") return;
    loadAuditLogs();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [authorized, selectedUserId]);

  const openCreateForm = () => {
    resetMessages();
    setFormMode("create");
    setEditingUserId(null);
    setPasswordTarget(null);
    setForm(EMPTY_FORM);
  };

  const openEditForm = (user: UserRow) => {
    resetMessages();
    setFormMode("edit");
    setEditingUserId(user.id);
    setPasswordTarget(null);
    setForm({
      full_name: user.full_name ?? "",
      email: user.email ?? "",
      id_number: user.id_number ?? "",
      phone: user.phone ?? "",
      role: user.role ?? "SUBSCRIBER",
      is_active: !!user.is_active,
      password: "",
    });
  };

  const closeForm = () => {
    setFormMode(null);
    setEditingUserId(null);
    setForm(EMPTY_FORM);
  };

  const submitForm = async (e: FormEvent) => {
    e.preventDefault();
    resetMessages();
    setSavingForm(true);

    try {
      if (formMode === "create") {
        const { data } = await createAdminUser({
          full_name: form.full_name.trim() || null,
          email: form.email.trim(),
          id_number: form.id_number.trim() || null,
          phone: form.phone.trim() || null,
          role: form.role.trim(),
          is_active: !!form.is_active,
          password: form.password,
        });

        setSuccess("Usuario creado correctamente.");
        closeForm();
        await loadUsers();
        if (data?.id) setSelectedUserId(data.id);
      }

      if (formMode === "edit" && editingUserId) {
        await updateAdminUser(editingUserId, buildUpdatePayload(form));
        setSuccess("Usuario actualizado correctamente.");
        closeForm();
        await loadUsers();
        setSelectedUserId(editingUserId);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo guardar el usuario.");
    } finally {
      setSavingForm(false);
    }
  };

  const toggleActive = async (user: UserRow) => {
    resetMessages();

    try {
      await updateAdminUser(user.id, { is_active: !user.is_active });
      setSuccess(user.is_active ? "Usuario desactivado correctamente." : "Usuario activado correctamente.");
      await loadUsers();
      if (selectedUserId === user.id) await loadUserDetail(user.id);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo cambiar el estado del usuario.");
    }
  };

  const archiveUser = async (user: UserRow) => {
    const ok = window.confirm(`¿Seguro que deseas archivar al usuario ${user.email}?`);
    if (!ok) return;

    resetMessages();

    try {
      await deleteAdminUser(user.id);
      setSuccess("Usuario archivado correctamente.");
      if (selectedUserId === user.id) {
        setSelectedUserId(null);
        setDetail(null);
      }
      await loadUsers();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo archivar el usuario.");
    }
  };

  const restoreUser = async (user: UserRow) => {
    resetMessages();

    try {
      await restoreAdminUser(user.id);
      setSuccess("Usuario restaurado correctamente.");
      await loadUsers();
      setSelectedUserId(user.id);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo restaurar el usuario.");
    }
  };

  const hardDeleteUser = async (user: UserRow) => {
    const ok = window.confirm(`¿Seguro que deseas eliminar definitivamente al usuario ${user.email}? Esta acción no se puede deshacer.`);
    if (!ok) return;

    resetMessages();

    try {
      await hardDeleteAdminUser(user.id);
      setSuccess("Usuario eliminado definitivamente.");
      if (selectedUserId === user.id) {
        setSelectedUserId(null);
        setDetail(null);
      }
      await loadUsers();
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo eliminar definitivamente el usuario.");
    }
  };

  const submitPasswordReset = async (e: FormEvent) => {
    e.preventDefault();
    if (!passwordTarget) return;

    resetMessages();
    setSavingPassword(true);

    try {
      await resetAdminUserPassword(passwordTarget.id, passwordValue);
      setSuccess("Contraseña actualizada correctamente.");
      setPasswordTarget(null);
      setPasswordValue("");
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo cambiar la contraseña.");
    } finally {
      setSavingPassword(false);
    }
  };

  if (authorized === "checking") {
    return (
      <div className="card">
        <h1>Administración de usuarios</h1>
        <p className="muted mt-2">Verificando permisos…</p>
      </div>
    );
  }

  if (authorized === "no") {
    return (
      <div className="card">
        <h1>Acceso restringido</h1>
        <p className="muted mt-2">
          Esta pantalla está disponible únicamente para administradores del sistema.
        </p>
        <div className="mt-4">
          <button className="btn-primary" onClick={() => navigate("/companies")}>
            Volver a empresas
          </button>
        </div>
      </div>
    );
  }

  const saveSubscriptionHandler = async (e: FormEvent) => {
    e.preventDefault();
    if (!selectedUserId) return;

    resetMessages();
    setSavingSubscription(true);

    try {
      await updateAdminUserSubscription(selectedUserId, {
        plan: subscriptionForm.plan.trim() || null,
        status: subscriptionForm.status.trim() || null,
        companies_quota: subscriptionForm.companies_quota.trim()
          ? Number(subscriptionForm.companies_quota)
          : null,
        free_trial_until: subscriptionForm.free_trial_until.trim() || null,
        current_period_end: subscriptionForm.current_period_end.trim() || null,
        last_payment_at: subscriptionForm.last_payment_at.trim() || null,
        provider: subscriptionForm.provider.trim() || null,
        customer_ref: subscriptionForm.customer_ref.trim() || null,
      });

      const refreshed = await getAdminUserSubscription(selectedUserId);
      const sub = refreshed.data ?? null;

      setSubscriptionForm({
        plan: sub?.plan ?? "",
        status: sub?.status ?? "ACTIVE",
        companies_quota: String(sub?.companies_quota ?? 1),
        free_trial_until: toDateTimeLocal(sub?.free_trial_until),
        current_period_end: toDateTimeLocal(sub?.current_period_end),
        last_payment_at: toDateTimeLocal(sub?.last_payment_at),
        provider: sub?.provider ?? "KUSHKI",
        customer_ref: sub?.customer_ref ?? "",
      });

      setSuccess("Suscripción actualizada correctamente.");
      setEditingSubscription(false);

      await loadUsers();
      await loadUserDetail(selectedUserId);
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo actualizar la suscripción.");
    } finally {
      setSavingSubscription(false);
    }
  };

  const handleReassignCompany = async (companyId: number) => {
    if (!selectedUserId) return;

    const targetText = window.prompt("Ingresa el ID del usuario destino:");
    if (!targetText) return;

    const newOwnerUserId = Number(targetText);
    if (!Number.isFinite(newOwnerUserId) || newOwnerUserId <= 0) {
      setError("Debes ingresar un ID de usuario destino válido.");
      return;
    }

    resetMessages();
    setReassigningCompanyId(companyId);

    try {
      await reassignAdminUserCompany(selectedUserId, companyId, newOwnerUserId);
      setSuccess("Empresa reasignada correctamente.");
      await loadUsers();
      if (selectedUserId) {
        await loadUserDetail(selectedUserId);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo reasignar la empresa.");
    } finally {
      setReassigningCompanyId(null);
    }
  };

  const handleDeleteCompany = async (companyId: number, companyName?: string) => {
    const label = String(companyName ?? "").trim() || `ID ${companyId}`;
    const confirmation = window.confirm(
      `¿Seguro que deseas archivar la empresa ${label}?`
    );

    if (!confirmation) return;

    resetMessages();
    setDeletingCompanyId(companyId);

    try {
      await deleteAdminCompany(companyId);
      setSuccess("Empresa archivada correctamente.");
      await loadUsers();

      if (selectedUserId) {
        await loadUserDetail(selectedUserId);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo archivar la empresa.");
    } finally {
      setDeletingCompanyId(null);
    }
  };

  const handleRestoreCompany = async (companyId: number) => {
    resetMessages();
    setDeletingCompanyId(companyId);

    try {
      await restoreAdminCompany(companyId);
      setSuccess("Empresa restaurada correctamente.");
      await loadUsers();
      if (selectedUserId) {
        await loadUserDetail(selectedUserId);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo restaurar la empresa.");
    } finally {
      setDeletingCompanyId(null);
    }
  };

  const handleHardDeleteCompany = async (companyId: number, companyName?: string) => {
    const label = String(companyName ?? "").trim() || `ID ${companyId}`;
    const confirmation = window.confirm(
      `¿Seguro que deseas eliminar definitivamente la empresa ${label}? Esta acción no se puede deshacer.`
    );

    if (!confirmation) return;

    resetMessages();
    setDeletingCompanyId(companyId);

    try {
      await hardDeleteAdminCompany(companyId);
      setSuccess("Empresa eliminada definitivamente.");
      await loadUsers();
      if (selectedUserId) {
        await loadUserDetail(selectedUserId);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail ?? "No se pudo eliminar definitivamente la empresa.");
    } finally {
      setDeletingCompanyId(null);
    }
  };

  return (
    <div className="grid gap-6">
      <section className="card">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1>Administración de usuarios</h1>
            <p className="muted mt-1 text-sm">
              Busca, edita, activa, desactiva, cambia contraseñas y revisa las empresas de cada usuario.
            </p>
          </div>

          <div className="flex gap-2 flex-wrap">
            <button
              className="btn-secondary"
              onClick={async () => {
                await loadUsers();
                await loadAuditLogs();
              }}
              disabled={loadingUsers || loadingAuditLogs}
            >
              {loadingUsers || loadingAuditLogs ? "Actualizando..." : "Actualizar lista"}
            </button>

            <button className="btn-primary" onClick={openCreateForm}>
              Nuevo usuario
            </button>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-5">
          <div className="md:col-span-2">
            <label className="block text-sm mb-1">Buscar por nombre, correo o cédula</label>
            <input
              className="input w-full"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ej.: Darwin, correo@dominio.com o 0701234567"
            />
          </div>

          <div>
            <label className="block text-sm mb-1">Rol</label>
            <select
              className="input w-full"
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
            >
              <option value="">Todos</option>
              <option value="ADMIN">ADMIN</option>
              <option value="SUBSCRIBER">SUBSCRIBER</option>
              <option value="PENDING">PENDING</option>
            </select>
          </div>

          <div>
            <label className="block text-sm mb-1">Estado</label>
            <select
              className="input w-full"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as "" | "true" | "false")}
            >
              <option value="">Todos</option>
              <option value="true">Activos</option>
              <option value="false">Inactivos</option>
            </select>
          </div>

          <div>
            <label className="block text-sm mb-1">Archivado</label>
            <select
              className="input w-full"
              value={archivedModeFilter}
              onChange={(e) => setArchivedModeFilter(e.target.value as "active" | "archived" | "all")}
            >
              <option value="active">Activos</option>
              <option value="archived">Archivados</option>
              <option value="all">Todos</option>
            </select>
          </div>

        </div>

        <div className="mt-3 flex gap-2 flex-wrap">
          <button className="btn-primary" onClick={loadUsers} disabled={loadingUsers}>
            {loadingUsers ? "Buscando..." : "Aplicar filtros"}
          </button>
          <button
            className="btn-secondary"
            onClick={() => {
              setQuery("");
              setRoleFilter("");
              setStatusFilter("");
              setArchivedModeFilter("active");
              setTimeout(() => loadUsers(), 0);
            }}
          >
            Limpiar filtros
          </button>
        </div>

        {error && (
          <div className="status-banner status-banner-danger mt-4 text-sm">
            {error}
          </div>
        )}

        {success && (
          <div className="status-banner status-banner-success mt-4 text-sm">
            {success}
          </div>
        )}

        <div className="mt-5 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-white/10">
                <th className="py-3 pr-3 text-left">Usuario</th>
                <th className="py-3 pr-3 text-left">Correo</th>
                <th className="py-3 pr-3 text-left">Cédula</th>
                <th className="py-3 pr-3 text-left">Rol</th>
                <th className="py-3 pr-3 text-left">Estado</th>
                <th className="py-3 pr-3 text-left">Empresas</th>
                <th className="py-3 pr-3 text-left">Suscripción</th>
                <th className="py-3 text-left">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr
                  key={u.id}
                  className={`border-b border-slate-100 align-top dark:border-white/5 ${
                    selectedUserId === u.id ? "bg-slate-50 dark:bg-white/[0.03]" : ""
                  }`}
                >
                  <td className="py-3 pr-3">
                    <div className="font-medium text-slate-900 dark:text-white">
                      {compactText(u.full_name)}
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">
                      ID interno: {u.id}
                    </div>
                  </td>
                  <td className="py-3 pr-3">{u.email}</td>
                  <td className="py-3 pr-3">{compactText(u.id_number)}</td>
                  <td className="py-3 pr-3">{u.role}</td>
                  <td className="py-3 pr-3">
                    {u.is_active ? "Activo" : "Inactivo"}
                  </td>
                  <td className="py-3 pr-3">{u.companies_count ?? 0}</td>
                  <td className="py-3 pr-3">{subscriptionSummary(u.subscription)}</td>
                  <td className="py-3">
                    <div className="flex gap-2 flex-wrap">
                      <button className="btn-secondary" onClick={() => setSelectedUserId(u.id)}>
                        Ver detalle
                      </button>

                      {!u.is_deleted && (
                        <>
                          <button className="btn-secondary" onClick={() => openEditForm(u)}>
                            Editar
                          </button>

                          <button className="btn-secondary" onClick={() => {
                            setPasswordTarget(u);
                            setPasswordValue("");
                            setFormMode(null);
                            resetMessages();
                          }}>
                            Clave
                          </button>

                          <button className="btn-secondary" onClick={() => toggleActive(u)}>
                            {u.is_active ? "Desactivar" : "Activar"}
                          </button>

                          <button className="btn-danger" onClick={() => archiveUser(u)}>
                            Archivar
                          </button>
                        </>
                      )}

                      {u.is_deleted && (
                        <>
                          <button className="btn-secondary" onClick={() => restoreUser(u)}>
                            Restaurar
                          </button>

                          <button className="btn-danger" onClick={() => hardDeleteUser(u)}>
                            Eliminar definitivo
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}

              {!loadingUsers && users.length === 0 && (
                <tr>
                  <td className="py-4 text-sm text-slate-500" colSpan={8}>
                    No hay usuarios que coincidan con los filtros aplicados.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {detail && (
        <section className="card">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-xl font-semibold">Detalle del usuario</h2>
              <p className="muted text-sm mt-1">
                Información ampliada, suscripción y empresas administradas.
              </p>
            </div>

            {selectedUser && (
              <div className="flex gap-2 flex-wrap">
                <button className="btn-secondary" onClick={() => openEditForm(selectedUser)}>
                  Editar este usuario
                </button>
                <button className="btn-secondary" onClick={() => {
                  setPasswordTarget(selectedUser);
                  setPasswordValue("");
                  resetMessages();
                }}>
                  Cambiar clave
                </button>
              </div>
            )}
          </div>

          {loadingDetail ? (
            <div className="muted mt-4">Cargando detalle…</div>
          ) : (
            <>
              <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Nombre</div>
                  <div className="mt-1 font-medium">{compactText(detail.full_name)}</div>
                </div>

                <div className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Correo</div>
                  <div className="mt-1 font-medium">{detail.email}</div>
                </div>

                <div className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Cédula</div>
                  <div className="mt-1 font-medium">{compactText(detail.id_number)}</div>
                </div>

                <div className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Teléfono</div>
                  <div className="mt-1 font-medium">{compactText(detail.phone)}</div>
                </div>

                <div className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Rol</div>
                  <div className="mt-1 font-medium">{detail.role}</div>
                </div>

                <div className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Estado</div>
                  <div className="mt-1 font-medium">{detail.is_active ? "Activo" : "Inactivo"}</div>
                </div>

                <div className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Creado</div>
                  <div className="mt-1 font-medium">{formatDate(detail.created_at)}</div>
                </div>

                <div className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="text-xs uppercase tracking-wide text-slate-500">Actualizado</div>
                  <div className="mt-1 font-medium">{formatDate(detail.updated_at)}</div>
                </div>
              </div>

              <div className="mt-6 grid gap-6 xl:grid-cols-[1.1fr_1.4fr]">
                <div className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="font-semibold">Suscripción</h3>

                    <button
                      className="btn-secondary"
                      type="button"
                      onClick={() => setEditingSubscription((prev) => !prev)}
                    >
                      {editingSubscription ? "Cerrar edición" : "Editar suscripción"}
                    </button>
                  </div>

                  {!detail.subscription ? (
                    <p className="muted mt-3 text-sm">
                      Este usuario no tiene suscripción registrada. Puedes crearla y guardarla desde esta misma sección.
                    </p>
                  ) : (
                    <div className="mt-4 space-y-2 text-sm">
                      <div><strong>Plan:</strong> {compactText(detail.subscription.plan)}</div>
                      <div><strong>Estado:</strong> {compactText(detail.subscription.status)}</div>
                      <div><strong>Cupo de empresas:</strong> {detail.subscription.companies_quota ?? "—"}</div>
                      <div><strong>Trial hasta:</strong> {formatDate(detail.subscription.free_trial_until)}</div>
                      <div><strong>Periodo actual hasta:</strong> {formatDate(detail.subscription.current_period_end)}</div>
                      <div><strong>Último pago:</strong> {formatDate(detail.subscription.last_payment_at)}</div>
                      <div><strong>Proveedor:</strong> {compactText(detail.subscription.provider)}</div>
                      <div><strong>Referencia cliente:</strong> {compactText(detail.subscription.customer_ref)}</div>
                    </div>
                  )}

                  {editingSubscription && (
                    <form className="mt-5 grid gap-4" onSubmit={saveSubscriptionHandler}>
                      <div className="grid gap-4 md:grid-cols-2">
                        <div>
                          <label className="block text-sm mb-1">Plan</label>
                          <select
                            className="input w-full"
                            value={subscriptionForm.plan}
                            onChange={(e) => setSubscriptionForm((prev) => ({ ...prev, plan: e.target.value }))}
                          >
                            <option value="FREE_TRIAL">FREE_TRIAL</option>
                            <option value="BASE_PLAN">BASE_PLAN</option>
                            <option value="PRO">PRO</option>
                            <option value="ENTERPRISE">ENTERPRISE</option>
                          </select>
                        </div>

                        <div>
                          <label className="block text-sm mb-1">Estado</label>
                          <select
                            className="input w-full"
                            value={subscriptionForm.status}
                            onChange={(e) => setSubscriptionForm((prev) => ({ ...prev, status: e.target.value }))}
                          >
                            <option value="ACTIVE">ACTIVE</option>
                            <option value="PAST_DUE">PAST_DUE</option>
                            <option value="CANCELED">CANCELED</option>
                          </select>
                        </div>

                        <div>
                          <label className="block text-sm mb-1">Cupo de empresas</label>
                          <input
                            className="input w-full"
                            type="number"
                            min={0}
                            value={subscriptionForm.companies_quota}
                            onChange={(e) => setSubscriptionForm((prev) => ({ ...prev, companies_quota: e.target.value }))}
                          />
                        </div>

                        <div>
                          <label className="block text-sm mb-1">Proveedor</label>
                          <input
                            className="input w-full"
                            value={subscriptionForm.provider}
                            onChange={(e) => setSubscriptionForm((prev) => ({ ...prev, provider: e.target.value }))}
                          />
                        </div>

                        <div>
                          <label className="block text-sm mb-1">Trial hasta</label>
                          <input
                            className="input w-full"
                            type="datetime-local"
                            value={subscriptionForm.free_trial_until}
                            onChange={(e) => setSubscriptionForm((prev) => ({ ...prev, free_trial_until: e.target.value }))}
                          />
                        </div>

                        <div>
                          <label className="block text-sm mb-1">Periodo actual hasta</label>
                          <input
                            className="input w-full"
                            type="datetime-local"
                            value={subscriptionForm.current_period_end}
                            onChange={(e) => setSubscriptionForm((prev) => ({ ...prev, current_period_end: e.target.value }))}
                          />
                        </div>

                        <div>
                          <label className="block text-sm mb-1">Último pago</label>
                          <input
                            className="input w-full"
                            type="datetime-local"
                            value={subscriptionForm.last_payment_at}
                            onChange={(e) => setSubscriptionForm((prev) => ({ ...prev, last_payment_at: e.target.value }))}
                          />
                        </div>

                        <div>
                          <label className="block text-sm mb-1">Referencia cliente</label>
                          <input
                            className="input w-full"
                            value={subscriptionForm.customer_ref}
                            onChange={(e) => setSubscriptionForm((prev) => ({ ...prev, customer_ref: e.target.value }))}
                          />
                        </div>
                      </div>

                      <div className="flex gap-2 flex-wrap">
                        <button className="btn-primary" type="submit" disabled={savingSubscription}>
                          {savingSubscription ? "Guardando..." : "Guardar suscripción"}
                        </button>

                        <button
                          className="btn-secondary"
                          type="button"
                          onClick={() => setEditingSubscription(false)}
                        >
                          Cancelar
                        </button>
                      </div>
                    </form>
                  )}
                </div>

                <div className="rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="font-semibold">Empresas del usuario</h3>
                    <span className="text-sm text-slate-500">
                      {detail.companies?.length ?? 0} registradas
                    </span>
                  </div>

                  <div className="mt-4 space-y-3">
                    {Array.isArray(detail.companies) && detail.companies.length > 0 ? (
                      detail.companies.map((company) => (
                        <div
                          key={company.id}
                          className="rounded-xl border border-slate-200 p-3 dark:border-white/10"
                        >
                          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                            <div>
                              <div className="font-medium">{compactText(company.name)}</div>
                              <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                                RUC: {compactText(company.ruc)} · Actividad: {compactText(company.activity)} · Riesgo: {compactText(company.risk_level)}
                              </div>
                              <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                Trabajadores: {company.workers ?? 0} · Creada: {formatDate(company.created_at)}
                              </div>
                            </div>

                            <div className="flex gap-2 flex-wrap">
                              <button
                                className="btn-secondary"
                                onClick={() => navigate(`/companies/${company.id}`)}
                              >
                                Abrir empresa
                              </button>

                              <button
                                className="btn-secondary"
                                onClick={() => navigate(`/companies/${company.id}/documents`)}
                              >
                                Documentos
                              </button>

                              <button
                                className="btn-secondary"
                                disabled={reassigningCompanyId === company.id}
                                onClick={() => handleReassignCompany(company.id)}
                              >
                                {reassigningCompanyId === company.id ? "Reasignando..." : "Reasignar"}
                              </button>

                              <button
                                className="btn-danger"
                                disabled={deletingCompanyId === company.id}
                                onClick={() => handleDeleteCompany(company.id, company.name)}
                              >
                                {deletingCompanyId === company.id ? "Archivando..." : "Archivar empresa"}
                              </button>
                            </div>
                            <div className="mt-6 rounded-2xl border border-slate-200 p-4 dark:border-white/10">
                              <div className="flex items-center justify-between gap-3">
                                <h3 className="font-semibold">Empresas archivadas del usuario</h3>
                                <span className="text-sm text-slate-500">
                                  {detail.archived_companies?.length ?? 0} archivadas
                                </span>
                              </div>

                              <div className="mt-4 space-y-3">
                                {Array.isArray(detail.archived_companies) && detail.archived_companies.length > 0 ? (
                                  detail.archived_companies.map((company) => (
                                    <div
                                      key={company.id}
                                      className="rounded-xl border border-slate-200 p-3 dark:border-white/10"
                                    >
                                      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                                        <div>
                                          <div className="font-medium">{compactText(company.name)}</div>
                                          <div className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                                            RUC: {compactText(company.ruc)} · Actividad: {compactText(company.activity)} · Riesgo: {compactText(company.risk_level)}
                                          </div>
                                          <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                                            Archivada: {formatDate(company.deleted_at)}
                                          </div>
                                        </div>

                                        <div className="flex gap-2 flex-wrap">
                                          <button
                                            className="btn-secondary"
                                            disabled={deletingCompanyId === company.id}
                                            onClick={() => handleRestoreCompany(company.id)}
                                          >
                                            {deletingCompanyId === company.id ? "Procesando..." : "Restaurar"}
                                          </button>

                                          <button
                                            className="btn-danger"
                                            disabled={deletingCompanyId === company.id}
                                            onClick={() => handleHardDeleteCompany(company.id, company.name)}
                                          >
                                            {deletingCompanyId === company.id ? "Procesando..." : "Eliminar definitivo"}
                                          </button>
                                        </div>
                                      </div>
                                    </div>
                                  ))
                                ) : (
                                  <div className="text-sm text-slate-500">
                                    Este usuario no tiene empresas archivadas.
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className="text-sm text-slate-500">
                        Este usuario todavía no tiene empresas asignadas.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
        </section>
      )}

      {formMode && (
        <section className="card">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold">
                {formMode === "create" ? "Crear usuario" : "Editar usuario"}
              </h2>
              <p className="muted text-sm mt-1">
                Completa los datos administrativos del usuario.
              </p>
            </div>

            <button className="btn-secondary" onClick={closeForm}>
              Cerrar
            </button>
          </div>

          <form className="mt-5 grid gap-4 md:grid-cols-2" onSubmit={submitForm}>
            <div>
              <label className="block text-sm mb-1">Nombre completo</label>
              <input
                className="input w-full"
                value={form.full_name}
                onChange={(e) => setForm((prev) => ({ ...prev, full_name: e.target.value }))}
              />
            </div>

            <div>
              <label className="block text-sm mb-1">Correo</label>
              <input
                className="input w-full"
                type="email"
                required
                value={form.email}
                onChange={(e) => setForm((prev) => ({ ...prev, email: e.target.value }))}
              />
            </div>

            <div>
              <label className="block text-sm mb-1">Cédula</label>
              <input
                className="input w-full"
                value={form.id_number}
                onChange={(e) => setForm((prev) => ({ ...prev, id_number: e.target.value }))}
              />
            </div>

            <div>
              <label className="block text-sm mb-1">Teléfono</label>
              <input
                className="input w-full"
                value={form.phone}
                onChange={(e) => setForm((prev) => ({ ...prev, phone: e.target.value }))}
              />
            </div>

            <div>
              <label className="block text-sm mb-1">Rol</label>
              <select
                className="input w-full"
                value={form.role}
                onChange={(e) => setForm((prev) => ({ ...prev, role: e.target.value }))}
              >
                <option value="SUBSCRIBER">SUBSCRIBER</option>
                <option value="ADMIN">ADMIN</option>
                <option value="PENDING">PENDING</option>
              </select>
            </div>

            <div className="flex items-center gap-2 pt-7">
              <input
                id="is_active_user"
                type="checkbox"
                checked={form.is_active}
                onChange={(e) => setForm((prev) => ({ ...prev, is_active: e.target.checked }))}
              />
              <label htmlFor="is_active_user" className="text-sm">
                Usuario activo
              </label>
            </div>

            {formMode === "create" && (
              <div className="md:col-span-2">
                <label className="block text-sm mb-1">Contraseña inicial</label>
                <input
                  className="input w-full"
                  type="password"
                  required
                  value={form.password}
                  onChange={(e) => setForm((prev) => ({ ...prev, password: e.target.value }))}
                />
              </div>
            )}

            <div className="md:col-span-2 flex gap-2 flex-wrap">
              <button className="btn-primary" type="submit" disabled={savingForm}>
                {savingForm
                  ? (formMode === "create" ? "Creando..." : "Guardando...")
                  : (formMode === "create" ? "Crear usuario" : "Guardar cambios")}
              </button>

              <button className="btn-secondary" type="button" onClick={closeForm}>
                Cancelar
              </button>
            </div>
          </form>
        </section>
      )}

      {passwordTarget && (
        <section className="card">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold">Cambiar contraseña</h2>
              <p className="muted text-sm mt-1">
                Usuario: {passwordTarget.email}
              </p>
            </div>

            <button
              className="btn-secondary"
              onClick={() => {
                setPasswordTarget(null);
                setPasswordValue("");
              }}
            >
              Cerrar
            </button>
          </div>

          <form className="mt-5" onSubmit={submitPasswordReset}>
            <label className="block text-sm mb-1">Nueva contraseña</label>
            <input
              className="input w-full max-w-xl"
              type="password"
              required
              value={passwordValue}
              onChange={(e) => setPasswordValue(e.target.value)}
            />

            <div className="mt-4 flex gap-2 flex-wrap">
              <button className="btn-primary" type="submit" disabled={savingPassword}>
                {savingPassword ? "Actualizando..." : "Guardar nueva contraseña"}
              </button>

              <button
                className="btn-secondary"
                type="button"
                onClick={() => {
                  setPasswordTarget(null);
                  setPasswordValue("");
                }}
              >
                Cancelar
              </button>
            </div>
          </form>
        </section>
      )}
      <section className="card">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h2 className="text-xl font-semibold">Bitácora administrativa</h2>
            <p className="muted text-sm mt-1">
              Registra acciones sensibles ejecutadas por administradores sobre usuarios, empresas y suscripciones.
            </p>
          </div>

          <div className="flex gap-2 flex-wrap">
            <button
              className="btn-secondary"
              onClick={loadAuditLogs}
              disabled={loadingAuditLogs}
            >
              {loadingAuditLogs ? "Actualizando..." : "Actualizar bitácora"}
            </button>
          </div>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-3">
          <div className="md:col-span-2">
            <label className="block text-sm mb-1">Buscar en descripción o detalle</label>
            <input
              className="input w-full"
              value={auditQuery}
              onChange={(e) => setAuditQuery(e.target.value)}
              placeholder="Ej.: contraseña, suscripción, empresa, Darwin..."
            />
          </div>

          <div>
            <label className="block text-sm mb-1">Acción</label>
            <select
              className="input w-full"
              value={auditActionFilter}
              onChange={(e) => setAuditActionFilter(e.target.value)}
            >
              <option value="">Todas</option>
              <option value="USER_CREATE">USER_CREATE</option>
              <option value="USER_UPDATE">USER_UPDATE</option>
              <option value="USER_PASSWORD_RESET">USER_PASSWORD_RESET</option>
              <option value="USER_DELETE">USER_DELETE</option>
              <option value="COMPANY_REASSIGN">COMPANY_REASSIGN</option>
              <option value="COMPANY_DELETE">COMPANY_DELETE</option>
              <option value="SUBSCRIPTION_UPDATE">SUBSCRIPTION_UPDATE</option>
            </select>
          </div>
        </div>

        <div className="mt-3 flex gap-2 flex-wrap">
          <button className="btn-primary" onClick={loadAuditLogs} disabled={loadingAuditLogs}>
            {loadingAuditLogs ? "Buscando..." : "Aplicar filtros"}
          </button>

          <button
            className="btn-secondary"
            onClick={() => {
              setAuditQuery("");
              setAuditActionFilter("");
              setTimeout(() => loadAuditLogs(), 0);
            }}
          >
            Limpiar filtros
          </button>
        </div>

        <div className="mt-5 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-white/10">
                <th className="py-3 pr-3 text-left">Fecha</th>
                <th className="py-3 pr-3 text-left">Administrador</th>
                <th className="py-3 pr-3 text-left">Acción</th>
                <th className="py-3 pr-3 text-left">Entidad</th>
                <th className="py-3 pr-3 text-left">Objetivo</th>
                <th className="py-3 pr-3 text-left">Empresa</th>
                <th className="py-3 text-left">Descripción</th>
              </tr>
            </thead>
            <tbody>
              {auditLogs.map((row) => (
                <tr key={row.id} className="border-b border-slate-100 align-top dark:border-white/5">
                  <td className="py-3 pr-3">{formatDate(row.created_at)}</td>
                  <td className="py-3 pr-3">{compactText(row.admin_email)}</td>
                  <td className="py-3 pr-3">{row.action}</td>
                  <td className="py-3 pr-3">{row.entity_type}</td>
                  <td className="py-3 pr-3">{compactText(row.target_user_email)}</td>
                  <td className="py-3 pr-3">{compactText(row.company_name)}</td>
                  <td className="py-3">{compactText(row.description)}</td>
                </tr>
              ))}

              {!loadingAuditLogs && auditLogs.length === 0 && (
                <tr>
                  <td className="py-4 text-sm text-slate-500" colSpan={7}>
                    No hay registros de bitácora para los filtros aplicados.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}