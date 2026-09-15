const BASE = "/api-proxy";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (response.status === 401 && typeof window !== "undefined") {
    window.location.href = "/login";
    throw new Error("请先登录");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(body.detail || "请求失败");
  }
  return response.json() as Promise<T>;
}

export const eventUrl = (id: string) => `${BASE}/api/research/${id}/events`;
export const exportUrl = (id: string, kind: string) => `${BASE}/api/research/${id}/export/${kind}`;
