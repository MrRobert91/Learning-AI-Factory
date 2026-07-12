export interface Project {
  id: string;
  title: string;
  topic: string;
  audience: string;
  level: string;
  language: string;
  style: string;
  output_format: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export type ProjectInput = Omit<
  Project,
  "id" | "status" | "created_at" | "updated_at"
>;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (resp.status === 401 && window.location.pathname !== "/login") {
    window.location.href = "/login";
  }
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // keep statusText
    }
    throw new ApiError(resp.status, detail);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

export const api = {
  login: (password: string) =>
    request<{ email: string }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ password }),
    }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: string) => request<Project>(`/api/projects/${id}`),
  createProject: (input: ProjectInput) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  updateProject: (id: string, input: Partial<ProjectInput>) =>
    request<Project>(`/api/projects/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  deleteProject: (id: string) =>
    request<void>(`/api/projects/${id}`, { method: "DELETE" }),
};
