// 构建产物由后端同源托管，走相对路径；开发模式下 dev_web.py 会注入 VITE_API_ROOT。
const API_ROOT =
  import.meta.env.VITE_API_ROOT ?? (import.meta.env.PROD ? "/api" : "http://127.0.0.1:53211/api");

export function apiUrl(path: string): string {
  return `${API_ROOT}${path}`;
}

/** 原图地址（大图、下载）。 */
export function imageUrl(path: string): string {
  return apiUrl(`/results/image?path=${encodeURIComponent(path)}`);
}

/** 节点预览图：size=0 为原图（看大图），其他为缓存的缩略图；节点没有图时 404。 */
export function nodePreviewUrl(ref: string, size = 240): string {
  return apiUrl(`/nodes/preview-image?ref=${encodeURIComponent(ref)}&size=${size}`);
}

/** 网格用的缩略图：后端按长边 size 生成 WebP 并缓存，比直接加载 1~2MB 的原图快得多。 */
export function thumbUrl(path: string, size = 320): string {
  return apiUrl(`/results/thumb?path=${encodeURIComponent(path)}&size=${size}`);
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

export async function apiPut<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw await toApiError(response);
  }
  return response.json() as Promise<T>;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const response = await fetch(apiUrl(path), {
    method: "DELETE",
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

export async function getNovelAIUsage(): Promise<import("./types").NovelAIUsageInfo> {
  return apiGet<import("./types").NovelAIUsageInfo>("/novelai/usage");
}

export async function refreshNovelAIUsage(): Promise<import("./types").NovelAIUsageInfo> {
  return apiPost<import("./types").NovelAIUsageInfo>("/novelai/usage/refresh", {});
}

type NovelAITokenList = import("./types").NovelAITokenList;

export async function listNovelAITokens(): Promise<NovelAITokenList> {
  return apiGet<NovelAITokenList>("/novelai/tokens");
}

export async function addNovelAIToken(body: {
  name: string;
  token: string;
  activate?: boolean;
}): Promise<NovelAITokenList> {
  return apiPost<NovelAITokenList>("/novelai/tokens", body);
}

/** 批量导入，每行一个 token（可写「名称 token」）；已存在和同批重复的跳过。 */
export async function importNovelAITokens(
  text: string,
): Promise<import("./types").NovelAITokenImportResult> {
  return apiPost<import("./types").NovelAITokenImportResult>("/novelai/tokens/import", { text });
}

/** 某个 token 的订阅和点数；refresh=true 时绕过后端 60s 缓存。 */
export async function getNovelAITokenUsage(
  id: string,
  refresh = false,
): Promise<import("./types").NovelAIUsageInfo> {
  return apiGet(
    `/novelai/tokens/${encodeURIComponent(id)}/usage${refresh ? "?refresh=true" : ""}`,
  );
}

/** 批量导入账号密码（每行「邮箱 密码」或旧 NAI_ACCOUNT 列表），逐个登录验证，重复的跳过。 */
export async function importNovelAIAccounts(
  text: string,
): Promise<import("./types").NovelAITokenImportResult> {
  return apiPost<import("./types").NovelAITokenImportResult>("/novelai/tokens/import-accounts", {
    text,
  });
}

/** 把登录失败的账号放回后台登录队列。 */
export async function reloginNovelAIAccount(id: string): Promise<NovelAITokenList> {
  return apiPost<NovelAITokenList>(`/novelai/tokens/${encodeURIComponent(id)}/relogin`, {});
}

export async function renameNovelAIToken(id: string, name: string): Promise<NovelAITokenList> {
  return apiPut<NovelAITokenList>(`/novelai/tokens/${encodeURIComponent(id)}`, { name });
}

export async function deleteNovelAIToken(id: string): Promise<NovelAITokenList> {
  return apiDelete<NovelAITokenList>(`/novelai/tokens/${encodeURIComponent(id)}`);
}

export async function activateNovelAIToken(id: string): Promise<NovelAITokenList> {
  return apiPost<NovelAITokenList>(`/novelai/tokens/${encodeURIComponent(id)}/activate`, {});
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
