"use client";

import { useEffect, useState } from "react";
import { api, type Job } from "@/lib/api";
import { ConfirmDialog, ErrorBanner, IconYoutube, Spinner } from "@/components/ui";

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
  const [confirmPublish, setConfirmPublish] = useState(false);

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
    setConfirmPublish(false);
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
    <div className="card mb-6 overflow-hidden">
      <div className="flex items-center gap-2.5 border-b border-red-400/15 bg-red-500/[0.06] px-5 py-3">
        <IconYoutube size={17} className="text-red-400" />
        <h3 className="text-sm font-semibold text-zinc-100">
          Publicar en YouTube
        </h3>
      </div>
      <div className="p-5">
        {!status.configured ? (
          <p className="text-sm leading-relaxed text-zinc-400">
            YouTube no está configurado. Añade <code>GOOGLE_CLIENT_ID</code> y{" "}
            <code>GOOGLE_CLIENT_SECRET</code> al .env (guía en{" "}
            <code>docs/YOUTUBE.md</code>) o descarga el vídeo y este paquete
            para publicar a mano.
          </p>
        ) : !status.connected ? (
          <button onClick={connect} className="btn-danger">
            <IconYoutube size={15} />
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
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={privacy}
              onChange={(e) => setPrivacy(e.target.value)}
              className="input w-auto"
              aria-label="Privacidad del vídeo"
            >
              <option value="private">Privado</option>
              <option value="unlisted">Oculto</option>
              <option value="public">Público</option>
            </select>
            <button
              onClick={() => setConfirmPublish(true)}
              disabled={publishing}
              className="btn-danger"
            >
              {publishing ? (
                <Spinner className="border-red-300/40 border-t-red-300" />
              ) : (
                <IconYoutube size={15} />
              )}
              {publishing ? "Subiendo…" : "Subir vídeo a YouTube"}
            </button>
          </div>
        )}
        {job?.status === "failed" && (
          <p className="mt-3 text-sm text-red-400">{job.error}</p>
        )}
        {error && (
          <div className="mt-3">
            <ErrorBanner>{error}</ErrorBanner>
          </div>
        )}
        <p className="mt-3 text-xs text-zinc-500">
          La subida nunca es automática: siempre requiere esta confirmación.
        </p>
      </div>
      <ConfirmDialog
        open={confirmPublish}
        title="Publicar en YouTube"
        description={`Vas a subir este vídeo con privacidad «${privacy}». La publicación se realizará en tu canal conectado.`}
        confirmLabel="Confirmar publicación"
        onCancel={() => setConfirmPublish(false)}
        onConfirm={publish}
      />
    </div>
  );
}
