"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, type IdeationSessionSummary } from "@/lib/api";
import {
  EmptyState,
  ErrorBanner,
  IconLightbulb,
  IconSparkles,
  LoadingScreen,
  PageHeader,
  Spinner,
} from "@/components/ui";

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  finalized: { label: "Proyecto creado", className: "badge-success" },
  brief: { label: "Brief listo", className: "badge-info" },
  active: { label: "En curso", className: "badge-neutral" },
};

function sessionBadge(s: IdeationSessionSummary) {
  if (s.status === "finalized") return STATUS_BADGE.finalized;
  if (s.has_brief) return STATUS_BADGE.brief;
  return STATUS_BADGE.active;
}

export default function IdeationListPage() {
  const router = useRouter();
  const [sessions, setSessions] = useState<IdeationSessionSummary[] | null>(
    null,
  );
  const [idea, setIdea] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listIdeations().then(setSessions).catch(() => {});
  }, []);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setStarting(true);
    try {
      const session = await api.createIdeation(idea);
      router.push(`/ideation/${session.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo crear la sesión");
      setStarting(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <PageHeader
        title="Asistente de ideación"
        description="Cuéntale tu idea aunque sea vaga: te hará preguntas para afinarla hasta tener un brief listo para fabricar el curso."
      />

      <form onSubmit={start} className="card mb-10 p-6">
        <label className="label" htmlFor="idea">
          ¿Sobre qué quieres crear un curso?
        </label>
        <textarea
          id="idea"
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          rows={3}
          required
          placeholder='Ej.: "algo de computación cuántica para gente técnica" o "un curso corto de RAG"'
          className="input mb-4 resize-y"
        />
        <ErrorBanner>{error}</ErrorBanner>
        <button
          type="submit"
          disabled={starting || !idea.trim()}
          className="btn-primary"
        >
          {starting ? (
            <Spinner className="border-white/40 border-t-white" />
          ) : (
            <IconSparkles size={15} />
          )}
          {starting ? "Pensando…" : "Empezar a idear"}
        </button>
      </form>

      <h2 className="mb-3 text-base font-semibold tracking-tight text-zinc-100">
        Sesiones anteriores
      </h2>
      {sessions === null ? (
        <LoadingScreen label="Cargando sesiones…" />
      ) : sessions.length === 0 ? (
        <EmptyState
          icon={<IconLightbulb size={22} />}
          title="Todavía no hay sesiones"
          description="Tu primera conversación con el asistente aparecerá aquí."
        />
      ) : (
        <ul className="space-y-2">
          {sessions.map((s) => {
            const badge = sessionBadge(s);
            return (
              <li key={s.id}>
                <Link
                  href={`/ideation/${s.id}`}
                  className="card card-hover flex items-center gap-3 px-4 py-3 text-sm"
                >
                  <span className="min-w-0 flex-1 truncate text-zinc-200">
                    {s.initial_idea}
                  </span>
                  <span className="shrink-0 text-xs text-zinc-600">
                    {new Date(s.updated_at).toLocaleDateString("es")}
                  </span>
                  <span className={`${badge.className} shrink-0`}>
                    {badge.label}
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
