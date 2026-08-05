export type DurationPreset =
  | "microvideo"
  | "minicourse"
  | "short"
  | "standard"
  | "complete"
  | "custom";

export interface DurationSpec {
  preset: DurationPreset;
  module_count: number;
  videos_per_module: number;
  target_minutes_per_video: number;
  total_videos: number;
  total_minutes: number;
  tolerance_ratio: number;
}

export type ResearchMode =
  | "provided_only"
  | "provided_plus_web"
  | "web_only";

export interface IdeationSource {
  id: string;
  session_id: string | null;
  project_id: string | null;
  kind: string;
  media_type: string;
  name: string;
  original_url: string | null;
  final_url: string | null;
  sha256: string;
  size_bytes: number;
  status: "pending" | "ready" | "failed";
  error: string;
  metadata: Record<string, unknown>;
  captured_at: string;
}

export interface Project {
  id: string;
  title: string;
  topic: string;
  audience: string;
  level: string;
  language: string;
  style: string;
  output_format: string;
  duration_spec: DurationSpec | null;
  selected_workflow_id: string | null;
  research_mode: ResearchMode;
  sources: IdeationSource[];
  status: string;
  created_at: string;
  updated_at: string;
}

export interface UsageAggregate {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  input_characters: number;
  image_count: number;
  cost_usd: string | null;
  unknown_cost_records: number;
}

export interface UsageBreakdown extends UsageAggregate {
  key: string;
  has_data?: boolean;
  kind?: string;
  status?: string;
  created_at?: string | null;
}

export interface ProjectCostSummary {
  has_data: boolean;
  historical: UsageAggregate | null;
  active: UsageAggregate | null;
  cost_sources: UsageBreakdown[];
  agents: UsageBreakdown[];
  models: string[];
  runs: UsageBreakdown[];
  last_updated: string | null;
}

export type ProjectInput = Omit<
  Project,
  | "id"
  | "sources"
  | "status"
  | "selected_workflow_id"
  | "created_at"
  | "updated_at"
>;

export type ProjectUpdateInput = Partial<ProjectInput> & {
  selected_workflow_id?: string | null;
};

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
      if (
        typeof body.detail === "object" &&
        body.detail !== null &&
        typeof body.detail.message === "string"
      ) {
        detail = body.detail.message;
      }
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
  kind: "text" | "question" | "answer" | "search" | "source" | "brief" | "progress";
  content: string;
  payload: { options?: IdeationOption[]; query?: string } | Record<
    string,
    unknown
  > | null;
  created_at: string;
}

export type IdeationProgress = IdeationMessage & {
  kind: "progress";
  payload: ({
    phase?: "stage" | "tool_call" | "tool_result" | "review";
    tool?: string;
  } & Record<string, unknown>) | null;
};

export interface CourseIdeaBrief {
  working_title: string;
  topic: string;
  audience: string;
  level: string;
  language: string;
  style: string;
  output_format: string;
  duration_spec: DurationSpec | null;
  research_mode: ResearchMode;
  source_ids: string[];
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
  research_mode: ResearchMode;
  source_count: number;
  has_brief: boolean;
  created_at: string;
  updated_at: string;
}

export interface IdeationSession extends IdeationSessionSummary {
  brief: CourseIdeaBrief | null;
  messages: IdeationMessage[];
  sources: IdeationSource[];
}

export interface AgentSpec {
  name: string;
  display_name: string;
  description: string;
  kind: "task" | "conversational" | "automatic";
  tool_names: string[];
  consumes: string[];
  produces: string[];
}

export interface SlidePalette {
  background: string;
  text: string;
  headings: string;
  primary: string;
  secondary: string;
  code_background: string;
  code_text: string;
  links: string;
}

export interface PaletteOptions {
  default: SlidePalette;
  presets: { id: string; label: string; colors: SlidePalette }[];
}

export interface LogoCandidate {
  id: string;
  source: "uploaded" | "generated";
  name: string;
  path: string;
  thumbnail_path: string;
  media_type: string;
  width: number;
  height: number;
  sha256: string;
  prompt?: string | null;
  model?: string | null;
  seed?: number | null;
  cost_usd?: number | null;
  created_at: string;
  status: "available" | "error";
  error?: string | null;
  transparent_variant?: LogoTransparentVariant | null;
}

export interface LogoTransparentVariant {
  path: string;
  media_type: "image/png";
  width: number;
  height: number;
  sha256: string;
  source_sha256: string;
  method: string;
}

export interface LogoVisibility {
  cover: boolean;
  content: boolean;
  summary: boolean;
}

export interface AgentProfile {
  id: string;
  agent_type: string;
  name: string;
  soul_md: string;
  agents_md: string;
  model: string | null;
  orientation: "horizontal" | "vertical" | null;
  images_enabled: boolean | null;
  image_model: string | null;
  image_style: string | null;
  image_style_prompt: string | null;
  automatic_review_enabled: boolean;
  max_automatic_regenerations: number;
  human_review_enabled: boolean;
  tts_provider: "openai" | "openrouter" | null;
  tts_model: string | null;
  tts_language: string | null;
  tts_voice: string | null;
  tts_available: boolean | null;
  tts_speed: number | null;
  tts_instructions: string | null;
  tts_style: string | null;
  tts_style_degree: number | null;
  tts_advanced_options: Record<string, string | number | boolean> | null;
  subtitles_mode: "none" | "srt" | "burned_and_srt" | null;
  slide_palette: SlidePalette | null;
  logo_mode: "none" | "uploaded" | "generated" | null;
  active_logo_id: string | null;
  logo_placement: "top-left" | "top-right" | "bottom-left" | "bottom-right" | null;
  logo_size: "small" | "medium" | "large" | null;
  logo_margin_px: number | null;
  logo_opacity: number | null;
  logo_background_mode: "opaque" | "transparent" | null;
  logo_visibility: LogoVisibility | null;
  logo_candidates: LogoCandidate[] | null;
  publisher_recurrent_text: string | null;
  publisher_recurrent_links: string | null;
  version: number;
  active_version: number;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface ProfileVersion {
  version: number;
  is_active: boolean;
  soul_md: string;
  agents_md: string;
  model: string | null;
  orientation: "horizontal" | "vertical" | null;
  images_enabled: boolean | null;
  image_model: string | null;
  image_style: string | null;
  image_style_prompt: string | null;
  automatic_review_enabled: boolean;
  max_automatic_regenerations: number;
  human_review_enabled: boolean;
  tts_provider: "openai" | "openrouter" | null;
  tts_model: string | null;
  tts_language: string | null;
  tts_voice: string | null;
  tts_available: boolean | null;
  tts_speed: number | null;
  tts_instructions: string | null;
  tts_style: string | null;
  tts_style_degree: number | null;
  tts_advanced_options: Record<string, string | number | boolean> | null;
  subtitles_mode: "none" | "srt" | "burned_and_srt" | null;
  slide_palette: SlidePalette | null;
  logo_mode: "none" | "uploaded" | "generated" | null;
  active_logo_id: string | null;
  logo_placement: "top-left" | "top-right" | "bottom-left" | "bottom-right" | null;
  logo_size: "small" | "medium" | "large" | null;
  logo_margin_px: number | null;
  logo_opacity: number | null;
  logo_background_mode: "opaque" | "transparent" | null;
  logo_visibility: LogoVisibility | null;
  logo_candidates: LogoCandidate[] | null;
  publisher_recurrent_text: string | null;
  publisher_recurrent_links: string | null;
  note: string;
  created_at: string;
}

export interface ImageOptions {
  default_model: string;
  default_style: string;
  max_images_per_deck: number;
  models: { id: string; label: string; price_hint: string }[];
  styles: { id: string; label: string; prompt: string }[];
}

export interface TTSModelOption {
  provider: "openai" | "openrouter";
  provider_label: string;
  model: string;
  label: string;
  languages: string[];
  voices_by_language: Record<string, string[]>;
  default_voice: string;
  request_formats: ("mp3" | "pcm")[];
  preferred_format: "mp3" | "pcm";
  response_mime_type: string;
  output_format: "mp3" | "wav";
  output_mime_type: string;
  sample_rate_hz: number | null;
  channels: number | null;
  streaming: boolean;
  provider_options: string[];
  price_per_million_characters_usd: number | null;
  price_hint: string;
  available: boolean;
  catalog_source: string;
  catalog_updated_at: string | null;
  status: "stable" | "preview";
  max_characters: number | null;
  capabilities: {
    speed: { min: number; max: number; step: number } | null;
    instructions: boolean;
    styles: string[];
    style_degree: { min: number; max: number; step: number } | null;
    inline_tags: string[];
    pronunciation: boolean;
  };
}

export interface TTSOptions {
  default: {
    tts_provider: "openai" | "openrouter";
    tts_model: string;
    tts_language: string;
    tts_voice: string;
    tts_speed: number;
    tts_instructions: string;
    tts_style: string | null;
    tts_style_degree: number | null;
    tts_advanced_options: Record<string, string | number | boolean>;
  };
  models: TTSModelOption[];
  source: string;
  updated_at: string | null;
  stale: boolean;
  error: string | null;
}

export interface JobEvent {
  seq: number;
  type: string;
  summary: string;
  data: {
    tool?: string;
    artifact_id?: string;
    agent?: string;
    status?:
      | "queued"
      | "running"
      | "pausing"
      | "paused"
      | "waiting_approval"
      | "canceling"
      | "canceled"
      | "done"
      | "failed";
    step?: number;
  } | null;
  created_at: string;
}

export interface ImprovementProposal {
  id: string;
  project_id: string | null;
  kind: "wiki" | "agents_md";
  agent_type: string;
  slug: string;
  title: string;
  proposed_content: string;
  evidence: string;
  status: string;
  applied_profile_id: string | null;
  created_at: string;
}

export interface WikiPage {
  slug: string;
  title: string;
  content_md: string;
  updated_at: string;
}

export interface WorkflowStep {
  agent: string;
  profile_id?: string | null;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  steps: WorkflowStep[];
  is_template: boolean;
  created_at: string;
  updated_at: string;
}

export interface Job {
  id: string;
  kind: string;
  status:
    | "queued"
    | "running"
    | "pausing"
    | "paused"
    | "waiting_approval"
    | "canceling"
    | "canceled"
    | "done"
    | "failed";
  error: string;
  project_id: string | null;
  workflow_id: string | null;
  workflow_name: string | null;
  result: {
    artifact_id?: string;
    artifact_ids?: string[];
    course_subtitles_id?: string | null;
    chapter_manifest_id?: string | null;
    cache_hit?: boolean;
  } | null;
  control: {
    pause_requested_at?: string;
    paused_at?: string;
    cancel_requested_at?: string;
    canceled_at?: string;
    resumed_at?: string;
    resume_count?: number;
    pause_reason?: string;
    checkpoint?: {
      phase?: string;
      current_unit?: string | null;
      next_unit?: string | null;
      last_completed_unit?: string;
      message?: string;
      updated_at?: string;
    };
  };
  usage_summary: {
    has_data: boolean;
    records: number;
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
    input_characters?: number;
    image_count?: number;
    cost_usd?: string | null;
    unknown_cost_records?: number;
  };
  review_policies: Record<
    string,
    {
      enabled: boolean;
      max_regenerations: number;
      profile_id: string | null;
      profile_version: number | null;
      evaluator_model: string | null;
      human_review_enabled: boolean;
    }
  >;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  events: JobEvent[];
}

export interface Artifact {
  id: string;
  project_id: string;
  type: string;
  format: string;
  title: string;
  logical_key: string;
  version: number;
  is_selected: boolean;
  metadata: Record<string, unknown>;
  created_by_job_id: string | null;
  created_at: string;
  content: string | null;
  renders: string[];
  versions: {
    id: string;
    version: number;
    is_selected: boolean;
    metadata: Record<string, unknown>;
    created_at: string;
  }[];
}

export type CourseVideoTransition = "none" | "fade_500ms" | "gap_500ms";

export interface CourseVideoPreflightIssue {
  code: string;
  lesson: string | null;
  detail: string;
}

export interface CourseVideoPreflightLesson {
  module_index: number;
  lesson_index: number;
  module_title: string;
  lesson_title: string;
  label: string;
  video_artifact_id: string | null;
  video_version: number | null;
  subtitles_artifact_id: string | null;
  duration_seconds: number | null;
  orientation: "horizontal" | "vertical" | null;
}

export interface CourseVideoPreflight {
  ready: boolean;
  ffmpeg_available: boolean;
  include_subtitles: boolean;
  include_chapters: boolean;
  transition: CourseVideoTransition;
  subtitles_available: boolean;
  total_duration_seconds: number;
  output_duration_seconds: number;
  orientation: "horizontal" | "vertical" | null;
  width: number | null;
  height: number | null;
  input_signature: string | null;
  lessons: CourseVideoPreflightLesson[];
  issues: CourseVideoPreflightIssue[];
}

async function streamIdeation(
  path: string,
  body: Record<string, string> = {},
  onProgress: (event: IdeationProgress) => void,
): Promise<IdeationSession> {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({ detail: response.statusText }));
    throw new ApiError(response.status, payload.detail ?? response.statusText);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: IdeationSession | null = null;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const event = block
        .split("\n")
        .find((line) => line.startsWith("event: "))
        ?.slice(7);
      const data = block
        .split("\n")
        .filter((line) => line.startsWith("data: "))
        .map((line) => line.slice(6))
        .join("\n");
      if (data) {
        const payload = JSON.parse(data);
        if (event === "progress") onProgress(payload as IdeationProgress);
        if (event === "result") result = payload as IdeationSession;
        if (event === "error") throw new ApiError(502, payload.detail ?? "Error de ideación");
      }
      boundary = buffer.indexOf("\n\n");
    }
    if (done) break;
  }
  if (!result) throw new ApiError(502, "La sesión terminó sin respuesta");
  return result;
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
  getProjectCostSummary: (id: string) =>
    request<ProjectCostSummary>(`/api/projects/${id}/costs/summary`),
  createProject: (input: ProjectInput) =>
    request<Project>("/api/projects", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  updateProject: (id: string, input: ProjectUpdateInput) =>
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
  createIdeationDraft: (idea: string, researchMode: ResearchMode) =>
    request<IdeationSession>("/api/ideation/draft", {
      method: "POST",
      body: JSON.stringify({ idea, research_mode: researchMode }),
    }),
  createIdeationStream: (
    idea: string,
    onProgress: (event: IdeationProgress) => void,
  ) => streamIdeation("/api/ideation/stream", { idea }, onProgress),
  startIdeationStream: (
    id: string,
    onProgress: (event: IdeationProgress) => void,
  ) => streamIdeation(`/api/ideation/${id}/start/stream`, {}, onProgress),
  listIdeations: () => request<IdeationSessionSummary[]>("/api/ideation"),
  getIdeation: (id: string) => request<IdeationSession>(`/api/ideation/${id}`),
  updateIdeationResearchMode: (id: string, researchMode: ResearchMode) =>
    request<IdeationSession>(`/api/ideation/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ research_mode: researchMode }),
    }),
  addIdeationSourceUrl: (id: string, url: string) =>
    request<IdeationSource>(`/api/ideation/${id}/sources/url`, {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  addIdeationSourceFile: async (id: string, file: File) => {
    const data = new FormData();
    data.append("file", file);
    const response = await fetch(`/api/ideation/${id}/sources/file`, {
      method: "POST",
      body: data,
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({ detail: response.statusText }));
      throw new ApiError(response.status, payload.detail ?? response.statusText);
    }
    return (await response.json()) as IdeationSource;
  },
  deleteIdeationSource: (id: string, sourceId: string) =>
    request<void>(`/api/ideation/${id}/sources/${sourceId}`, {
      method: "DELETE",
    }),
  sendIdeationMessage: (id: string, content: string) =>
    request<IdeationSession>(`/api/ideation/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  sendIdeationMessageStream: (
    id: string,
    content: string,
    onProgress: (event: IdeationProgress) => void,
  ) => streamIdeation(`/api/ideation/${id}/messages/stream`, { content }, onProgress),
  finalizeIdeation: (id: string) =>
    request<Project>(`/api/ideation/${id}/finalize`, { method: "POST" }),
  deleteIdeation: (id: string) =>
    request<void>(`/api/ideation/${id}`, { method: "DELETE" }),
  listAgents: () => request<AgentSpec[]>("/api/agents"),
  getImageOptions: () => request<ImageOptions>("/api/agents/image-options"),
  getPaletteOptions: () => request<PaletteOptions>("/api/agents/palette-options"),
  getTTSOptions: (refresh = false) =>
    request<TTSOptions>(`/api/agents/tts-options${refresh ? "?refresh=true" : ""}`),
  listProfiles: (agentType: string) =>
    request<AgentProfile[]>(`/api/agents/${agentType}/profiles`),
  createProfile: (
    agentType: string,
    input: {
      name: string;
      soul_md?: string;
      agents_md?: string;
      model?: string;
      orientation?: "horizontal" | "vertical";
      images_enabled?: boolean;
      image_model?: string;
      image_style?: string;
      image_style_prompt?: string;
      automatic_review_enabled?: boolean;
      max_automatic_regenerations?: number;
      human_review_enabled?: boolean;
      tts_provider?: "openai" | "openrouter";
      tts_model?: string;
      tts_language?: string;
      tts_voice?: string;
      tts_speed?: number;
      tts_instructions?: string;
      tts_style?: string | null;
      tts_style_degree?: number | null;
      tts_advanced_options?: Record<string, string | number | boolean>;
      subtitles_mode?: "none" | "srt" | "burned_and_srt";
      slide_palette?: SlidePalette;
      logo_mode?: "none" | "uploaded" | "generated";
      active_logo_id?: string | null;
      logo_placement?: "top-left" | "top-right" | "bottom-left" | "bottom-right";
      logo_size?: "small" | "medium" | "large";
      logo_margin_px?: number;
      logo_opacity?: number;
      logo_background_mode?: "opaque" | "transparent";
      logo_visibility?: LogoVisibility;
      publisher_recurrent_text?: string;
      publisher_recurrent_links?: string;
    },
  ) =>
    request<AgentProfile>(`/api/agents/${agentType}/profiles`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  getProfile: (id: string) => request<AgentProfile>(`/api/agents/profiles/${id}`),
  getProfileVersions: (id: string) =>
    request<ProfileVersion[]>(`/api/agents/profiles/${id}/versions`),
  activateProfileVersion: (id: string, version: number) =>
    request<AgentProfile>(`/api/agents/profiles/${id}/versions/${version}/activate`, {
      method: "POST",
    }),
  updateProfile: (
    id: string,
    input: Partial<
      Pick<
        AgentProfile,
        | "name"
        | "soul_md"
        | "agents_md"
        | "is_default"
        | "orientation"
        | "images_enabled"
        | "image_model"
        | "image_style"
        | "image_style_prompt"
        | "automatic_review_enabled"
        | "max_automatic_regenerations"
        | "human_review_enabled"
        | "tts_provider"
        | "tts_model"
        | "tts_language"
        | "tts_voice"
        | "tts_speed"
        | "tts_instructions"
        | "tts_style"
        | "tts_style_degree"
        | "tts_advanced_options"
        | "subtitles_mode"
        | "slide_palette"
        | "logo_mode"
        | "active_logo_id"
        | "logo_placement"
        | "logo_size"
        | "logo_margin_px"
        | "logo_opacity"
        | "logo_background_mode"
        | "logo_visibility"
        | "publisher_recurrent_text"
        | "publisher_recurrent_links"
      >
    > & { model?: string; note?: string },
  ) =>
    request<AgentProfile>(`/api/agents/profiles/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  previewProfileTTS: async (
    id: string,
    input: {
      text: string;
      tts_provider: "openai" | "openrouter";
      tts_model: string;
      tts_language: string;
      tts_voice: string;
      tts_speed: number;
      tts_instructions: string;
      tts_style: string | null;
      tts_style_degree: number | null;
      tts_advanced_options: Record<string, string | number | boolean>;
    },
  ) => {
    const response = await fetch(`/api/agents/profiles/${id}/tts-preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: response.statusText }));
      throw new ApiError(response.status, body.detail ?? response.statusText);
    }
    return response.blob();
  },
  deleteProfile: (id: string) =>
    request<void>(`/api/agents/profiles/${id}`, { method: "DELETE" }),
  uploadProfileLogo: async (id: string, file: File, name = "") => {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    const response = await fetch(`/api/agents/profiles/${id}/logos/upload`, {
      method: "POST",
      body: form,
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: response.statusText }));
      throw new ApiError(response.status, body.detail ?? response.statusText);
    }
    return response.json() as Promise<AgentProfile>;
  },
  generateProfileLogo: (id: string, prompt: string, model: string, name = "") =>
    request<AgentProfile>(`/api/agents/profiles/${id}/logos/generate`, {
      method: "POST",
      body: JSON.stringify({ prompt, model, name }),
    }),
  deleteProfileLogo: (id: string, logoId: string) =>
    request<AgentProfile>(
      `/api/agents/profiles/${id}/logos/${encodeURIComponent(logoId)}`,
      { method: "DELETE" },
    ),
  prepareTransparentProfileLogo: (id: string, logoId: string) =>
    request<LogoTransparentVariant>(
      `/api/agents/profiles/${id}/logos/${encodeURIComponent(logoId)}/transparent-preview`,
      { method: "POST" },
    ),
  profileLogoUrl: (
    id: string,
    logoId: string,
    options: boolean | { thumbnail?: boolean; variant?: "original" | "transparent" } = false,
  ) => {
    const normalized =
      typeof options === "boolean" ? { thumbnail: options } : options;
    const params = new URLSearchParams();
    if (normalized.thumbnail) params.set("thumbnail", "true");
    if (normalized.variant && normalized.variant !== "original") {
      params.set("variant", normalized.variant);
    }
    const query = params.size > 0 ? `?${params.toString()}` : "";
    return `/api/agents/profiles/${id}/logos/${encodeURIComponent(logoId)}${query}`;
  },
  createAgentRun: (
    projectId: string,
    agent: string,
    profileId?: string,
    options?: {
      expected_input_artifact_ids?: Record<string, string[]>;
      request_id?: string;
      trigger?: "stage_card" | "artifact_card";
    },
  ) =>
    request<Job>(`/api/projects/${projectId}/agent-runs`, {
      method: "POST",
      body: JSON.stringify({
        agent,
        profile_id: profileId ?? null,
        ...options,
      }),
    }),
  getCourseVideoPreflight: (
    projectId: string,
    input?: {
      include_subtitles?: boolean;
      include_chapters?: boolean;
      transition?: CourseVideoTransition;
    },
  ) => {
    const params = new URLSearchParams();
    if (input?.include_subtitles !== undefined) {
      params.set("include_subtitles", String(input.include_subtitles));
    }
    if (input?.include_chapters !== undefined) {
      params.set("include_chapters", String(input.include_chapters));
    }
    if (input?.transition) params.set("transition", input.transition);
    const query = params.size > 0 ? `?${params.toString()}` : "";
    return request<CourseVideoPreflight>(
      `/api/projects/${projectId}/course-video/preflight${query}`,
    );
  },
  createCourseVideo: (
    projectId: string,
    input: {
      include_subtitles: boolean;
      include_chapters: boolean;
      transition: CourseVideoTransition;
      request_id?: string;
    },
  ) =>
    request<Job>(`/api/projects/${projectId}/course-video`, {
      method: "POST",
      body: JSON.stringify(input),
    }),
  uploadArtifact: async (
    projectId: string,
    file: File,
    type: string,
    title?: string,
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("type", type);
    if (title) form.append("title", title);
    const resp = await fetch(`/api/projects/${projectId}/artifacts`, {
      method: "POST",
      body: form,
    });
    if (!resp.ok) {
      const body = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new ApiError(resp.status, body.detail ?? resp.statusText);
    }
    return resp.json() as Promise<Artifact>;
  },
  listProjectRuns: (projectId: string) =>
    request<Job[]>(`/api/projects/${projectId}/runs`),
  getRun: (id: string) => request<Job>(`/api/runs/${id}`),
  listProjectArtifacts: (projectId: string) =>
    request<Artifact[]>(`/api/projects/${projectId}/artifacts`),
  getArtifact: (id: string) => request<Artifact>(`/api/artifacts/${id}`),
  editArtifact: (id: string, content: string) =>
    request<Artifact>(`/api/artifacts/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ content }),
    }),
  regenerateSlideImage: (artifactId: string, imageId: string, prompt: string) =>
    request<Artifact>(
      `/api/artifacts/${artifactId}/images/${encodeURIComponent(imageId)}/regenerate`,
      {
        method: "POST",
        body: JSON.stringify({ prompt }),
      },
    ),
  previewSlidePalette: async (artifactId: string, palette: SlidePalette) => {
    const response = await fetch(`/api/artifacts/${artifactId}/palette/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ palette }),
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({ detail: response.statusText }));
      throw new ApiError(response.status, body.detail ?? response.statusText);
    }
    return response.blob();
  },
  applySlidePalette: (
    artifactId: string,
    palette: SlidePalette,
    scope: "deck" | "project",
  ) =>
    request<Artifact[]>(`/api/artifacts/${artifactId}/palette`, {
      method: "POST",
      body: JSON.stringify({ palette, scope }),
    }),
  selectArtifact: (id: string) =>
    request<Artifact>(`/api/artifacts/${id}/select`, { method: "POST" }),
  deleteArtifact: (id: string) =>
    request<void>(`/api/artifacts/${id}`, { method: "DELETE" }),
  listWorkflows: () => request<Workflow[]>("/api/workflows"),
  getWorkflow: (id: string) => request<Workflow>(`/api/workflows/${id}`),
  createWorkflow: (input: {
    name: string;
    description?: string;
    steps: WorkflowStep[];
  }) =>
    request<Workflow>("/api/workflows", {
      method: "POST",
      body: JSON.stringify(input),
    }),
  updateWorkflow: (
    id: string,
    input: Partial<{ name: string; description: string; steps: WorkflowStep[] }>,
  ) =>
    request<Workflow>(`/api/workflows/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),
  deleteWorkflow: (id: string) =>
    request<void>(`/api/workflows/${id}`, { method: "DELETE" }),
  createWorkflowRun: (projectId: string, workflowId: string) =>
    request<Job>(`/api/projects/${projectId}/workflow-runs`, {
      method: "POST",
      body: JSON.stringify({ workflow_id: workflowId }),
    }),
  listProjectWiki: (projectId: string) =>
    request<WikiPage[]>(`/api/projects/${projectId}/wiki`),
  upsertWikiPage: (projectId: string, slug: string, input: {
    title?: string;
    content_md: string;
  }) =>
    request<WikiPage>(`/api/projects/${projectId}/wiki/${slug}`, {
      method: "PUT",
      body: JSON.stringify(input),
    }),
  deleteWikiPage: (projectId: string, slug: string) =>
    request<void>(`/api/projects/${projectId}/wiki/${slug}`, {
      method: "DELETE",
    }),
  youtubeStatus: () =>
    request<{ configured: boolean; connected: boolean }>("/api/youtube/status"),
  youtubeAuthUrl: () => request<{ url: string }>("/api/youtube/auth-url"),
  youtubePublish: (packageArtifactId: string, privacy: string) =>
    request<Job>("/api/youtube/publish", {
      method: "POST",
      body: JSON.stringify({
        package_artifact_id: packageArtifactId,
        privacy,
      }),
    }),
  createAnalyticsRun: (projectId: string) =>
    request<Job>(`/api/projects/${projectId}/analytics-runs`, {
      method: "POST",
    }),
  listImprovements: (status = "pending") =>
    request<ImprovementProposal[]>(`/api/improvements?status_filter=${status}`),
  getImprovementCurrent: (id: string) =>
    request<{ current: string }>(`/api/improvements/${id}/current`),
  approveImprovement: (id: string) =>
    request<ImprovementProposal>(`/api/improvements/${id}/approve`, {
      method: "POST",
    }),
  rejectImprovement: (id: string) =>
    request<ImprovementProposal>(`/api/improvements/${id}/reject`, {
      method: "POST",
    }),
  approveRun: (jobId: string, approved: boolean, feedback = "") =>
    request<Job>(`/api/runs/${jobId}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved, feedback }),
    }),
  pauseRun: (jobId: string) =>
    request<Job>(`/api/runs/${jobId}/pause`, { method: "POST" }),
  resumeRun: (jobId: string) =>
    request<Job>(`/api/runs/${jobId}/resume`, { method: "POST" }),
  cancelRun: (jobId: string) =>
    request<Job>(`/api/runs/${jobId}/cancel`, { method: "POST" }),
};
