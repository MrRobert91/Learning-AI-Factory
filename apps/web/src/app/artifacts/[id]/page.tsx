"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { api, type Artifact } from "@/lib/api";

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
      <main className="mx-auto max-w-3xl p-6 text-neutral-400">
        Artefacto no encontrado.
      </main>
    );
  }
  if (!artifact) {
    return (
      <main className="mx-auto max-w-3xl p-6 text-neutral-400">Cargando…</main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <Link
          href={`/projects/${artifact.project_id}`}
          className="text-sm text-indigo-400 hover:underline"
        >
          ← Volver al proyecto
        </Link>
        <div className="flex gap-2">
          {artifact.renders.map((fmt) => (
            <a
              key={fmt}
              href={`/api/artifacts/${artifact.id}/render/${fmt}`}
              target={fmt === "html" ? "_blank" : undefined}
              className="rounded-lg border border-neutral-700 px-3 py-1.5 text-sm uppercase text-neutral-300 hover:bg-neutral-900"
            >
              {fmt}
            </a>
          ))}
          <a
            href={`/api/artifacts/${artifact.id}/download`}
            className="rounded-lg border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-900"
          >
            Descargar {artifact.format === "markdown" ? ".md" : ""}
          </a>
        </div>
      </div>
      <h1 className="mb-1 text-2xl font-semibold">
        {artifact.title || artifact.type}
      </h1>
      <p className="mb-6 text-sm text-neutral-500">
        {artifact.type} · {artifact.format} ·{" "}
        {new Date(artifact.created_at).toLocaleString("es")}
      </p>
      {artifact.type === "video" && (
        <video
          controls
          src={`/api/artifacts/${artifact.id}/download`}
          className="mb-6 aspect-video w-full rounded-xl border border-neutral-800 bg-black"
        />
      )}
      {artifact.renders.includes("html") && (
        <iframe
          src={`/api/artifacts/${artifact.id}/render/html`}
          title="Vista previa de slides"
          className="mb-6 aspect-video w-full rounded-xl border border-neutral-800 bg-white"
        />
      )}
      {artifact.content !== null ? (
        <article className="whitespace-pre-wrap rounded-xl border border-neutral-800 bg-neutral-900/50 p-6 font-mono text-sm leading-relaxed">
          {artifact.content}
        </article>
      ) : (
        <p className="text-sm text-neutral-500">
          Este formato no tiene vista previa; usa el botón de descarga.
        </p>
      )}
    </main>
  );
}
