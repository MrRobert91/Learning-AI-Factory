"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  api,
  type CourseIdeaBrief,
  type IdeationMessage,
  type IdeationOption,
  type IdeationSession,
} from "@/lib/api";
import {
  ErrorBanner,
  IconChevronLeft,
  IconSearch,
  IconSparkles,
  LoadingScreen,
  Spinner,
} from "@/components/ui";

function AssistantAvatar() {
  return (
    <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 text-white">
      <IconSparkles size={13} />
    </span>
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
  return (
    <div className="flex gap-3">
      <AssistantAvatar />
      <div className="animate-in min-w-0 flex-1 rounded-2xl rounded-tl-sm border border-indigo-400/20 bg-indigo-500/[0.07] p-4">
        <p className="mb-3 text-sm font-medium text-zinc-100">
          {message.content}
        </p>
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
      </div>
    </div>
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
              disabled={finalizing}
              className="btn-success w-full"
            >
              {finalizing ? "Creando proyecto…" : "Crear proyecto desde este brief"}
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
    setInput("");
    try {
      setSession(await api.sendIdeationMessage(id, content));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al enviar");
    } finally {
      setSending(false);
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
                    <pre className="mt-2 whitespace-pre-wrap leading-relaxed">
                      {m.content}
                    </pre>
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
                    <p className="whitespace-pre-wrap leading-relaxed">
                      {m.content}
                    </p>
                  </div>
                </div>
              );
            })}
            {sending && (
              <div className="flex items-center gap-3">
                <AssistantAvatar />
                <div className="flex items-center gap-1 rounded-2xl rounded-tl-sm border border-white/[0.07] bg-white/[0.03] px-4 py-3">
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                  <span className="typing-dot" />
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {session.status === "active" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send(input);
              }}
              className="sticky bottom-4 mt-6 flex gap-2 rounded-2xl border border-white/[0.08] bg-[#0d0f15]/95 p-2 shadow-[0_8px_30px_rgba(0,0,0,0.4)] backdrop-blur"
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

        <aside className="lg:sticky lg:top-8 lg:self-start">
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
