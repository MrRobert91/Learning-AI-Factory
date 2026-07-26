"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  api,
  type CourseIdeaBrief,
  type IdeationMessage,
  type IdeationOption,
  type IdeationProgress,
  type IdeationSession,
  type ResearchMode,
} from "@/lib/api";
import {
  ErrorBanner,
  IconChevronLeft,
  IconSearch,
  IconSparkles,
  IconWrench,
  IconCheck,
  IconFileText,
  IconPlus,
  IconTrash,
  IconUpload,
  LoadingScreen,
  Spinner,
} from "@/components/ui";
import Markdown from "@/components/Markdown";

const RESEARCH_MODE_LABELS: Record<ResearchMode, string> = {
  web_only: "Investigación web libre",
  provided_plus_web: "Fuentes proporcionadas + web",
  provided_only: "Solo fuentes proporcionadas",
};

function AssistantAvatar() {
  return (
    <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-white">
      <IconSparkles size={13} />
    </span>
  );
}

function ProgressLine({ event }: { event: IdeationProgress }) {
  const phase = event.payload?.phase;
  const ProgressIcon =
    phase === "tool_call"
      ? IconWrench
      : phase === "tool_result"
        ? IconSearch
        : phase === "review"
          ? IconCheck
          : IconSparkles;
  const label =
    phase === "tool_call"
      ? "Llamada a herramienta"
      : phase === "tool_result"
        ? "Resultado de herramienta"
        : phase === "review"
          ? "Revisión"
          : "Paso actual";
  return (
    <div className="ml-10 flex items-start gap-2 rounded-xl border border-white/[0.07] bg-white/[0.02] px-3 py-2 text-xs text-zinc-400">
      <ProgressIcon size={13} className="mt-0.5 shrink-0 text-indigo-300" />
      <span className="min-w-0">
        <span className="font-semibold text-zinc-300">{label}: </span>
        {event.content}
      </span>
    </div>
  );
}

function QuestionCard({
  message,
  disabled,
  onAnswer,
}: {
  message: IdeationMessage;
  disabled: boolean;
  onAnswer: (text: string) => void;
}) {
  const options =
    (message.payload as { options?: IdeationOption[] })?.options ?? [];
  const [customAnswer, setCustomAnswer] = useState("");
  return (
    <div className="flex gap-3">
      <AssistantAvatar />
      <div className="animate-in min-w-0 flex-1 rounded-2xl rounded-tl-sm border border-indigo-400/20 bg-indigo-500/[0.07] p-4">
        <Markdown className="mb-3 text-sm font-medium">
          {message.content}
        </Markdown>
        <div className="grid gap-2 sm:grid-cols-2">
          {options.map((o) => (
            <button
              key={o.label}
              disabled={disabled}
              onClick={() => onAnswer(o.label)}
              className="rounded-xl border border-white/[0.1] bg-white/[0.03] p-3 text-left text-sm transition-all hover:border-indigo-400/60 hover:bg-indigo-500/[0.08] disabled:cursor-default disabled:opacity-50 disabled:hover:border-white/[0.1] disabled:hover:bg-white/[0.03]"
            >
              <span className="font-medium text-zinc-100">{o.label}</span>
              {o.description && (
                <span className="mt-1 block text-xs leading-relaxed text-zinc-400">
                  {o.description}
                </span>
              )}
            </button>
          ))}
        </div>
        {!disabled && (
          <p className="mt-3 text-xs text-zinc-500">
            …o responde con texto libre abajo.
          </p>
        )}
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!disabled && customAnswer.trim()) {
              onAnswer(customAnswer.trim());
              setCustomAnswer("");
            }
          }}
          className="mt-3 rounded-xl border border-dashed border-zinc-300 bg-white/40 p-3"
        >
          <label
            htmlFor={`custom-answer-${message.id}`}
            className="mb-2 block text-xs font-semibold text-zinc-300"
          >
            Otra opci&oacute;n
          </label>
          <div className="flex gap-2">
            <input
              id={`custom-answer-${message.id}`}
              value={customAnswer}
              onChange={(event) => setCustomAnswer(event.target.value)}
              disabled={disabled}
              placeholder="Escribe tu propia respuesta"
              className="input min-w-0 flex-1 py-1.5 text-xs"
            />
            <button
              type="submit"
              disabled={disabled || !customAnswer.trim()}
              className="btn-primary btn-sm shrink-0"
            >
              Elegir
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function SourcesPanel({
  session,
  busy,
  onChangeMode,
  onAddFile,
  onAddUrl,
  onDelete,
}: {
  session: IdeationSession;
  busy: boolean;
  onChangeMode: (mode: ResearchMode) => Promise<void>;
  onAddFile: (file: File) => Promise<void>;
  onAddUrl: (url: string) => Promise<void>;
  onDelete: (sourceId: string) => Promise<void>;
}) {
  const [url, setUrl] = useState("");
  const editable = session.status === "active";
  return (
    <section className="card overflow-hidden">
      <div className="border-b border-white/[0.06] px-5 py-3">
        <h3 className="text-sm font-semibold text-zinc-200">
          Fuentes de investigación
        </h3>
      </div>
      <div className="space-y-4 p-5">
        <label className="block">
          <span className="label">Política</span>
          <select
            value={session.research_mode}
            disabled={!editable || busy}
            onChange={(event) =>
              void onChangeMode(event.target.value as ResearchMode)
            }
            className="input"
          >
            {Object.entries(RESEARCH_MODE_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        {session.research_mode !== "web_only" && editable && (
          <div className="space-y-2">
            <label className="btn-secondary w-full cursor-pointer justify-center">
              <IconUpload size={14} />
              Adjuntar documento
              <input
                type="file"
                accept=".pdf,.docx,.pptx,.md,.markdown,.txt"
                className="sr-only"
                disabled={busy || session.sources.length >= 10}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) void onAddFile(file);
                  event.target.value = "";
                }}
              />
            </label>
            <form
              className="flex gap-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (!url.trim()) return;
                void onAddUrl(url.trim()).then(() => setUrl(""));
              }}
            >
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                disabled={busy || session.sources.length >= 10}
                placeholder="URL HTML o PDF"
                className="input min-w-0 flex-1 py-1.5 text-xs"
              />
              <button
                type="submit"
                disabled={busy || !url.trim()}
                className="btn-secondary btn-sm"
                aria-label="Añadir URL"
              >
                <IconPlus size={13} />
              </button>
            </form>
          </div>
        )}
        {session.sources.length === 0 ? (
          <p className="text-xs leading-relaxed text-zinc-500">
            {session.research_mode === "web_only"
              ? "Esta sesión no usa un corpus proporcionado."
              : "Todavía no hay fuentes. Puedes añadir hasta 10."}
          </p>
        ) : (
          <ul className="space-y-2">
            {session.sources.map((source) => (
              <li
                key={source.id}
                className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5"
              >
                <div className="flex items-start gap-2">
                  <IconFileText
                    size={13}
                    className={
                      source.status === "ready"
                        ? "mt-0.5 text-emerald-300"
                        : "mt-0.5 text-red-300"
                    }
                  />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium text-zinc-300">
                      {source.name}
                    </p>
                    <p className="mt-0.5 text-[10px] text-zinc-600">
                      {source.status === "ready"
                        ? `${source.kind.toUpperCase()} · ${(source.size_bytes / 1024).toFixed(0)} KB · ${source.sha256.slice(0, 8)}`
                        : source.error}
                    </p>
                    {source.status === "ready" && (
                      <p className="mt-1 flex gap-3 text-[10px]">
                        <a
                          href={`/api/ideation/sources/${source.id}/original`}
                          className="text-indigo-300 hover:underline"
                        >
                          Original
                        </a>
                        <a
                          href={`/api/ideation/sources/${source.id}/text`}
                          target="_blank"
                          rel="noreferrer"
                          className="text-indigo-300 hover:underline"
                        >
                          Texto extraído
                        </a>
                      </p>
                    )}
                  </div>
                  {editable && (
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void onDelete(source.id)}
                      className="text-zinc-600 hover:text-red-300"
                      aria-label={`Eliminar ${source.name}`}
                    >
                      <IconTrash size={13} />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
        <p className="text-[10px] leading-relaxed text-zinc-600">
          Las URL se capturan una sola vez. El hash y el texto extraído quedan
          congelados con el proyecto.
        </p>
      </div>
    </section>
  );
}

function BriefPanel({
  brief,
  status,
  finalizing,
  onFinalize,
}: {
  brief: CourseIdeaBrief | null;
  status: string;
  finalizing: boolean;
  onFinalize: () => void;
}) {
  if (!brief) {
    return (
      <div className="card border-dashed p-5 text-sm leading-relaxed text-zinc-500">
        El brief del curso aparecerá aquí cuando la idea esté suficientemente
        afinada.
      </div>
    );
  }
  const row = (label: string, value: string) =>
    value ? (
      <div>
        <dt className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          {label}
        </dt>
        <dd className="mt-0.5 text-sm text-zinc-200">{value}</dd>
      </div>
    ) : null;
  const list = (label: string, values: string[]) =>
    values.length > 0 ? (
      <div>
        <dt className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
          {label}
        </dt>
        <dd className="mt-1">
          <ul className="space-y-1 text-sm text-zinc-300">
            {values.map((v) => (
              <li key={v} className="flex gap-2">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-indigo-400" />
                {v}
              </li>
            ))}
          </ul>
        </dd>
      </div>
    ) : null;

  return (
    <div className="card animate-in overflow-hidden">
      <div className="border-b border-emerald-400/15 bg-emerald-500/[0.07] px-5 py-3">
        <h3 className="text-sm font-semibold text-emerald-300">
          Brief del curso
        </h3>
      </div>
      <dl className="space-y-4 p-5">
        {row("Título", brief.working_title)}
        {row("Tema", brief.topic)}
        {row("Audiencia", brief.audience)}
        {row("Nivel", brief.level)}
        {row("Idioma", brief.language)}
        {row("Estilo", brief.style)}
        {row("Formato", brief.output_format)}
        {row(
          "Investigación",
          RESEARCH_MODE_LABELS[brief.research_mode ?? "web_only"],
        )}
        {(brief.source_ids?.length ?? 0) > 0 &&
          row("Corpus", `${brief.source_ids.length} fuentes congeladas`)}
        {brief.duration_spec ? (
          <>
            {row(
              "Duración",
              `${brief.duration_spec.total_videos} vídeos · ${brief.duration_spec.total_minutes} min`,
            )}
            {row(
              "Estructura",
              `${brief.duration_spec.module_count} módulos · ${brief.duration_spec.videos_per_module} vídeos por módulo · ${brief.duration_spec.target_minutes_per_video} min por vídeo`,
            )}
          </>
        ) : (
          <div className="rounded-lg border border-amber-400/25 bg-amber-500/[0.07] p-3 text-sm text-amber-200">
            Falta elegir la duración. Pídele al asistente un preset o una
            estructura personalizada antes de crear el proyecto.
          </div>
        )}
        {list("Objetivos", brief.objectives)}
        {list("Alcance", brief.scope_outline)}
        {row("Ángulo diferencial", brief.differential_angle)}
        {list("Cuestiones abiertas", brief.open_questions)}
      </dl>
      <div className="border-t border-white/[0.06] p-5 pt-4">
        {status === "active" ? (
          <>
            <button
              onClick={onFinalize}
              disabled={finalizing || !brief.duration_spec}
              className="btn-success w-full"
            >
              {finalizing
                ? "Creando proyecto…"
                : brief.duration_spec
                  ? "Crear proyecto desde este brief"
                  : "Completa la duración en el chat"}
            </button>
            <p className="mt-2.5 text-center text-xs text-zinc-500">
              ¿Quieres cambiar algo? Pídeselo al asistente en el chat.
            </p>
          </>
        ) : (
          <p className="text-center text-sm font-medium text-emerald-400">
            Proyecto creado ✓
          </p>
        )}
      </div>
    </div>
  );
}

export default function IdeationSessionPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [session, setSession] = useState<IdeationSession | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [finalizing, setFinalizing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [liveProgress, setLiveProgress] = useState<IdeationProgress[]>([]);
  const [sourceBusy, setSourceBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.getIdeation(id).then(setSession).catch(() => {});
  }, [id]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [session?.messages.length, sending]);

  async function send(content: string) {
    if (!content.trim() || sending) return;
    setError(null);
    setSending(true);
    setLiveProgress([]);
    setInput("");
    try {
      setSession(
        await api.sendIdeationMessageStream(id, content, (event) =>
          setLiveProgress((previous) => [...previous, event]),
        ),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al enviar");
    } finally {
      setSending(false);
      setLiveProgress([]);
    }
  }

  async function finalize() {
    setFinalizing(true);
    setError(null);
    try {
      const project = await api.finalizeIdeation(id);
      router.push(`/projects/${project.id}`);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudo crear el proyecto",
      );
      setFinalizing(false);
    }
  }

  async function mutateSources(action: () => Promise<unknown>) {
    setSourceBusy(true);
    setError(null);
    try {
      await action();
      setSession(await api.getIdeation(id));
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "No se pudo actualizar las fuentes",
      );
    } finally {
      setSourceBusy(false);
    }
  }

  if (!session) {
    return <LoadingScreen label="Cargando sesión…" />;
  }

  const lastQuestionSeq = [...session.messages]
    .reverse()
    .find((m) => m.kind === "question")?.seq;
  const isLastMessageQuestion =
    session.messages.length > 0 &&
    session.messages[session.messages.length - 1].kind === "question";

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <Link
          href="/ideation"
          className="inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <IconChevronLeft size={15} />
          Sesiones de ideación
        </Link>
        {session.project_id && (
          <Link
            href={`/projects/${session.project_id}`}
            className="text-sm font-medium text-emerald-400 hover:underline"
          >
            Ver proyecto →
          </Link>
        )}
      </div>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_340px]">
        <section className="flex min-h-[60vh] flex-col">
          <div className="flex-1 space-y-4">
            {session.messages.map((m) => {
              if (m.kind === "progress") {
                return <ProgressLine key={m.id} event={m as IdeationProgress} />;
              }
              if (m.kind === "question") {
                return (
                  <QuestionCard
                    key={m.id}
                    message={m}
                    disabled={
                      sending ||
                      session.status !== "active" ||
                      !isLastMessageQuestion ||
                      m.seq !== lastQuestionSeq
                    }
                    onAnswer={send}
                  />
                );
              }
              if (m.kind === "search") {
                return (
                  <details
                    key={m.id}
                    className="ml-10 rounded-xl border border-white/[0.07] bg-white/[0.02] px-4 py-2.5 text-xs text-zinc-400"
                  >
                    <summary className="flex cursor-pointer items-center gap-2">
                      <IconSearch size={13} className="shrink-0 text-sky-300" />
                      Búsqueda web:{" "}
                      <span className="font-medium text-zinc-300">
                        {(m.payload as { query?: string })?.query ?? ""}
                      </span>
                    </summary>
                    <Markdown className="mt-2 text-xs">
                      {m.content}
                    </Markdown>
                  </details>
                );
              }
              if (m.kind === "source") {
                return (
                  <details
                    key={m.id}
                    className="ml-10 rounded-xl border border-emerald-400/15 bg-emerald-500/[0.04] px-4 py-2.5 text-xs text-zinc-400"
                  >
                    <summary className="flex cursor-pointer items-center gap-2">
                      <IconFileText size={13} className="text-emerald-300" />
                      Consulta al corpus:{" "}
                      <span className="font-medium text-zinc-300">
                        {(m.payload as { query?: string; source_id?: string })
                          ?.query ??
                          (m.payload as { source_id?: string })?.source_id ??
                          "fuentes disponibles"}
                      </span>
                    </summary>
                    <Markdown className="mt-2 text-xs">{m.content}</Markdown>
                  </details>
                );
              }
              if (m.kind === "brief") {
                return (
                  <p
                    key={m.id}
                    className="ml-10 flex items-center gap-2 text-sm text-emerald-400"
                  >
                    <IconSparkles size={14} />
                    El asistente ha propuesto un brief (panel lateral).
                  </p>
                );
              }
              if (m.role === "user") {
                return (
                  <div key={m.id} className="flex justify-end">
                    <div className="animate-in max-w-[85%] rounded-2xl rounded-br-sm border border-indigo-400/25 bg-gradient-to-b from-indigo-500/25 to-indigo-600/15 px-4 py-2.5 text-sm text-zinc-100">
                      <p className="whitespace-pre-wrap leading-relaxed">
                        {m.content}
                      </p>
                    </div>
                  </div>
                );
              }
              return (
                <div key={m.id} className="flex gap-3">
                  <AssistantAvatar />
                  <div className="animate-in max-w-[85%] rounded-2xl rounded-tl-sm border border-white/[0.07] bg-white/[0.03] px-4 py-2.5 text-sm text-zinc-200">
                    <Markdown className="text-sm">
                      {m.content}
                    </Markdown>
                  </div>
                </div>
              );
            })}
            {sending && (
              <div className="space-y-2">
                {liveProgress.map((event) => (
                  <ProgressLine key={event.id} event={event} />
                ))}
                <div className="flex items-center gap-3">
                  <AssistantAvatar />
                  <div className="flex items-center gap-1 rounded-2xl rounded-tl-sm border border-white/[0.07] bg-white/[0.03] px-4 py-3">
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                    <span className="typing-dot" />
                  </div>
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {session.status === "active" && !isLastMessageQuestion && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send(input);
              }}
              className="card sticky bottom-4 mt-6 flex gap-2 p-2"
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={sending}
                placeholder="Escribe tu respuesta o comentario…"
                className="input flex-1 border-transparent bg-transparent shadow-none focus:border-transparent focus:bg-transparent focus:ring-0"
              />
              <button
                type="submit"
                disabled={sending || !input.trim()}
                className="btn-primary"
              >
                {sending ? <Spinner className="border-white/40 border-t-white" /> : "Enviar"}
              </button>
            </form>
          )}
          {error && <ErrorBanner>{error}</ErrorBanner>}
        </section>

        <aside className="space-y-4 lg:sticky lg:top-8 lg:self-start">
          <SourcesPanel
            session={session}
            busy={sourceBusy}
            onChangeMode={(mode) =>
              mutateSources(() => api.updateIdeationResearchMode(id, mode))
            }
            onAddFile={(file) =>
              mutateSources(() => api.addIdeationSourceFile(id, file))
            }
            onAddUrl={(sourceUrl) =>
              mutateSources(() => api.addIdeationSourceUrl(id, sourceUrl))
            }
            onDelete={(sourceId) =>
              mutateSources(() => api.deleteIdeationSource(id, sourceId))
            }
          />
          <BriefPanel
            brief={session.brief}
            status={session.status}
            finalizing={finalizing}
            onFinalize={finalize}
          />
        </aside>
      </div>
    </div>
  );
}
