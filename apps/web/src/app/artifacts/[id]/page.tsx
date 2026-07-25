"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  api,
  type Artifact,
  type PaletteOptions,
  type SlidePalette,
} from "@/lib/api";
import YouTubePublish from "@/components/YouTubePublish";
import Markdown from "@/components/Markdown";
import SlideDeck from "@/components/SlideDeck";
import JsonViewer from "@/components/JsonViewer";
import SlidePaletteEditor, { paletteWarnings } from "@/components/SlidePaletteEditor";
import {
  ConfirmDialog,
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

function paletteLabel(metadata: Record<string, unknown>): string | null {
  const labels: Record<string, string> = {
    factory: "Factory",
    neutral_light: "Neutro claro",
    dark: "Oscuro",
    high_contrast: "Alto contraste",
    warm: "Cálido",
    custom: "Personalizada",
  };
  return typeof metadata.palette_name === "string"
    ? `Paleta ${labels[metadata.palette_name] ?? metadata.palette_name}`
    : null;
}

function logoLabel(metadata: Record<string, unknown>): string | null {
  if (typeof metadata.logo !== "object" || metadata.logo === null) return null;
  const logo = metadata.logo as Record<string, unknown>;
  return typeof logo.name === "string" && logo.name ? `Logo ${logo.name}` : "Con logo";
}

interface SlideImageMetadata {
  id: string;
  slide: number;
  prompt: string;
  layout: "left" | "right" | "background";
  model: string;
  style: string;
  status: "generated" | "failed";
  cost_usd?: number | null;
  error?: string;
}

function slideImages(metadata: Record<string, unknown>): SlideImageMetadata[] {
  if (!Array.isArray(metadata.images)) return [];
  return metadata.images.filter(
    (item): item is SlideImageMetadata =>
      typeof item === "object" &&
      item !== null &&
      typeof (item as { id?: unknown }).id === "string" &&
      typeof (item as { slide?: unknown }).slide === "number" &&
      typeof (item as { prompt?: unknown }).prompt === "string",
  );
}

export default function ArtifactViewerPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [imagePrompts, setImagePrompts] = useState<Record<string, string>>({});
  const [regeneratingImage, setRegeneratingImage] = useState<string | null>(null);
  const [paletteOptions, setPaletteOptions] = useState<PaletteOptions | null>(null);
  const [editingPalette, setEditingPalette] = useState(false);
  const [slidePalette, setSlidePalette] = useState<SlidePalette | null>(null);
  const [paletteScope, setPaletteScope] = useState<"deck" | "project">("deck");
  const [paletteWarningsAccepted, setPaletteWarningsAccepted] = useState(false);
  const [palettePreview, setPalettePreview] = useState<string | null>(null);
  const [previewingPalette, setPreviewingPalette] = useState(false);
  const [confirmPalette, setConfirmPalette] = useState(false);
  const [applyingPalette, setApplyingPalette] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setArtifact(null);
    setNotFound(false);
    setEditing(false);
    setError(null);
    Promise.all([api.getArtifact(id), api.getPaletteOptions()])
      .then(([value, palettes]) => {
        setArtifact(value);
        setPaletteOptions(palettes);
        setDraft(value.content ?? "");
        setImagePrompts(
          Object.fromEntries(
            slideImages(value.metadata).map((image) => [image.id, image.prompt]),
          ),
        );
      })
      .catch(() => setNotFound(true));
  }, [id]);

  useEffect(
    () => () => {
      if (palettePreview) URL.revokeObjectURL(palettePreview);
    },
    [palettePreview],
  );

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

  async function regenerateImage(image: SlideImageMetadata) {
    if (!artifact) return;
    const prompt = (imagePrompts[image.id] ?? image.prompt).trim();
    if (!prompt) {
      setError("El prompt de la imagen no puede estar vacío.");
      return;
    }
    setRegeneratingImage(image.id);
    setError(null);
    try {
      const updated = await api.regenerateSlideImage(artifact.id, image.id, prompt);
      setArtifact(updated);
      router.replace("/artifacts/" + updated.id);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "No se pudo regenerar la imagen",
      );
    } finally {
      setRegeneratingImage(null);
    }
  }

  function openPaletteEditor() {
    if (!artifact || !paletteOptions) return;
    const stored = artifact.metadata.slide_palette;
    setSlidePalette(
      typeof stored === "object" && stored !== null
        ? (stored as SlidePalette)
        : paletteOptions.default,
    );
    setPaletteScope("deck");
    setPaletteWarningsAccepted(false);
    setEditingPalette(true);
    setError(null);
  }

  async function refreshPalettePreview() {
    if (!artifact || !slidePalette) return;
    setPreviewingPalette(true);
    setError(null);
    try {
      const blob = await api.previewSlidePalette(artifact.id, slidePalette);
      if (palettePreview) URL.revokeObjectURL(palettePreview);
      setPalettePreview(URL.createObjectURL(blob));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "No se pudo generar la preview");
    } finally {
      setPreviewingPalette(false);
    }
  }

  async function applyPalette() {
    if (!artifact || !slidePalette) return;
    setApplyingPalette(true);
    setError(null);
    try {
      const created = await api.applySlidePalette(artifact.id, slidePalette, paletteScope);
      const current = created.find((item) => item.logical_key === artifact.logical_key) ?? created[0];
      setArtifact(current);
      setEditingPalette(false);
      setConfirmPalette(false);
      router.replace("/artifacts/" + current.id);
    } catch (reason) {
      setConfirmPalette(false);
      setError(reason instanceof Error ? reason.message : "No se pudo aplicar la paleta");
    } finally {
      setApplyingPalette(false);
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
  const images = slideImages(artifact.metadata);
  const generation =
    typeof artifact.metadata.image_generation === "object" &&
    artifact.metadata.image_generation !== null
      ? (artifact.metadata.image_generation as Record<string, unknown>)
      : null;

  return (
    <>
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
          {artifact.type === "slide_deck" && !editing && (
            <button type="button" onClick={openPaletteEditor} className="btn-primary btn-sm">
              Cambiar paleta
            </button>
          )}
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
            {paletteLabel(artifact.metadata) && (
              <span className="badge-info">{paletteLabel(artifact.metadata)}</span>
            )}
            {logoLabel(artifact.metadata) && (
              <span className="badge-info">{logoLabel(artifact.metadata)}</span>
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
                  {paletteLabel(version.metadata)
                    ? ` · ${paletteLabel(version.metadata)}`
                    : ""}
                  {logoLabel(version.metadata) ? ` · ${logoLabel(version.metadata)}` : ""}
                  {version.is_selected ? " · activa" : ""}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {editingPalette && paletteOptions && slidePalette && (
        <section className="card mb-6 p-4 sm:p-6">
          <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold text-zinc-100">Cambiar paleta</h2>
              <p className="mt-1 text-xs text-zinc-500">
                Crea nuevas versiones autosuficientes, clona los assets y no usa LLM ni
                regenera imágenes.
              </p>
            </div>
            <button
              type="button"
              onClick={() => {
                setEditingPalette(false);
                setError(null);
              }}
              className="btn-secondary btn-sm"
            >
              Cerrar
            </button>
          </div>
          <div className="grid gap-6 xl:grid-cols-2">
            <div>
              <SlidePaletteEditor
                palette={slidePalette}
                options={paletteOptions}
                onChange={(value) => {
                  setSlidePalette(value);
                  setPaletteWarningsAccepted(false);
                }}
              />
              {paletteWarnings(slidePalette).length > 0 && (
                <label className="mt-3 flex cursor-pointer items-start gap-2 text-xs text-amber-100">
                  <input
                    type="checkbox"
                    checked={paletteWarningsAccepted}
                    onChange={(event) => setPaletteWarningsAccepted(event.target.checked)}
                  />
                  Confirmo la aplicación pese a las advertencias WCAG.
                </label>
              )}
              <div className="mt-5 space-y-2">
                <label className="card flex cursor-pointer items-start gap-3 px-4 py-3 text-sm">
                  <input
                    type="radio"
                    checked={paletteScope === "deck"}
                    onChange={() => setPaletteScope("deck")}
                  />
                  <span>
                    <span className="block font-semibold text-zinc-200">Este deck</span>
                    <span className="text-xs text-zinc-500">Solo {artifact.title}</span>
                  </span>
                </label>
                <label className="card flex cursor-pointer items-start gap-3 px-4 py-3 text-sm">
                  <input
                    type="radio"
                    checked={paletteScope === "project"}
                    onChange={() => setPaletteScope("project")}
                  />
                  <span>
                    <span className="block font-semibold text-zinc-200">
                      Todos los decks activos del proyecto
                    </span>
                    <span className="text-xs text-zinc-500">
                      Se validan y renderizan todos antes de publicar las versiones.
                    </span>
                  </span>
                </label>
              </div>
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={refreshPalettePreview}
                  disabled={previewingPalette}
                  className="btn-secondary btn-sm"
                >
                  {previewingPalette ? "Generando preview…" : "Actualizar preview canónica"}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmPalette(true)}
                  disabled={
                    paletteWarnings(slidePalette).length > 0 && !paletteWarningsAccepted
                  }
                  className="btn-primary btn-sm"
                >
                  Aplicar como nueva versión
                </button>
              </div>
            </div>
            <div>
              {palettePreview ? (
                <iframe
                  src={palettePreview}
                  title="Preview canónica de la nueva paleta"
                  className={`w-full rounded-md border-2 border-zinc-300 bg-white ${
                    artifactOrientation(artifact) === "vertical"
                      ? "mx-auto aspect-[9/16] max-w-md"
                      : "aspect-video"
                  }`}
                />
              ) : (
                <div className="flex min-h-64 items-center justify-center rounded-lg border border-dashed border-white/[0.12] px-8 text-center text-sm text-zinc-500">
                  Genera la preview para comprobar el HTML exacto de Marp antes de crear
                  la nueva versión.
                </div>
              )}
            </div>
          </div>
          <ErrorBanner>{error}</ErrorBanner>
        </section>
      )}

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
            <>
              <div className="card mb-6 p-4 sm:p-6">
                <SlideDeck
                  artifactId={artifact.id}
                  orientation={artifactOrientation(artifact) ?? "horizontal"}
                />
              </div>
              {images.length > 0 && (
                <section className="card mb-6 p-4 sm:p-6">
                  <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="text-base font-semibold text-zinc-100">
                        Imágenes generadas
                      </h2>
                      <p className="mt-1 text-xs text-zinc-500">
                        Edita un prompt y regenera solo esa imagen. Al guardar se creará
                        automáticamente la v{artifact.version + 1} del deck.
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-2 text-xs">
                      {typeof generation?.model === "string" && (
                        <span className="badge-neutral">{generation.model}</span>
                      )}
                      {typeof generation?.style === "string" && (
                        <span className="badge-info">{generation.style}</span>
                      )}
                      {typeof generation?.generation_cost_usd === "number" && (
                        <span className="badge-neutral">
                          ${generation.generation_cost_usd.toFixed(4)} esta versión
                        </span>
                      )}
                    </div>
                  </div>
                  <ErrorBanner>{error}</ErrorBanner>
                  <div className="grid gap-5 lg:grid-cols-2">
                    {images.map((image) => (
                      <article
                        key={image.id}
                        className="overflow-hidden rounded-xl border border-white/[0.09] bg-black/20"
                      >
                        {image.status === "generated" ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={`/api/artifacts/${artifact.id}/images/${encodeURIComponent(image.id)}`}
                            alt={`Ilustración generada para la slide ${image.slide}`}
                            className="aspect-video w-full bg-black object-cover"
                          />
                        ) : (
                          <div className="flex aspect-video items-center justify-center bg-amber-500/[0.08] px-6 text-center text-sm text-amber-200">
                            La generación falló. Puedes ajustar el prompt y volver a intentarlo.
                          </div>
                        )}
                        <div className="space-y-3 p-4">
                          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                            <span className="font-semibold text-zinc-200">
                              Slide {image.slide}
                            </span>
                            <span className="badge-neutral">{image.layout}</span>
                          </div>
                          <textarea
                            value={imagePrompts[image.id] ?? image.prompt}
                            onChange={(event) =>
                              setImagePrompts((current) => ({
                                ...current,
                                [image.id]: event.target.value,
                              }))
                            }
                            rows={4}
                            className="input resize-y text-sm leading-relaxed"
                            aria-label={`Prompt de la imagen de la slide ${image.slide}`}
                          />
                          {image.error && (
                            <p className="text-xs text-amber-300/80">{image.error}</p>
                          )}
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="font-mono text-[10px] text-zinc-500">
                              {image.model}
                            </span>
                            <button
                              type="button"
                              onClick={() => regenerateImage(image)}
                              disabled={regeneratingImage !== null}
                              className="btn-primary btn-sm"
                            >
                              {regeneratingImage === image.id
                                ? "Generando…"
                                : `Regenerar y guardar v${artifact.version + 1}`}
                            </button>
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                </section>
              )}
            </>
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
    <ConfirmDialog
      open={confirmPalette}
      title="Aplicar nueva paleta"
      description={
        paletteScope === "project"
          ? "Se crearán nuevas versiones de todos los decks activos del proyecto. Las versiones anteriores permanecerán intactas."
          : `Se creará la versión ${artifact.version + 1} de «${artifact.title}» y la actual permanecerá intacta.`
      }
      busy={applyingPalette}
      onCancel={() => setConfirmPalette(false)}
      onConfirm={applyPalette}
    />
    </>
  );
}
