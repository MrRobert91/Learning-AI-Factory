"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, type Artifact } from "@/lib/api";
import YouTubePublish from "@/components/YouTubePublish";
import {
  EmptyState,
  IconChevronLeft,
  IconDownload,
  IconFileText,
  LoadingScreen,
} from "@/components/ui";

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

export default function ArtifactViewerPage() {
  const { id } = useParams<{ id: string }>();
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    api
      .getArtifact(id)
      .then(setArtifact)
      .catch(() => setNotFound(true));
  }, [id]);

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

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Link
          href={`/projects/${artifact.project_id}`}
          className="inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <IconChevronLeft size={15} />
          Volver al proyecto
        </Link>
        <div className="flex flex-wrap gap-2">
          {artifact.renders.map((fmt) => (
            <a
              key={fmt}
              href={`/api/artifacts/${artifact.id}/render/${fmt}`}
              target={fmt === "html" ? "_blank" : undefined}
              className="btn-secondary btn-sm uppercase"
            >
              {fmt}
            </a>
          ))}
          <a
            href={`/api/artifacts/${artifact.id}/download`}
            className="btn-secondary btn-sm"
          >
            <IconDownload size={13} />
            Descargar{artifact.format === "markdown" ? " .md" : ""}
          </a>
        </div>
      </div>

      <h1 className="mb-1.5 text-2xl font-semibold tracking-tight text-zinc-50">
        {artifact.title || artifact.type}
      </h1>
      <p className="mb-6 flex flex-wrap items-center gap-2 text-sm text-zinc-500">
        <span className="badge-neutral">
          {TYPE_LABELS[artifact.type] ?? artifact.type}
        </span>
        <span className="badge-neutral">{artifact.format}</span>
        <span>{new Date(artifact.created_at).toLocaleString("es")}</span>
      </p>

      {artifact.type === "publication_package" && (
        <YouTubePublish packageArtifactId={artifact.id} />
      )}
      {artifact.type === "thumbnail" && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`/api/artifacts/${artifact.id}/download`}
          alt="Miniatura del vídeo"
          className="card mb-6 w-full max-w-2xl"
        />
      )}
      {artifact.type === "video" && (
        <video
          controls
          src={`/api/artifacts/${artifact.id}/download`}
          className="card mb-6 aspect-video w-full bg-black"
        />
      )}
      {artifact.renders.includes("html") && (
        <iframe
          src={`/api/artifacts/${artifact.id}/render/html`}
          title="Vista previa de slides"
          className="card mb-6 aspect-video w-full bg-white"
        />
      )}
      {artifact.content !== null ? (
        <article className="card whitespace-pre-wrap p-6 font-mono text-[13px] leading-relaxed text-zinc-300">
          {artifact.content}
        </article>
      ) : (
        <p className="text-sm text-zinc-500">
          Este formato no tiene vista previa; usa el botón de descarga.
        </p>
      )}
    </div>
  );
}
