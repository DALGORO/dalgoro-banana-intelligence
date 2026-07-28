// frontend/src/app/auth.ts
import axios from "axios";

const BASE = import.meta.env.VITE_API_URL ?? "/api";

export async function login(email: string, password: string) {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);

  const { data } = await axios.post(`${BASE}/api/v1/auth/token`, body, {
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
