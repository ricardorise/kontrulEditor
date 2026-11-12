const TOKEN_KEY = "kontrul_token";
export const getToken = () => localStorage.getItem(TOKEN_KEY) ?? import.meta.env.VITE_API_TOKEN ?? "dev-token-change-me";
export const setToken = (t: string) => localStorage.setItem(TOKEN_KEY, t);

export class ApiError extends Error {
  constructor(public status: number, public code: string | undefined, message: string, public extra?: unknown) {
    super(message);
  }
}

async function parse(res: Response) {
  if (res.ok) return res.status === 204 ? null : res.json();
  let body: { detail?: unknown; code?: string } = {};
  try { body = await res.json(); } catch { /* corpo não-JSON */ }
  const detail = typeof body.detail === "string" ? body.detail
    : Array.isArray(body.detail) ? (body.detail as { msg: string }[]).map((d) => d.msg).join("; ") : res.statusText;
  throw new ApiError(res.status, body.code, detail, body);
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${getToken()}`);
  let body = init.body;
  if (init.json !== undefined) { headers.set("Content-Type", "application/json"); body = JSON.stringify(init.json); }
  return parse(await fetch(`/v1${path}`, { ...init, headers, body })) as Promise<T>;
}

/** Upload com progresso (fetch não expõe progresso de envio). */
export function upload<T>(path: string, form: FormData, onProgress: (p: number) => void): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/v1${path}`);
    xhr.setRequestHeader("Authorization", `Bearer ${getToken()}`);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onerror = () => reject(new ApiError(0, "network", "falha de rede durante o upload"));
    xhr.onload = () => {
      let body: { detail?: string; code?: string } = {};
      try { body = JSON.parse(xhr.responseText); } catch { /* vazio */ }
      xhr.status >= 200 && xhr.status < 300 ? resolve(body as T) : reject(new ApiError(xhr.status, body.code, body.detail ?? xhr.statusText));
    };
    xhr.send(form);
  });
}
