const API_ROOT = import.meta.env.VITE_API_ROOT ?? "http://127.0.0.1:8765/api";

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_ROOT}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json() as Promise<T>;
}
