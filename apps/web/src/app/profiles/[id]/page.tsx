"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  api,
  type AgentProfile,
  type ImageOptions,
  type PaletteOptions,
  type ProfileVersion,
  type SlidePalette,
} from "@/lib/api";
import SlidePaletteEditor, { paletteWarnings } from "@/components/SlidePaletteEditor";
import {
  ConfirmDialog,
  ErrorBanner,
  IconChevronLeft,
  IconStar,
  LoadingScreen,
} from "@/components/ui";

export default function ProfileEditorPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [profile, setProfile] = useState<AgentProfile | null>(null);
  const [versions, setVersions] = useState<ProfileVersion[]>([]);
  const [name, setName] = useState("");
  const [soul, setSoul] = useState("");
  const [agentsMd, setAgentsMd] = useState("");
  const [model, setModel] = useState("");
  const [orientation, setOrientation] = useState<"horizontal" | "vertical">(
    "horizontal",
  );
  const [imageOptions, setImageOptions] = useState<ImageOptions | null>(null);
  const [imagesEnabled, setImagesEnabled] = useState(false);
  const [imageModel, setImageModel] = useState("");
  const [imageStyle, setImageStyle] = useState("");
  const [imageStylePrompt, setImageStylePrompt] = useState("");
  const [automaticReviewEnabled, setAutomaticReviewEnabled] = useState(false);
  const [maxAutomaticRegenerations, setMaxAutomaticRegenerations] = useState(0);
  const [paletteOptions, setPaletteOptions] = useState<PaletteOptions | null>(null);
  const [slidePalette, setSlidePalette] = useState<SlidePalette | null>(null);
  const [paletteWarningsAccepted, setPaletteWarningsAccepted] = useState(false);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function load() {
    const [p, options, palettes] = await Promise.all([
      api.getProfile(id),
      api.getImageOptions(),
      api.getPaletteOptions(),
    ]);
    setProfile(p);
    setImageOptions(options);
    setName(p.name);
    setSoul(p.soul_md);
    setAgentsMd(p.agents_md);
    setModel(p.model ?? "");
    setOrientation(p.orientation ?? "horizontal");
    setImagesEnabled(p.images_enabled ?? false);
    setImageModel(p.image_model ?? options.default_model);
    setImageStyle(p.image_style ?? options.default_style);
    setImageStylePrompt(p.image_style_prompt ?? "");
    setAutomaticReviewEnabled(p.automatic_review_enabled);
    setMaxAutomaticRegenerations(p.max_automatic_regenerations);
    setPaletteOptions(palettes);
    setSlidePalette(p.slide_palette ?? palettes.default);
    setPaletteWarningsAccepted(false);
    setVersions(await api.getProfileVersions(id));
  }

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  // Only the fields that actually changed are sent, so saving never creates
  // spurious versions nor overwrites config the user didn't touch.
  function buildPatch() {
    if (!profile) return null;
    const patch: {
      name?: string;
      soul_md?: string;
      agents_md?: string;
      model?: string;
      orientation?: "horizontal" | "vertical";
      images_enabled?: boolean;
      image_model?: string;
      image_style?: string;
      image_style_prompt?: string;
      automatic_review_enabled?: boolean;
      max_automatic_regenerations?: number;
      slide_palette?: SlidePalette;
      note?: string;
    } = {};
    if (name !== profile.name) patch.name = name;
    if (soul !== profile.soul_md) patch.soul_md = soul;
    if (agentsMd !== profile.agents_md) patch.agents_md = agentsMd;
    // An empty string clears the model override (back to the system default).
    if (model.trim() !== (profile.model ?? "")) patch.model = model.trim();
    if (
      profile.orientation !== null &&
      orientation !== (profile.orientation ?? "horizontal")
    ) {
      patch.orientation = orientation;
    }
    if (profile.images_enabled !== null && imagesEnabled !== profile.images_enabled) {
      patch.images_enabled = imagesEnabled;
    }
    if (profile.image_model !== null && imageModel !== profile.image_model) {
      patch.image_model = imageModel;
    }
    if (profile.image_style !== null && imageStyle !== profile.image_style) {
      patch.image_style = imageStyle;
    }
    if (
      profile.image_style_prompt !== null &&
      imageStylePrompt !== profile.image_style_prompt
    ) {
      patch.image_style_prompt = imageStylePrompt;
    }
    if (automaticReviewEnabled !== profile.automatic_review_enabled) {
      patch.automatic_review_enabled = automaticReviewEnabled;
    }
    if (maxAutomaticRegenerations !== profile.max_automatic_regenerations) {
      patch.max_automatic_regenerations = maxAutomaticRegenerations;
    }
    if (
      profile.slide_palette !== null &&
      slidePalette !== null &&
      JSON.stringify(slidePalette) !== JSON.stringify(profile.slide_palette)
    ) {
      patch.slide_palette = slidePalette;
    }
    return patch;
  }

  const patch = buildPatch();
  const dirty = patch !== null && Object.keys(patch).length > 0;
  const contentChanged =
    patch !== null &&
    (patch.soul_md !== undefined ||
      patch.agents_md !== undefined ||
      patch.model !== undefined ||
      patch.orientation !== undefined ||
      patch.images_enabled !== undefined ||
      patch.image_model !== undefined ||
      patch.image_style !== undefined ||
      patch.image_style_prompt !== undefined ||
      patch.automatic_review_enabled !== undefined ||
      patch.max_automatic_regenerations !== undefined ||
      patch.slide_palette !== undefined);
  const paletteChanged = patch?.slide_palette !== undefined;
  const currentPaletteWarnings = slidePalette ? paletteWarnings(slidePalette) : [];

  async function save() {
    if (!patch || !dirty) return;
    if (imageStyle === "custom" && !imageStylePrompt.trim()) {
      setError("El estilo personalizado necesita un prompt.");
      return;
    }
    if (
      slidePalette &&
      Object.values(slidePalette).some((value) => !/^#[0-9A-Fa-f]{6}$/.test(value))
    ) {
      setError("Todos los colores deben usar HEX de seis dígitos, por ejemplo #F8F1E3.");
      return;
    }
    if (paletteChanged && currentPaletteWarnings.length > 0 && !paletteWarningsAccepted) {
      setError("Confirma las advertencias de contraste antes de guardar la paleta.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.updateProfile(id, { ...patch, note });
      setNote("");
      await load();
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  async function makeDefault() {
    await api.updateProfile(id, { is_default: true });
    await load();
  }

  async function remove() {
    setDeleting(true);
    await api.deleteProfile(id);
    router.push("/profiles");
  }

  if (!profile) {
    return <LoadingScreen label="Cargando perfil…" />;
  }
  const supportsOrientation =
    profile.agent_type === "slides" || profile.agent_type === "video";
  const isSlides = profile.agent_type === "slides";
  const isAutomaticVideo = profile.agent_type === "video";
  const selectedImageStyle = imageOptions?.styles.find(
    (option) => option.id === imageStyle,
  );

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Link
          href="/profiles"
          className="inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <IconChevronLeft size={15} />
          Agentes y perfiles
        </Link>
        <div className="flex items-center gap-2">
          {!profile.is_default && (
            <>
              <button onClick={makeDefault} className="btn-secondary btn-sm">
                <IconStar size={13} />
                Hacer por defecto
              </button>
              <button onClick={() => setConfirmDelete(true)} className="btn-danger btn-sm">
                Eliminar
              </button>
            </>
          )}
        </div>
      </div>

      <div className="mb-1 flex items-center gap-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="flex-1 rounded-lg border border-transparent bg-transparent text-2xl font-semibold tracking-tight text-zinc-50 outline-none focus:border-white/[0.15]"
        />
        <span className="badge-neutral shrink-0">v{profile.version}</span>
      </div>
      <p className="mb-6 text-sm text-zinc-500">
        Agente: <span className="text-zinc-400">{profile.agent_type}</span>
        {profile.is_default && (
          <span className="badge-info ml-2 align-middle">
            <IconStar size={10} />
            perfil por defecto
          </span>
        )}
      </p>

      <div className="space-y-5">
        <div className="card p-5">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <label className="label">Revisión automática</label>
              <p className="text-xs leading-relaxed text-zinc-500">
                Un evaluador revisa la salida de este agente. La política queda
                congelada con esta versión cuando empieza un run.
              </p>
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-zinc-200">
              <input
                type="checkbox"
                checked={automaticReviewEnabled}
                onChange={(event) =>
                  setAutomaticReviewEnabled(event.target.checked)
                }
              />
              {automaticReviewEnabled ? "Activada" : "Desactivada"}
            </label>
          </div>
          <div className="max-w-xs">
            <label className="label">Regeneraciones automáticas</label>
            <select
              value={maxAutomaticRegenerations}
              onChange={(event) =>
                setMaxAutomaticRegenerations(Number(event.target.value))
              }
              disabled={!automaticReviewEnabled}
              className="input"
            >
              {[0, 1, 2, 3, 4, 5].map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </div>
          <p className="mt-3 text-xs text-zinc-400">
            {automaticReviewEnabled
              ? maxAutomaticRegenerations === 0
                ? "Se evalúa una vez, pero no se regenera."
                : `Se evalúa el resultado y se permiten hasta ${maxAutomaticRegenerations} regeneraciones adicionales.`
              : "No se ejecutará el evaluador para este perfil."}
          </p>
        </div>
        {supportsOrientation && (
          <div className="card p-5">
            <label className="label">Orientación de salida</label>
            <p className="mb-3 text-xs text-zinc-500">
              La orientación se guarda con esta versión del perfil y se aplica a
              cada nueva generación.
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="card card-hover flex cursor-pointer items-center gap-3 px-4 py-3 text-sm">
                <input
                  type="radio"
                  name="orientation"
                  value="horizontal"
                  checked={orientation === "horizontal"}
                  onChange={() => setOrientation("horizontal")}
                />
                <span>
                  <span className="block font-semibold text-zinc-200">
                    Horizontal
                  </span>
                  <span className="text-xs text-zinc-500">16:9 · 1920×1080</span>
                </span>
              </label>
              <label className="card card-hover flex cursor-pointer items-center gap-3 px-4 py-3 text-sm">
                <input
                  type="radio"
                  name="orientation"
                  value="vertical"
                  checked={orientation === "vertical"}
                  onChange={() => setOrientation("vertical")}
                />
                <span>
                  <span className="block font-semibold text-zinc-200">Vertical</span>
                  <span className="text-xs text-zinc-500">9:16 · 1080×1920</span>
                </span>
              </label>
            </div>
          </div>
        )}
        {isSlides && paletteOptions && slidePalette && (
          <div className="card p-5">
            <div className="mb-4">
              <label className="label">Paleta de slides</label>
              <p className="text-xs leading-relaxed text-zinc-500">
                Se congela con la versión del perfil y se aplica programáticamente al
                Markdown Marp y a todos sus renders.
              </p>
            </div>
            <SlidePaletteEditor
              palette={slidePalette}
              options={paletteOptions}
              onChange={(value) => {
                setSlidePalette(value);
                setPaletteWarningsAccepted(false);
              }}
            />
            {paletteChanged && currentPaletteWarnings.length > 0 && (
              <label className="mt-3 flex cursor-pointer items-start gap-2 text-xs text-amber-100">
                <input
                  type="checkbox"
                  checked={paletteWarningsAccepted}
                  onChange={(event) => setPaletteWarningsAccepted(event.target.checked)}
                />
                Confirmo que quiero guardar la paleta pese a las advertencias de contraste.
              </label>
            )}
          </div>
        )}
        {isSlides && imageOptions && (
          <div className="card p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <label className="label">Imágenes generadas</label>
                <p className="text-xs leading-relaxed text-zinc-500">
                  El agente puede elegir hasta {imageOptions.max_images_per_deck} slides
                  por lección. Nunca generará más de una imagen por slide.
                </p>
              </div>
              <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-zinc-200">
                <input
                  type="checkbox"
                  checked={imagesEnabled}
                  onChange={(event) => setImagesEnabled(event.target.checked)}
                />
                {imagesEnabled ? "Activadas" : "Desactivadas"}
              </label>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="label">Modelo de imágenes</label>
                <select
                  value={imageModel}
                  onChange={(event) => setImageModel(event.target.value)}
                  className="input"
                >
                  {imageOptions.models.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label} · {option.price_hint}
                    </option>
                  ))}
                </select>
                <p className="mt-1.5 break-all font-mono text-[11px] text-zinc-500">
                  {imageModel}
                </p>
              </div>
              <div>
                <label className="label">Estilo visual consistente</label>
                <select
                  value={imageStyle}
                  onChange={(event) => setImageStyle(event.target.value)}
                  className="input"
                >
                  {imageOptions.styles.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {imageStyle === "custom" ? (
              <div className="mt-4">
                <label className="label">Prompt de estilo personalizado</label>
                <textarea
                  value={imageStylePrompt}
                  onChange={(event) => setImageStylePrompt(event.target.value)}
                  rows={5}
                  placeholder="Describe paleta, técnica, iluminación, materiales y composición…"
                  className="input resize-y text-sm"
                />
                <p className="mt-1.5 text-xs text-zinc-500">
                  Este prompt reemplaza completamente los estilos predefinidos.
                </p>
              </div>
            ) : (
              <div className="mt-4 rounded-lg border border-white/[0.08] bg-black/20 p-3">
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
                  Prompt del preset
                </p>
                <p className="text-xs leading-relaxed text-zinc-400">
                  {selectedImageStyle?.prompt}
                </p>
              </div>
            )}
            <p className="mt-3 text-xs text-amber-300/80">
              Las imágenes usan créditos de OpenRouter. Los fallos se reintentan dos
              veces y no bloquean la generación del deck.
            </p>
          </div>
        )}
        {!isAutomaticVideo && (
          <>
        <div className="card p-5">
          <label className="label">soul.md — personalidad y criterio</label>
          <p className="mb-2 text-xs text-zinc-500">
            Cómo piensa y qué prioriza el agente: tono, gustos, criterio
            editorial.
          </p>
          <textarea
            value={soul}
            onChange={(e) => setSoul(e.target.value)}
            rows={8}
            className="input resize-y font-mono text-[13px]"
          />
        </div>
        <div className="card p-5">
          <label className="label">agents.md — instrucciones operativas</label>
          <p className="mb-2 text-xs text-zinc-500">
            Reglas concretas de trabajo: formato, longitudes, restricciones,
            checklist.
          </p>
          <textarea
            value={agentsMd}
            onChange={(e) => setAgentsMd(e.target.value)}
            rows={8}
            className="input resize-y font-mono text-[13px]"
          />
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label className="label">Modelo (slug de OpenRouter)</label>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="vacío = modelo por defecto del sistema"
              className="input font-mono text-[13px]"
            />
            <p className="mt-1.5 text-xs text-zinc-500">
              Deja el campo vacío para volver al modelo por defecto.
            </p>
          </div>
          <div>
            <label className="label">Nota de esta versión</label>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="qué has cambiado y por qué"
              className="input"
            />
          </div>
        </div>
          </>
        )}
        {isAutomaticVideo && (
          <div>
            <label className="label">Nota de esta versión</label>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="qué has cambiado y por qué"
              className="input"
            />
          </div>
        )}
        <ErrorBanner>{error}</ErrorBanner>
        <div className="flex items-center gap-3">
          <button onClick={save} disabled={saving || !dirty} className="btn-primary">
            {saving
              ? "Guardando…"
              : contentChanged
                ? "Guardar (crea nueva versión)"
                : "Guardar"}
          </button>
          {dirty && !saving && (
            <span className="badge-warning">Cambios sin guardar</span>
          )}
          {saved && <span className="badge-success">Guardado ✓</span>}
        </div>
      </div>

      <section className="mt-12">
        <h2 className="mb-3 text-base font-semibold tracking-tight text-zinc-100">
          Historial de versiones
        </h2>
        <ul className="space-y-1.5">
          {versions.map((v) => (
            <li key={v.version} className="card px-4 py-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2 font-semibold text-zinc-200">
                  v{v.version}
                  {v.orientation && (
                    <span className="badge-neutral font-normal">
                      {v.orientation === "vertical"
                        ? "Vertical 9:16"
                        : "Horizontal 16:9"}
                    </span>
                  )}
                  {v.images_enabled !== null && (
                    <span
                      className={v.images_enabled ? "badge-info font-normal" : "badge-neutral font-normal"}
                    >
                      {v.images_enabled ? "Con imágenes" : "Sin imágenes"}
                    </span>
                  )}
                  <span
                    className={
                      v.automatic_review_enabled
                        ? "badge-info font-normal"
                        : "badge-neutral font-normal"
                    }
                  >
                    {v.automatic_review_enabled
                      ? `Revisión · ${v.max_automatic_regenerations} regeneraciones`
                      : "Sin revisión automática"}
                  </span>
                  {v.slide_palette && (
                    <span className="badge-neutral font-normal">
                      <span
                        className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full border border-white/20"
                        style={{ background: v.slide_palette.primary }}
                      />
                      Paleta guardada
                    </span>
                  )}
                </span>
                <span className="text-xs text-zinc-500">
                  {new Date(v.created_at).toLocaleString("es")}
                </span>
              </div>
              {v.note && (
                <p className="mt-1 text-sm leading-relaxed text-zinc-400">
                  {v.note}
                </p>
              )}
            </li>
          ))}
        </ul>
      </section>
      <ConfirmDialog
        open={confirmDelete}
        title="Eliminar perfil"
        description={`Se eliminará el perfil «${profile.name}» y su historial de versiones.`}
        busy={deleting}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={remove}
      />
    </div>
  );
}
