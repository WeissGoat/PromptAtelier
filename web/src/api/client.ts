const API_ROOT = import.meta.env.VITE_API_ROOT ?? "http://127.0.0.1:8765/api";

export function apiUrl(path: string): string {
  return `${API_ROOT}${path}`;
}

export class ApiClientError extends Error {
  status: number;
  code?: string;
  details?: unknown;

  constructor(message: string, options: { status: number; code?: string; details?: unknown }) {
    super(message);
    this.name = "ApiClientError";
    this.status = options.status;
    this.code = options.code;
    this.details = options.details;
  }
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(apiUrl(path));
  if (!response.ok) {
    throw await toApiError(response);
  }
  return response.json() as Promise<T>;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw await toApiError(response);
  }
  return response.json() as Promise<T>;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.code ? `${error.code}: ${error.message}` : error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

async function toApiError(response: Response): Promise<ApiClientError> {
  const text = await response.text();
  try {
    const data = JSON.parse(text) as {
      error?: { code?: string; message?: string; details?: unknown };
      detail?: unknown;
    };
    const apiError = data.error;
    if (apiError?.message) {
      return new ApiClientError(apiError.message, {
        status: response.status,
        code: apiError.code,
        details: apiError.details,
      });
    }
    if (data.detail) {
      return new ApiClientError(JSON.stringify(data.detail), { status: response.status });
    }
  } catch {
    // 非 JSON 响应保留原始文本，方便看网关或开发服务器错误。
  }
  return new ApiClientError(text || response.statusText, { status: response.status });
}
