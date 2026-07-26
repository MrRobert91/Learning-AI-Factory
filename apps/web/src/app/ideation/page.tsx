"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  api,
  type IdeationProgress,
  type IdeationSessionSummary,
  type ResearchMode,
} from "@/lib/api";
import {
  EmptyState,
  ErrorBanner,
  IconLightbulb,
  IconFileText,
  IconPlus,
  IconSparkles,
  IconTrash,
  IconUpload,
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
  const [researchMode, setResearchMode] = useState<ResearchMode>("web_only");
  const [files, setFiles] = useState<File[]>([]);
  const [url, setUrl] = useState("");
  const [urls, setUrls] = useState<string[]>([]);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<IdeationProgress[]>([]);

  useEffect(() => {
    api.listIdeations().then(setSessions).catch(() => {});
  }, []);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setStarting(true);
    setProgress([]);
    try {
      const draft = await api.createIdeationDraft(idea, researchMode);
      const selectedSources =
        researchMode === "web_only" ? [] : [...files, ...urls];
      if (selectedSources.length > 0) {
        setProgress((previous) => [
          ...previous,
          {
            id: "source-upload",
            seq: -1,
            role: "assistant",
            kind: "progress",
            content: `Capturando y extrayendo ${selectedSources.length} fuentes…`,
            payload: { phase: "tool_call", tool: "source_ingestion" },
            created_at: new Date().toISOString(),
          },
        ]);
      }
      await Promise.all([
        ...files.map((file) => api.addIdeationSourceFile(draft.id, file)),
        ...urls.map((sourceUrl) =>
          api.addIdeationSourceUrl(draft.id, sourceUrl),
        ),
      ]);
      const session = await api.startIdeationStream(draft.id, (event) =>
        setProgress((previous) => [...previous, event]),
      );
      router.push(`/ideation/${session.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo crear la sesión");
      setStarting(false);
    }
  }

  function addFiles(nextFiles: File[]) {
    setError(null);
    setFiles((current) => {
      const remaining = Math.max(0, 10 - urls.length - current.length);
      const accepted = nextFiles.slice(0, remaining);
      if (accepted.length < nextFiles.length) {
        setError("Cada sesión admite como máximo 10 fuentes.");
      }
      return [...current, ...accepted];
    });
  }

  function addUrl() {
    const value = url.trim();
    if (!value) return;
    try {
      const parsed = new URL(value);
      if (!["http:", "https:"].includes(parsed.protocol)) throw new Error();
    } catch {
      setError("Escribe una URL pública HTTP o HTTPS válida.");
      return;
    }
    if (files.length + urls.length >= 10) {
      setError("Cada sesión admite como máximo 10 fuentes.");
      return;
    }
    setUrls((current) => [...current, value]);
    setUrl("");
    setError(null);
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
        <fieldset className="mb-5">
          <legend className="label">¿Cómo debe investigar el curso?</legend>
          <div className="grid gap-2 sm:grid-cols-3">
            {(
              [
                [
                  "web_only",
                  "Web libre",
                  "Mantiene el flujo actual de investigación web.",
                ],
                [
                  "provided_plus_web",
                  "Fuentes + web",
                  "Parte de tu corpus y lo complementa claramente.",
                ],
                [
                  "provided_only",
                  "Solo mis fuentes",
                  "Bloquea la web y declara cualquier hueco.",
                ],
              ] as [ResearchMode, string, string][]
            ).map(([value, label, description]) => (
              <label
                key={value}
                className={`cursor-pointer rounded-xl border p-3 transition-colors ${
                  researchMode === value
                    ? "border-indigo-400/60 bg-indigo-500/[0.1]"
                    : "border-white/[0.08] bg-white/[0.02]"
                }`}
              >
                <input
                  type="radio"
                  name="research-mode"
                  value={value}
                  checked={researchMode === value}
                  onChange={() => setResearchMode(value)}
                  className="sr-only"
                />
                <span className="block text-sm font-medium text-zinc-100">
                  {label}
                </span>
                <span className="mt-1 block text-xs leading-relaxed text-zinc-500">
                  {description}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        {researchMode !== "web_only" && (
          <section className="mb-5 space-y-3 rounded-xl border border-white/[0.08] bg-black/10 p-4">
            <div>
              <p className="text-sm font-medium text-zinc-200">
                Fuentes del curso
              </p>
              <p className="mt-1 text-xs text-zinc-500">
                PDF con texto, DOCX, PPTX, Markdown o TXT · máximo 25 MB por
                fichero y 10 fuentes en total.
              </p>
            </div>
            <label
              className="flex cursor-pointer items-center justify-center gap-2 rounded-xl border border-dashed border-zinc-600 px-4 py-5 text-sm text-zinc-400 hover:border-indigo-400/60 hover:text-zinc-200"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault();
                addFiles(Array.from(event.dataTransfer.files));
              }}
            >
              <IconUpload size={16} />
              Arrastra documentos o selecciónalos
              <input
                type="file"
                multiple
                accept=".pdf,.docx,.pptx,.md,.markdown,.txt"
                className="sr-only"
                onChange={(event) =>
                  addFiles(Array.from(event.target.files ?? []))
                }
              />
            </label>
            <div className="flex gap-2">
              <input
                value={url}
                onChange={(event) => setUrl(event.target.value)}
                placeholder="https://ejemplo.com/página-o-documento.pdf"
                className="input min-w-0 flex-1"
              />
              <button type="button" onClick={addUrl} className="btn-secondary">
                <IconPlus size={14} />
                Añadir URL
              </button>
            </div>
            {(files.length > 0 || urls.length > 0) && (
              <ul className="space-y-2">
                {files.map((file, index) => (
                  <li
                    key={`${file.name}-${file.size}-${index}`}
                    className="flex items-center gap-2 rounded-lg bg-white/[0.03] px-3 py-2 text-xs"
                  >
                    <IconFileText size={13} className="text-indigo-300" />
                    <span className="min-w-0 flex-1 truncate text-zinc-300">
                      {file.name}
                    </span>
                    <span className="text-zinc-600">
                      {(file.size / 1024 / 1024).toFixed(1)} MB
                    </span>
                    <button
                      type="button"
                      aria-label={`Quitar ${file.name}`}
                      onClick={() =>
                        setFiles((current) =>
                          current.filter((_, itemIndex) => itemIndex !== index),
                        )
                      }
                      className="text-zinc-500 hover:text-red-300"
                    >
                      <IconTrash size={13} />
                    </button>
                  </li>
                ))}
                {urls.map((sourceUrl, index) => (
                  <li
                    key={`${sourceUrl}-${index}`}
                    className="flex items-center gap-2 rounded-lg bg-white/[0.03] px-3 py-2 text-xs"
                  >
                    <IconFileText size={13} className="text-sky-300" />
                    <span className="min-w-0 flex-1 truncate text-zinc-300">
                      {sourceUrl}
                    </span>
                    <button
                      type="button"
                      aria-label={`Quitar ${sourceUrl}`}
                      onClick={() =>
                        setUrls((current) =>
                          current.filter((_, itemIndex) => itemIndex !== index),
                        )
                      }
                      className="text-zinc-500 hover:text-red-300"
                    >
                      <IconTrash size={13} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
        <ErrorBanner>{error}</ErrorBanner>
        <button
          type="submit"
          disabled={
            starting ||
            !idea.trim() ||
            (researchMode === "provided_only" &&
              files.length + urls.length === 0)
          }
          className="btn-primary"
        >
          {starting ? (
            <Spinner className="border-white/40 border-t-white" />
          ) : (
            <IconSparkles size={15} />
          )}
          {starting ? "Pensando…" : "Empezar a idear"}
        </button>
        {researchMode === "provided_only" &&
          files.length + urls.length === 0 && (
            <p className="mt-2 text-xs text-amber-300">
              Añade al menos una fuente para iniciar en modo estricto.
            </p>
          )}
        {starting && progress.length > 0 && (
          <div className="mt-4 space-y-1.5 border-t border-white/[0.06] pt-4">
            <p className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Actividad del agente
            </p>
            {progress.map((event) => (
              <p key={event.id} className="flex gap-2 text-xs leading-relaxed text-zinc-400">
                <IconSparkles size={12} className="mt-0.5 shrink-0 text-indigo-300" />
                {event.content}
              </p>
            ))}
          </div>
        )}
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
