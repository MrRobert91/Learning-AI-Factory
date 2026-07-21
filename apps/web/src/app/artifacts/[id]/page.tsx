"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api, type Artifact } from "@/lib/api";
import YouTubePublish from "@/components/YouTubePublish";
import Markdown from "@/components/Markdown";
import SlideDeck from "@/components/SlideDeck";
import JsonViewer from "@/components/JsonViewer";
import {
  EmptyState,
  ErrorBanner,
  IconChevronLeft,
  IconDownload,
  IconFileText,
  LoadingScreen,
} from "@/components/ui";

const MARKDOWN_TYPES = new Set([
  "research_brief",
  "performance_report",
  "lesson_content",
  "teaching_script",
  "voice_script",
]);

const EDITABLE_FORMATS = new Set(["markdown", "json", "text"]);

const TYPE_LABELS: Record<string, string> = {
  research_brief: "Research brief",
  performance_report: "Informe de rendimiento",
  course_plan: "Plan del curso",
  lesson_content: "Lección",
  slide_deck: "Slides",
  teaching_script: "Guion docente",
  voice_script: "Guion de voz",
  video: "Vídeo",
  subtitles: "Subtítulos",
  publication_package: "Paquete de publicación",
  thumbnail: "Miniatura",
};

function artifactOrientation(
  artifact: Artifact,
): "horizontal" | "vertical" | null {
  return artifact.metadata.orientation === "vertical"
    ? "vertical"
    : artifact.metadata.orientation === "horizontal"
      ? "horizontal"
      : null;
}

function orientationLabel(metadata: Record<string, unknown>): string | null {
  return metadata.orientation === "vertical"
    ? "Vertical 9:16"
    : metadata.orientation === "horizontal"
      ? "Horizontal 16:9"
      : null;
}

export default function ArtifactViewerPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setArtifact(null);
    setNotFound(false);
    setEditing(false);
    setError(null);
    api
      .getArtifact(id)
      .then((value) => {
        setArtifact(value);
        setDraft(value.content ?? "");
      })
      .catch(() => setNotFound(true));
  }, [id]);

  async function saveVersion() {
    if (!artifact) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await api.editArtifact(artifact.id, draft);
      setArtifact(updated);
      setEditing(false);
      router.replace("/artifacts/" + updated.id);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "No se pudo guardar la versión",
      );
    } finally {
      setSaving(false);
    }
  }

  if (notFound) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-16">
        <EmptyState
          icon={<IconFileText size={22} />}
          title="Artefacto no encontrado"
          description="Puede que se haya eliminado junto con su proyecto."
          action={
            <Link href="/" className="btn-secondary">
              <IconChevronLeft size={15} />
              Volver a proyectos
            </Link>
          }
        />
      </div>
    );
  }
  if (!artifact) {
    return <LoadingScreen label="Cargando artefacto…" />;
  }

  const editable =
    artifact.content !== null && EDITABLE_FORMATS.has(artifact.format);

  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Link
          href={"/projects/" + artifact.project_id}
          className="inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <IconChevronLeft size={15} />
          Volver al proyecto
        </Link>
        <div className="flex flex-wrap gap-2">
          {editable && !editing && (
            <button
              type="button"
              onClick={() => {
                setDraft(artifact.content ?? "");
                setEditing(true);
              }}
              className="btn-primary btn-sm"
            >
              Editar texto
            </button>
          )}
          {artifact.renders.map((fmt) => (
            <a
              key={fmt}
              href={"/api/artifacts/" + artifact.id + "/render/" + fmt}
              target={fmt === "html" ? "_blank" : undefined}
              className="btn-secondary btn-sm uppercase"
            >
              {fmt}
            </a>
          ))}
          <a
            href={"/api/artifacts/" + artifact.id + "/download"}
            className="btn-secondary btn-sm"
          >
            <IconDownload size={13} />
            Descargar{artifact.format === "markdown" ? " .md" : ""}
          </a>
        </div>
      </div>

      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="mb-1.5 text-2xl font-semibold tracking-tight text-zinc-50">
            {artifact.title || artifact.type}
          </h1>
          <p className="flex flex-wrap items-center gap-2 text-sm text-zinc-500">
            <span className="badge-neutral">
              {TYPE_LABELS[artifact.type] ?? artifact.type}
            </span>
            <span className="badge-neutral">{artifact.format}</span>
            <span
              className={artifact.is_selected ? "badge-success" : "badge-neutral"}
            >
              v{artifact.version} {artifact.is_selected ? "· activa" : "· histórica"}
            </span>
            {orientationLabel(artifact.metadata) && (
              <span className="badge-info">
                {orientationLabel(artifact.metadata)}
              </span>
            )}
            <span>{new Date(artifact.created_at).toLocaleString("es")}</span>
          </p>
        </div>
        {artifact.versions.length > 1 && (
          <label className="text-xs text-zinc-500">
            Versión
            <select
              value={artifact.id}
              onChange={(event) =>
                router.push("/artifacts/" + event.target.value)
              }
              className="input ml-2 w-auto px-2 py-1.5 text-xs"
            >
              {artifact.versions.map((version) => (
                <option key={version.id} value={version.id}>
                  v{version.version}
                  {orientationLabel(version.metadata)
                    ? ` · ${orientationLabel(version.metadata)}`
                    : ""}
                  {version.is_selected ? " · activa" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {editing ? (
        <section className="card mb-6 p-4 sm:p-6">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-semibold text-zinc-100">
                Editando v{artifact.version}
              </h2>
              <p className="mt-1 text-xs text-zinc-500">
                Al guardar se creará la v{artifact.version + 1}; esta versión no
                se modificará.
              </p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => {
                  setDraft(artifact.content ?? "");
                  setEditing(false);
                  setError(null);
                }}
                disabled={saving}
                className="btn-secondary btn-sm"
              >
                Cancelar
              </button>
              <button
                type="button"
                onClick={saveVersion}
                disabled={saving || draft === artifact.content}
                className="btn-primary btn-sm"
              >
                {saving ? "Guardando…" : "Guardar como nueva versión"}
              </button>
            </div>
          </div>
          <ErrorBanner>{error}</ErrorBanner>
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            spellCheck={artifact.format !== "json"}
            className="input min-h-[65vh] w-full resize-y font-mono text-sm leading-relaxed"
            aria-label="Contenido del artefacto"
          />
        </section>
      ) : (
        <>
          {artifact.type === "publication_package" && (
            <YouTubePublish packageArtifactId={artifact.id} />
          )}
          {artifact.type === "thumbnail" && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={"/api/artifacts/" + artifact.id + "/download"}
              alt="Miniatura del vídeo"
              className="card mb-6 w-full max-w-4xl"
            />
          )}
          {artifact.type === "video" && (
            <video
              controls
              src={"/api/artifacts/" + artifact.id + "/download"}
              className={`card mb-6 w-full bg-black ${
                artifactOrientation(artifact) === "vertical"
                  ? "mx-auto aspect-[9/16] max-w-md"
                  : "aspect-video"
              }`}
            />
          )}
          {artifact.format === "json" && artifact.content !== null ? (
            <article className="card mb-6 p-4 sm:p-6">
              <JsonViewer source={artifact.content} />
            </article>
          ) : artifact.type === "slide_deck" && artifact.content !== null ? (
            <div className="card mb-6 p-4 sm:p-6">
              <SlideDeck
                artifactId={artifact.id}
                orientation={artifactOrientation(artifact) ?? "horizontal"}
              />
            </div>
          ) : MARKDOWN_TYPES.has(artifact.type) && artifact.content !== null ? (
            <article className="card notebook-sheet p-6 sm:p-8">
              <Markdown>{artifact.content}</Markdown>
            </article>
          ) : artifact.content !== null ? (
            <article className="card whitespace-pre-wrap p-6 font-mono text-[13px] leading-relaxed text-zinc-700">
              {artifact.content}
            </article>
          ) : (
            <p className="text-sm text-zinc-500">
              Este formato no tiene vista previa; usa el botón de descarga.
            </p>
          )}
        </>
      )}
    </div>
  );
}
