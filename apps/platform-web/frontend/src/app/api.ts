import axios from "axios";
import type { AxiosRequestConfig } from "axios";

/**
 * Base del backend.
 *
 * Sin VITE_API_URL dejamos la base vacía para usar el mismo origen y el proxy
 * de Vite (/api -> backend) sin duplicar el prefijo. Cuando se configura una
 * URL explícita, el contrato esperado es el origen del backend; toleramos por
 * compatibilidad un sufijo /api o /api/v1 y lo normalizamos al origen.
 */
const RAW_API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");
const API_BASE = RAW_API_BASE.replace(/\/api(?:\/v1)?$/, "");
const client = axios.create({
  baseURL: API_BASE || undefined,
  withCredentials: true,
});

/** Inyecta Bearer en cada request */
client.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers = config.headers ?? {};
    (config.headers as any).Authorization = `Bearer ${token}`;
  }

  // Normaliza paths heredados a /api/v1 sin duplicar llamadas ya normalizadas.
  if (typeof config.url === "string" && config.url.startsWith("/")) {
    const alreadyApiV1 = config.url === "/api/v1" || config.url.startsWith("/api/v1/");
    if (!alreadyApiV1) {
      config.url = `/api/v1${config.url}`;
    }
  }

  return config;
});


client.interceptors.response.use(
  (r) => r,
  async (error) => {
    const status = error?.response?.status;
    const original = error?.config;
    const data = error?.response?.data;

    if (status === 401 && original && !original._retry) {
      const t = localStorage.getItem("token");

      if (t) {
        original._retry = true;
        original.headers = original.headers ?? {};
        original.headers.Authorization = `Bearer ${t}`;
        return client(original);
      }
    }

    if (
      status === 402 &&
      data &&
      (data.code === "TRIAL_EXPIRED" || data.code === "SUBSCRIPTION_INACTIVE")
    ) {
      try {
        sessionStorage.setItem("billing_block", JSON.stringify(data));
      } catch (_) {}

      const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;

      if (window.location.pathname !== "/pay") {
        try {
          sessionStorage.setItem("post_billing_redirect", currentPath || "/");
        } catch (_) {}

        window.location.assign("/pay");
      }
    }

    return Promise.reject(error);
  }
);


/** ⇢ Export nombrado: axios-like (para `{ api }`) */
export const api = client;

/** ⇢ Export default: wrapper que retorna `data` (para `import api from ...`) */
const http = {
  async get<T = any>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await client.get<T>(url, config);
    return data;
  },
  async post<T = any>(url: string, body?: any, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await client.post<T>(url, body, config);
    return data;
  },
  async put<T = any>(url: string, body?: any, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await client.put<T>(url, body, config);
    return data;
  },
  async patch<T = any>(url: string, body?: any, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await client.patch<T>(url, body, config);
    return data;
  },
  async delete<T = any>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await client.delete<T>(url, config);
    return data;
  },
};
export default http;

/** Opcional: si necesitas la instancia cruda */
export { client as axiosClient };

/* --------- Helpers usados por Documents.tsx --------- */
export function getCompanyDocuments(companyId: number) {
  return client.get(`/documents/company/${companyId}`);
}
export function getCompanyRequirements(companyId: number) {
  return client.get(`/companies/${companyId}/requirements`);
}
export function askIncidentAssistant(companyId: number, question: string) {
  return client.post(`/companies/${companyId}/incident-assistant/query`, { question });
}

export function getIncidentAssistantState(companyId: number) {
  return client.get(`/companies/${companyId}/incident-assistant/state`);
}

export function saveIncidentProcedure(companyId: number, payload: Record<string, any>) {
  return client.post(`/companies/${companyId}/incident-assistant/procedure`, payload);
}

export function generateIncidentProcedurePdf(companyId: number) {
  return client.post(`/companies/${companyId}/incident-assistant/procedure/pdf`);
}

export function createIncidentWorker(companyId: number, payload: Record<string, any>) {
  return client.post(`/companies/${companyId}/incident-assistant/workers`, payload);
}

export function createWorkerEppDelivery(companyId: number, payload: Record<string, any>) {
  return client.post(`/companies/${companyId}/incident-assistant/epp-deliveries`, payload);
}

export function createIncidentCase(companyId: number, payload: Record<string, any>) {
  return client.post(`/companies/${companyId}/incident-assistant/cases`, payload);
}

export function updateIncidentCase(companyId: number, caseId: number, payload: Record<string, any>) {
  return client.patch(`/companies/${companyId}/incident-assistant/cases/${caseId}`, payload);
}

export function streamDocumentUrl(documentId: number) {
  return `${API_BASE}/api/v1/documents/${documentId}/stream`;
}

export function getAdminUsers(params?: {
  q?: string;
  role?: string;
  is_active?: boolean;
  archived_mode?: "active" | "archived" | "all";
}) {
  return client.get('/users', { params });
}

export function getAdminUserDetail(userId: number) {
  return client.get(`/users/${userId}`);
}

export function getAdminUserCompanies(userId: number) {
  return client.get(`/users/${userId}/companies`);
}

export function createAdminUser(payload: {
  full_name?: string | null;
  email: string;
  id_number?: string | null;
  phone?: string | null;
  role: string;
  is_active: boolean;
  password: string;
}) {
  return client.post('/users', payload);
}

export function updateAdminUser(
  userId: number,
  payload: {
    full_name?: string | null;
    email?: string | null;
    id_number?: string | null;
    phone?: string | null;
    role?: string | null;
    is_active?: boolean | null;
  }
) {
  return client.patch(`/users/${userId}`, payload);
}

export function resetAdminUserPassword(userId: number, password: string) {
  return client.patch(`/users/${userId}/password`, { password });
}

export function deleteAdminUser(userId: number) {
  return client.delete(`/users/${userId}`);
}

export function restoreAdminUser(userId: number) {
  return client.patch(`/users/${userId}/restore`);
}

export function hardDeleteAdminUser(userId: number) {
  return client.delete(`/users/${userId}/hard`);
}

export function reassignAdminUserCompany(
  userId: number,
  companyId: number,
  newOwnerUserId: number
) {
  return client.patch(`/users/${userId}/companies/${companyId}/reassign`, {
    new_owner_user_id: newOwnerUserId,
  });
}

export function deleteAdminCompany(companyId: number) {
  return client.delete(`/companies/${companyId}`);
}

export function restoreAdminCompany(companyId: number) {
  return client.patch(`/companies/${companyId}/restore`);
}

export function hardDeleteAdminCompany(companyId: number) {
  return client.delete(`/companies/${companyId}/hard`);
}

export function getAdminUserSubscription(userId: number) {
  return client.get(`/users/${userId}/subscription`);
}

export function updateAdminUserSubscription(
  userId: number,
  payload: {
    plan?: string | null;
    status?: string | null;
    companies_quota?: number | null;
    free_trial_until?: string | null;
    current_period_end?: string | null;
    last_payment_at?: string | null;
    provider?: string | null;
    customer_ref?: string | null;
  }
) {
  return client.patch(`/users/${userId}/subscription`, payload);
}

export function getAdminAuditLogs(params?: {
  q?: string;
  action?: string;
  entity_type?: string;
  target_user_id?: number;
  company_id?: number;
  limit?: number;
}) {
  return client.get('/users/audit/logs', { params });
}
