// frontend/src/app/auth.ts
import axios from "axios";

/**
 * Mantiene el login alineado con src/app/api.ts:
 * - sin VITE_API_URL usa el mismo origen de la PWA;
 * - con URL explicita acepta origen, /api o /api/v1 y normaliza al origen.
 */
const RAW_API_BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");
const API_BASE = RAW_API_BASE.replace(/\/api(?:\/v1)?$/, "");

export async function login(email: string, password: string) {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);

  const { data } = await axios.post(`${API_BASE}/api/v1/auth/token`, body, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    withCredentials: true,
  });

  // ← clave alineada con Protected en routes.tsx
  localStorage.setItem("token", data.access_token);
  return data;
}

export function logout() {
  localStorage.removeItem("token");
}
