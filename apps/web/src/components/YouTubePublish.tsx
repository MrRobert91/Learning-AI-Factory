"use client";

import { useEffect, useState } from "react";
import { api, type Job } from "@/lib/api";

export default function YouTubePublish({
  packageArtifactId,
}: {
  packageArtifactId: string;
}) {
  const [status, setStatus] = useState<{
    configured: boolean;
    connected: boolean;
  } | null>(null);
  const [privacy, setPrivacy] = useState("private");
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [publishing, setPublishing] = useState(false);

  useEffect(() => {
    api.youtubeStatus().then(setStatus).catch(() => {});
  }, []);

  async function connect() {
    try {
      const { url } = await api.youtubeAuthUrl();
      window.location.href = url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo iniciar OAuth");
    }
  }

  async function publish() {
    if (
      !confirm(
        `Vas a subir este vídeo a YouTube con privacidad «${privacy}». ¿Confirmas?`,
      )
    ) {
      return;
    }
    setPublishing(true);
    setError(null);
    try {
      const created = await api.youtubePublish(packageArtifactId, privacy);
      // Poll until the upload job finishes
      let current = created;
      while (current.status === "queued" || current.status === "running") {
        await new Promise((r) => setTimeout(r, 1500));
        current = await api.getRun(created.id);
      }
      setJob(current);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo publicar");
    } finally {
      setPublishing(false);
    }
  }

  if (!status) return null;

  const uploadedUrl = job?.result?.["url" as keyof typeof job.result] as
    | string
    | undefined;

  return (
    <div className="mb-6 rounded-xl border border-red-900/50 bg-red-950/20 p-4">
      <h3 className="mb-2 text-sm font-semibold text-red-300">
        ▶ Publicar en YouTube
      </h3>
      {!status.configured ? (
        <p className="text-sm text-neutral-400">
          YouTube no está configurado. Añade <code>GOOGLE_CLIENT_ID</code> y{" "}
          <code>GOOGLE_CLIENT_SECRET</code> al .env (guía en{" "}
          <code>docs/YOUTUBE.md</code>) o descarga el vídeo y este paquete para
          publicar a mano.
        </p>
      ) : !status.connected ? (
        <button
          onClick={connect}
          className="rounded-lg bg-red-700 px-4 py-2 text-sm font-medium hover:bg-red-600"
        >
          Conectar con YouTube (OAuth)
        </button>
      ) : job?.status === "done" && uploadedUrl ? (
        <p className="text-sm text-emerald-400">
          Publicado ✓{" "}
          <a href={uploadedUrl} target="_blank" className="underline">
            {uploadedUrl}
          </a>
        </p>
      ) : (
        <div className="flex items-center gap-2">
          <select
            value={privacy}
            onChange={(e) => setPrivacy(e.target.value)}
            className="rounded-lg border border-neutral-700 bg-neutral-900 px-2 py-2 text-sm outline-none"
          >
            <option value="private">Privado</option>
            <option value="unlisted">Oculto</option>
            <option value="public">Público</option>
          </select>
          <button
            onClick={publish}
            disabled={publishing}
            className="rounded-lg bg-red-700 px-4 py-2 text-sm font-medium hover:bg-red-600 disabled:opacity-50"
          >
            {publishing ? "Subiendo…" : "Subir vídeo a YouTube"}
          </button>
        </div>
      )}
      {job?.status === "failed" && (
        <p className="mt-2 text-sm text-red-400">{job.error}</p>
      )}
      {error && <p className="mt-2 text-sm text-red-400">{error}</p>}
      <p className="mt-2 text-xs text-neutral-500">
        La subida nunca es automática: siempre requiere esta confirmación.
      </p>
    </div>
  );
}
