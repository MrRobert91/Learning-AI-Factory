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

function QuestionCard({
  message,
  disabled,
  onAnswer,
}: {
  message: IdeationMessage;
  disabled: boolean;
  onAnswer: (text: string) => void;
}) {
  const options = (message.payload as { options?: IdeationOption[] })?.options ?? [];
  return (
    <div className="rounded-xl border border-indigo-900/60 bg-indigo-950/30 p-4">
      <p className="mb-3 text-sm font-medium">{message.content}</p>
      <div className="grid gap-2 sm:grid-cols-2">
        {options.map((o) => (
          <button
            key={o.label}
            disabled={disabled}
            onClick={() => onAnswer(o.label)}
            className="rounded-lg border border-neutral-700 bg-neutral-900 p-3 text-left text-sm transition hover:border-indigo-500 disabled:cursor-default disabled:opacity-60 disabled:hover:border-neutral-700"
          >
            <span className="font-medium">{o.label}</span>
            {o.description && (
              <span className="mt-1 block text-xs text-neutral-400">
                {o.description}
              </span>
            )}
          </button>
        ))}
      </div>
      {!disabled && (
        <p className="mt-2 text-xs text-neutral-500">
          …o responde con texto libre abajo.
        </p>
      )}
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
      <div className="rounded-xl border border-dashed border-neutral-800 p-4 text-sm text-neutral-500">
        El brief aparecerá aquí cuando la idea esté suficientemente afinada.
      </div>
    );
  }
  const row = (label: string, value: string) =>
    value ? (
      <div>
        <dt className="text-xs uppercase tracking-wide text-neutral-500">
          {label}
        </dt>
        <dd className="text-sm">{value}</dd>
      </div>
    ) : null;
  const list = (label: string, values: string[]) =>
    values.length > 0 ? (
      <div>
        <dt className="text-xs uppercase tracking-wide text-neutral-500">
          {label}
        </dt>
        <dd>
          <ul className="list-inside list-disc text-sm">
            {values.map((v) => (
              <li key={v}>{v}</li>
            ))}
          </ul>
        </dd>
      </div>
    ) : null;

  return (
    <div className="rounded-xl border border-emerald-900/60 bg-emerald-950/20 p-4">
      <h3 className="mb-3 text-sm font-semibold text-emerald-300">
        Brief del curso
      </h3>
      <dl className="space-y-3">
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
      {status === "active" ? (
        <button
          onClick={onFinalize}
          disabled={finalizing}
          className="mt-4 w-full rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium hover:bg-emerald-500 disabled:opacity-50"
        >
          {finalizing ? "Creando proyecto…" : "Crear proyecto desde este brief"}
        </button>
      ) : (
        <p className="mt-4 text-sm text-emerald-400">Proyecto creado ✓</p>
      )}
      <p className="mt-2 text-xs text-neutral-500">
        ¿Quieres cambiar algo? Pídeselo al asistente en el chat.
      </p>
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
  }, [session?.messages.length]);

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
      setError(err instanceof Error ? err.message : "No se pudo crear el proyecto");
      setFinalizing(false);
    }
  }

  if (!session) {
    return (
      <main className="mx-auto max-w-5xl p-6 text-neutral-400">Cargando…</main>
    );
  }

  const lastQuestionSeq = [...session.messages]
    .reverse()
    .find((m) => m.kind === "question")?.seq;
  const isLastMessageQuestion =
    session.messages.length > 0 &&
    session.messages[session.messages.length - 1].kind === "question";

  return (
    <main className="mx-auto max-w-5xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <Link href="/ideation" className="text-sm text-indigo-400 hover:underline">
          ← Sesiones de ideación
        </Link>
        {session.project_id && (
          <Link
            href={`/projects/${session.project_id}`}
            className="text-sm text-emerald-400 hover:underline"
          >
            Ver proyecto →
          </Link>
        )}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
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
                    className="rounded-lg border border-neutral-800 p-3 text-xs text-neutral-400"
                  >
                    <summary className="cursor-pointer">
                      🔎 Búsqueda web:{" "}
                      {(m.payload as { query?: string })?.query ?? ""}
                    </summary>
                    <pre className="mt-2 whitespace-pre-wrap">{m.content}</pre>
                  </details>
                );
              }
              if (m.kind === "brief") {
                return (
                  <p key={m.id} className="text-sm text-emerald-400">
                    ✦ El asistente ha propuesto un brief (panel lateral).
                  </p>
                );
              }
              return (
                <div
                  key={m.id}
                  className={
                    m.role === "user"
                      ? "ml-auto max-w-[85%] rounded-xl bg-indigo-600/20 px-4 py-2 text-sm"
                      : "max-w-[85%] rounded-xl bg-neutral-900 px-4 py-2 text-sm"
                  }
                >
                  <p className="whitespace-pre-wrap">{m.content}</p>
                </div>
              );
            })}
            {sending && (
              <p className="text-sm text-neutral-500">El asistente está pensando…</p>
            )}
            <div ref={bottomRef} />
          </div>

          {session.status === "active" && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                send(input);
              }}
              className="mt-6 flex gap-2"
            >
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                disabled={sending}
                placeholder="Escribe tu respuesta o comentario…"
                className="flex-1 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
              <button
                type="submit"
                disabled={sending || !input.trim()}
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
              >
                Enviar
              </button>
            </form>
          )}
          {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
        </section>

        <aside>
          <BriefPanel
            brief={session.brief}
            status={session.status}
            finalizing={finalizing}
            onFinalize={finalize}
          />
        </aside>
      </div>
    </main>
  );
}
