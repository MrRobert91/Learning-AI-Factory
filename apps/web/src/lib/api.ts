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

export interface IdeationOption {
  label: string;
  description?: string;
}

export interface IdeationMessage {
  id: string;
  seq: number;
  role: "user" | "assistant";
  kind: "text" | "question" | "answer" | "search" | "brief";
  content: string;
  payload: { options?: IdeationOption[]; query?: string } | Record<
    string,
    unknown
  > | null;
  created_at: string;
}

export interface CourseIdeaBrief {
  working_title: string;
  topic: string;
  audience: string;
  level: string;
  language: string;
  style: string;
  output_format: string;
  objectives: string[];
  scope_outline: string[];
  differential_angle: string;
  open_questions: string[];
}

export interface IdeationSessionSummary {
  id: string;
  status: "active" | "finalized";
  initial_idea: string;
  project_id: string | null;
  has_brief: boolean;
  created_at: string;
  updated_at: string;
}

export interface IdeationSession extends IdeationSessionSummary {
  brief: CourseIdeaBrief | null;
  messages: IdeationMessage[];
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
  createIdeation: (idea: string) =>
    request<IdeationSession>("/api/ideation", {
      method: "POST",
      body: JSON.stringify({ idea }),
    }),
  listIdeations: () => request<IdeationSessionSummary[]>("/api/ideation"),
  getIdeation: (id: string) => request<IdeationSession>(`/api/ideation/${id}`),
  sendIdeationMessage: (id: string, content: string) =>
    request<IdeationSession>(`/api/ideation/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  finalizeIdeation: (id: string) =>
    request<Project>(`/api/ideation/${id}/finalize`, { method: "POST" }),
  deleteIdeation: (id: string) =>
    request<void>(`/api/ideation/${id}`, { method: "DELETE" }),
};
