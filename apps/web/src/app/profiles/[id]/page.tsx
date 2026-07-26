"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  api,
  type AgentProfile,
  type ImageOptions,
  type LogoVisibility,
  type PaletteOptions,
  type ProfileVersion,
  type SlidePalette,
  type TTSOptions,
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
  const [humanReviewEnabled, setHumanReviewEnabled] = useState(false);
  const [ttsOptions, setTTSOptions] = useState<TTSOptions | null>(null);
  const [ttsProvider, setTTSProvider] = useState<"openai" | "openrouter">("openai");
  const [ttsModel, setTTSModel] = useState("");
  const [ttsLanguage, setTTSLanguage] = useState("inherit");
  const [ttsVoice, setTTSVoice] = useState("");
  const [ttsSample, setTTSSample] = useState(
    "Hola. Esta es una muestra de la voz seleccionada para tu curso.",
  );
  const [ttsPreviewUrl, setTTSPreviewUrl] = useState<string | null>(null);
  const [ttsPreviewBusy, setTTSPreviewBusy] = useState(false);
  const [subtitlesMode, setSubtitlesMode] = useState<
    "none" | "srt" | "burned_and_srt"
  >("none");
  const [paletteOptions, setPaletteOptions] = useState<PaletteOptions | null>(null);
  const [slidePalette, setSlidePalette] = useState<SlidePalette | null>(null);
  const [paletteWarningsAccepted, setPaletteWarningsAccepted] = useState(false);
  const [logoMode, setLogoMode] = useState<"none" | "uploaded" | "generated">("none");
  const [activeLogoId, setActiveLogoId] = useState<string | null>(null);
  const [logoPlacement, setLogoPlacement] = useState<
    "top-left" | "top-right" | "bottom-left" | "bottom-right"
  >("top-right");
  const [logoSize, setLogoSize] = useState<"small" | "medium" | "large">("small");
  const [logoMarginPx, setLogoMarginPx] = useState(32);
  const [logoOpacity, setLogoOpacity] = useState(1);
  const [logoVisibility, setLogoVisibility] = useState<LogoVisibility>({
    cover: true,
    content: true,
    summary: true,
  });
  const [logoName, setLogoName] = useState("");
  const [logoPrompt, setLogoPrompt] = useState("");
  const [logoModel, setLogoModel] = useState("");
  const [logoBusy, setLogoBusy] = useState(false);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function load() {
    const [p, options, palettes, voiceOptions] = await Promise.all([
      api.getProfile(id),
      api.getImageOptions(),
      api.getPaletteOptions(),
      api.getTTSOptions(),
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
    setHumanReviewEnabled(p.human_review_enabled);
    setTTSOptions(voiceOptions);
    setTTSProvider(p.tts_provider ?? voiceOptions.default.tts_provider);
    setTTSModel(p.tts_model ?? voiceOptions.default.tts_model);
    setTTSLanguage(p.tts_language ?? voiceOptions.default.tts_language);
    setTTSVoice(p.tts_voice ?? voiceOptions.default.tts_voice);
    setSubtitlesMode(p.subtitles_mode ?? "none");
    setPaletteOptions(palettes);
    setSlidePalette(p.slide_palette ?? palettes.default);
    setLogoMode(p.logo_mode ?? "none");
    setActiveLogoId(p.active_logo_id);
    setLogoPlacement(p.logo_placement ?? "top-right");
    setLogoSize(p.logo_size ?? "small");
    setLogoMarginPx(p.logo_margin_px ?? 32);
    setLogoOpacity(p.logo_opacity ?? 1);
    setLogoVisibility(
      p.logo_visibility ?? { cover: true, content: true, summary: true },
    );
    setLogoModel((current) => current || p.image_model || options.default_model);
    setPaletteWarningsAccepted(false);
    setVersions(await api.getProfileVersions(id));
  }

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(
    () => () => {
      if (ttsPreviewUrl) URL.revokeObjectURL(ttsPreviewUrl);
    },
    [ttsPreviewUrl],
  );

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
      human_review_enabled?: boolean;
      tts_provider?: "openai" | "openrouter";
      tts_model?: string;
      tts_language?: string;
      tts_voice?: string;
      subtitles_mode?: "none" | "srt" | "burned_and_srt";
      slide_palette?: SlidePalette;
      logo_mode?: "none" | "uploaded" | "generated";
      active_logo_id?: string | null;
      logo_placement?: "top-left" | "top-right" | "bottom-left" | "bottom-right";
      logo_size?: "small" | "medium" | "large";
      logo_margin_px?: number;
      logo_opacity?: number;
      logo_visibility?: LogoVisibility;
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
    if (humanReviewEnabled !== profile.human_review_enabled) {
      patch.human_review_enabled = humanReviewEnabled;
    }
    if (profile.tts_provider !== null && ttsProvider !== profile.tts_provider) {
      patch.tts_provider = ttsProvider;
    }
    if (profile.tts_model !== null && ttsModel !== profile.tts_model) {
      patch.tts_model = ttsModel;
    }
    if (profile.tts_language !== null && ttsLanguage !== profile.tts_language) {
      patch.tts_language = ttsLanguage;
    }
    if (profile.tts_voice !== null && ttsVoice !== profile.tts_voice) {
      patch.tts_voice = ttsVoice;
    }
    if (
      profile.subtitles_mode !== null &&
      subtitlesMode !== profile.subtitles_mode
    ) {
      patch.subtitles_mode = subtitlesMode;
    }
    if (
      profile.slide_palette !== null &&
      slidePalette !== null &&
      JSON.stringify(slidePalette) !== JSON.stringify(profile.slide_palette)
    ) {
      patch.slide_palette = slidePalette;
    }
    if (profile.logo_mode !== null && logoMode !== profile.logo_mode) {
      patch.logo_mode = logoMode;
    }
    if (profile.logo_mode !== null && activeLogoId !== profile.active_logo_id) {
      patch.active_logo_id = activeLogoId;
    }
    if (profile.logo_placement !== null && logoPlacement !== profile.logo_placement) {
      patch.logo_placement = logoPlacement;
    }
    if (profile.logo_size !== null && logoSize !== profile.logo_size) {
      patch.logo_size = logoSize;
    }
    if (profile.logo_margin_px !== null && logoMarginPx !== profile.logo_margin_px) {
      patch.logo_margin_px = logoMarginPx;
    }
    if (profile.logo_opacity !== null && logoOpacity !== profile.logo_opacity) {
      patch.logo_opacity = logoOpacity;
    }
    if (
      profile.logo_visibility !== null &&
      JSON.stringify(logoVisibility) !== JSON.stringify(profile.logo_visibility)
    ) {
      patch.logo_visibility = logoVisibility;
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
      patch.human_review_enabled !== undefined ||
      patch.tts_provider !== undefined ||
      patch.tts_model !== undefined ||
      patch.tts_language !== undefined ||
      patch.tts_voice !== undefined ||
      patch.subtitles_mode !== undefined ||
      patch.slide_palette !== undefined ||
      patch.logo_mode !== undefined ||
      patch.active_logo_id !== undefined ||
      patch.logo_placement !== undefined ||
      patch.logo_size !== undefined ||
      patch.logo_margin_px !== undefined ||
      patch.logo_opacity !== undefined ||
      patch.logo_visibility !== undefined);
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
    if (logoMode !== "none" && !activeLogoId) {
      setError("Selecciona un logo activo o desactiva el logo.");
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

  async function uploadLogo(file: File) {
    setLogoBusy(true);
    setError(null);
    try {
      await api.uploadProfileLogo(id, file, logoName);
      setLogoName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo subir el logo");
    } finally {
      setLogoBusy(false);
    }
  }

  async function generateLogo() {
    if (!logoPrompt.trim()) {
      setError("Describe el logo que quieres generar.");
      return;
    }
    setLogoBusy(true);
    setError(null);
    try {
      await api.generateProfileLogo(id, logoPrompt.trim(), logoModel, logoName);
      setLogoPrompt("");
      setLogoName("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo generar el logo");
    } finally {
      setLogoBusy(false);
    }
  }

  async function deleteLogo(logoId: string) {
    setLogoBusy(true);
    setError(null);
    try {
      await api.deleteProfileLogo(id, logoId);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo eliminar el logo");
    } finally {
      setLogoBusy(false);
    }
  }

  async function previewVoice() {
    if (!ttsSample.trim()) {
      setError("Escribe un texto breve para escuchar la muestra.");
      return;
    }
    setTTSPreviewBusy(true);
    setError(null);
    try {
      const blob = await api.previewProfileTTS(id, {
        text: ttsSample.trim(),
        tts_provider: ttsProvider,
        tts_model: ttsModel,
        tts_language: ttsLanguage,
        tts_voice: ttsVoice,
      });
      const nextUrl = URL.createObjectURL(blob);
      setTTSPreviewUrl(nextUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo generar la muestra");
    } finally {
      setTTSPreviewBusy(false);
    }
  }

  if (!profile) {
    return <LoadingScreen label="Cargando perfil…" />;
  }
  const supportsOrientation =
    profile.agent_type === "slides" || profile.agent_type === "video";
  const isSlides = profile.agent_type === "slides";
  const isVoice = profile.agent_type === "voice";
  const isAutomaticVideo = profile.agent_type === "video";
  const selectedTTSModel = ttsOptions?.models.find(
    (option) => option.provider === ttsProvider && option.model === ttsModel,
  );
  const availableTTSVoices = selectedTTSModel
    ? selectedTTSModel.voices_by_language["*"] ??
      (ttsLanguage === "inherit"
        ? Array.from(
            new Set(Object.values(selectedTTSModel.voices_by_language).flat()),
          )
        : selectedTTSModel.voices_by_language[ttsLanguage] ?? [])
    : [];
  const selectedImageStyle = imageOptions?.styles.find(
    (option) => option.id === imageStyle,
  );
  const selectedLogo = profile.logo_candidates?.find(
    (candidate) => candidate.id === activeLogoId,
  );
  const logoPositionStyle = {
    [logoPlacement.startsWith("top") ? "top" : "bottom"]: `${Math.max(4, logoMarginPx / 4)}px`,
    [logoPlacement.endsWith("left") ? "left" : "right"]: `${Math.max(4, logoMarginPx / 4)}px`,
    width: logoSize === "small" ? "12%" : logoSize === "medium" ? "18%" : "24%",
    opacity: logoOpacity,
  };

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
          <div className="flex items-start justify-between gap-4">
            <div>
              <label className="label">Aprobación humana</label>
              <p className="text-xs leading-relaxed text-zinc-500">
                Detiene el workflow después de esta fase. Puedes aprobarla o
                enviar feedback para regenerar y volver a revisar. Si todos los
                perfiles la desactivan, la producción continúa autónomamente hasta vídeo.
              </p>
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-zinc-200">
              <input
                type="checkbox"
                checked={humanReviewEnabled}
                onChange={(event) => setHumanReviewEnabled(event.target.checked)}
              />
              {humanReviewEnabled ? "Activada" : "Desactivada"}
            </label>
          </div>
          <p className="mt-3 text-xs text-zinc-400">
            {humanReviewEnabled
              ? "El run congela esta decisión con la versión del perfil."
              : "Esta fase continuará automáticamente al terminar su revisión automática."}
          </p>
        </div>
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
        {isVoice && ttsOptions && (
          <div className="card p-5">
            <div className="mb-4">
              <label className="label">Síntesis de voz (TTS)</label>
              <p className="text-xs leading-relaxed text-zinc-500">
                Proveedor, modelo, idioma y voz quedan congelados en cada
                <code className="mx-1 text-zinc-300">voice_script</code>. El montaje
                usa ese snapshot aunque edites después el perfil.
              </p>
            </div>
            {profile.tts_available === false && (
              <div className="mb-4 rounded-lg border border-amber-400/30 bg-amber-400/10 px-3 py-2 text-xs text-amber-100">
                Esta versión usa una combinación histórica no disponible. Elige una
                opción actual antes de iniciar un nuevo run.
              </div>
            )}
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label className="label">Proveedor y modelo</label>
                <select
                  value={`${ttsProvider}::${ttsModel}`}
                  onChange={(event) => {
                    const option = ttsOptions.models.find(
                      (item) =>
                        `${item.provider}::${item.model}` === event.target.value,
                    );
                    if (!option) return;
                    setTTSProvider(option.provider);
                    setTTSModel(option.model);
                    setTTSLanguage("inherit");
                    setTTSVoice(option.default_voice);
                  }}
                  className="input"
                >
                  {!selectedTTSModel && (
                    <option value={`${ttsProvider}::${ttsModel}`}>
                      Configuración histórica — no disponible
                    </option>
                  )}
                  {ttsOptions.models.map((option) => (
                    <option
                      key={`${option.provider}:${option.model}`}
                      value={`${option.provider}::${option.model}`}
                    >
                      {option.provider_label} · {option.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Idioma</label>
                <select
                  value={ttsLanguage}
                  onChange={(event) => {
                    const language = event.target.value;
                    setTTSLanguage(language);
                    if (!selectedTTSModel) return;
                    const voices =
                      selectedTTSModel.voices_by_language["*"] ??
                      (language === "inherit"
                        ? Array.from(
                            new Set(
                              Object.values(
                                selectedTTSModel.voices_by_language,
                              ).flat(),
                            ),
                          )
                        : selectedTTSModel.voices_by_language[language] ?? []);
                    if (!voices.includes(ttsVoice)) {
                      setTTSVoice(
                        voices.includes(selectedTTSModel.default_voice)
                          ? selectedTTSModel.default_voice
                          : (voices[0] ?? ""),
                      );
                    }
                  }}
                  className="input"
                >
                  {(selectedTTSModel?.languages ?? [ttsLanguage]).map((language) => (
                    <option key={language} value={language}>
                      {language === "inherit"
                        ? "Heredar idioma del proyecto"
                        : language}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="label">Voz validada</label>
                <select
                  value={ttsVoice}
                  onChange={(event) => setTTSVoice(event.target.value)}
                  className="input font-mono text-[13px]"
                >
                  {!availableTTSVoices.includes(ttsVoice) && ttsVoice && (
                    <option value={ttsVoice}>{ttsVoice} · histórica</option>
                  )}
                  {availableTTSVoices.map((voice) => (
                    <option key={voice} value={voice}>
                      {voice}
                    </option>
                  ))}
                </select>
              </div>
              <div className="rounded-lg border border-white/[0.08] bg-white/[0.02] px-3 py-2">
                <p className="text-xs font-medium text-zinc-300">Coste y capacidad</p>
                <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                  {selectedTTSModel?.price_hint ?? "Configuración histórica."}
                </p>
              </div>
            </div>
            <div className="mt-4">
              <label className="label">Muestra de voz · máximo 300 caracteres</label>
              <textarea
                value={ttsSample}
                maxLength={300}
                rows={3}
                onChange={(event) => setTTSSample(event.target.value)}
                className="input resize-y"
              />
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <button
                  type="button"
                  onClick={previewVoice}
                  disabled={ttsPreviewBusy || !ttsVoice}
                  className="btn-secondary btn-sm"
                >
                  {ttsPreviewBusy ? "Generando muestra…" : "Escuchar muestra"}
                </button>
                <span className="text-xs text-zinc-500">
                  {ttsSample.length}/300 · la muestra registra uso, pero no crea
                  artefactos ni versiones.
                </span>
              </div>
              {ttsPreviewUrl && (
                <audio
                  controls
                  autoPlay
                  src={ttsPreviewUrl}
                  className="mt-3 w-full"
                />
              )}
            </div>
          </div>
        )}
        {isAutomaticVideo && (
          <div className="card p-5">
            <label className="label">Subtítulos del vídeo</label>
            <p className="mb-3 text-xs leading-relaxed text-zinc-500">
              Se generan a partir de las duraciones TTS reales, sin llamadas LLM
              adicionales. El valor predeterminado es no crear subtítulos.
            </p>
            <div className="grid gap-2">
              {[
                {
                  value: "none" as const,
                  title: "Sin subtítulos",
                  detail: "No crea SRT ni incrusta texto en el MP4.",
                },
                {
                  value: "srt" as const,
                  title: "SRT descargable",
                  detail: "Crea el artefacto SRT, pero deja limpio el vídeo.",
                },
                {
                  value: "burned_and_srt" as const,
                  title: "Incrustados + SRT",
                  detail:
                    "Quema texto legible con safe areas y conserva el SRT descargable.",
                },
              ].map((option) => (
                <label
                  key={option.value}
                  className="card card-hover flex cursor-pointer items-start gap-3 px-4 py-3"
                >
                  <input
                    type="radio"
                    name="subtitles-mode"
                    value={option.value}
                    checked={subtitlesMode === option.value}
                    onChange={() => setSubtitlesMode(option.value)}
                  />
                  <span>
                    <span className="block text-sm font-semibold text-zinc-200">
                      {option.title}
                    </span>
                    <span className="text-xs text-zinc-500">{option.detail}</span>
                  </span>
                </label>
              ))}
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
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div>
                <label className="label">Logo de marca</label>
                <p className="text-xs leading-relaxed text-zinc-500">
                  La biblioteca pertenece al perfil. El logo activo se copia a cada
                  versión del deck; cambiarlo no altera artefactos anteriores.
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setLogoMode("none");
                  setActiveLogoId(null);
                }}
                className={logoMode === "none" ? "btn-primary btn-sm" : "btn-secondary btn-sm"}
              >
                Sin logo
              </button>
            </div>

            {(profile.logo_candidates?.length ?? 0) > 0 ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {profile.logo_candidates?.map((candidate) => {
                  const active = candidate.id === activeLogoId && logoMode !== "none";
                  return (
                    <div
                      key={candidate.id}
                      className={`rounded-lg border p-3 ${
                        active
                          ? "border-amber-400/60 bg-amber-400/[0.06]"
                          : "border-white/[0.08] bg-black/20"
                      }`}
                    >
                      <button
                        type="button"
                        onClick={() => {
                          setActiveLogoId(candidate.id);
                          setLogoMode(candidate.source);
                        }}
                        className="flex w-full items-center gap-3 text-left"
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={api.profileLogoUrl(id, candidate.id, true)}
                          alt={candidate.name}
                          className="h-16 w-20 rounded bg-white/95 object-contain p-1"
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-semibold text-zinc-200">
                            {candidate.name}
                          </span>
                          <span className="block text-[11px] text-zinc-500">
                            {candidate.source === "generated" ? "Generado" : "Subido"}
                            {candidate.model ? ` · ${candidate.model}` : ""}
                          </span>
                          <span className="block text-[11px] text-zinc-600">
                            {candidate.width}×{candidate.height}
                            {candidate.cost_usd != null
                              ? ` · $${candidate.cost_usd.toFixed(4)}`
                              : ""}
                          </span>
                        </span>
                      </button>
                      <div className="mt-2 flex items-center justify-between">
                        <span className={active ? "badge-info" : "badge-neutral"}>
                          {active ? "Activo" : "Candidato"}
                        </span>
                        <button
                          type="button"
                          disabled={logoBusy}
                          onClick={() => deleteLogo(candidate.id)}
                          className="text-xs text-red-300 hover:text-red-200 disabled:opacity-40"
                        >
                          Eliminar
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="rounded-lg border border-dashed border-white/10 p-4 text-center text-xs text-zinc-500">
                Aún no hay logos en este perfil.
              </p>
            )}

            <div className="mt-4 grid gap-4 border-t border-white/[0.08] pt-4 sm:grid-cols-2">
              <div>
                <label className="label">Subir logo</label>
                <input
                  value={logoName}
                  onChange={(event) => setLogoName(event.target.value)}
                  placeholder="Nombre opcional"
                  className="input mb-2"
                />
                <input
                  type="file"
                  accept=".png,.webp,.svg,.jpg,.jpeg,image/png,image/webp,image/svg+xml,image/jpeg"
                  disabled={logoBusy}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (file) void uploadLogo(file);
                    event.target.value = "";
                  }}
                  className="block w-full text-xs text-zinc-400 file:mr-3 file:rounded-md file:border-0 file:bg-white/10 file:px-3 file:py-2 file:text-zinc-200"
                />
                <p className="mt-1.5 text-[11px] text-zinc-500">
                  PNG, WebP, SVG, JPG o JPEG · máximo 5 MB.
                </p>
              </div>
              <div>
                <label className="label">Generar candidato</label>
                <select
                  value={logoModel}
                  onChange={(event) => setLogoModel(event.target.value)}
                  className="input mb-2"
                >
                  {imageOptions.models.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label} · {option.price_hint}
                    </option>
                  ))}
                </select>
                <textarea
                  value={logoPrompt}
                  onChange={(event) => setLogoPrompt(event.target.value)}
                  rows={3}
                  placeholder="Símbolo, personalidad, formas y colores…"
                  className="input resize-y text-sm"
                />
                <button
                  type="button"
                  onClick={generateLogo}
                  disabled={logoBusy || !logoPrompt.trim()}
                  className="btn-secondary btn-sm mt-2"
                >
                  {logoBusy ? "Procesando…" : "Generar logo"}
                </button>
              </div>
            </div>

            <div className="mt-5 grid gap-4 border-t border-white/[0.08] pt-4 sm:grid-cols-2">
              <div>
                <label className="label">Posición</label>
                <select
                  value={logoPlacement}
                  onChange={(event) =>
                    setLogoPlacement(
                      event.target.value as
                        | "top-left"
                        | "top-right"
                        | "bottom-left"
                        | "bottom-right",
                    )
                  }
                  disabled={logoMode === "none"}
                  className="input"
                >
                  <option value="top-left">Arriba izquierda</option>
                  <option value="top-right">Arriba derecha</option>
                  <option value="bottom-left">Abajo izquierda</option>
                  <option value="bottom-right">Abajo derecha</option>
                </select>
              </div>
              <div>
                <label className="label">Tamaño</label>
                <select
                  value={logoSize}
                  onChange={(event) =>
                    setLogoSize(event.target.value as "small" | "medium" | "large")
                  }
                  disabled={logoMode === "none"}
                  className="input"
                >
                  <option value="small">Pequeño</option>
                  <option value="medium">Mediano</option>
                  <option value="large">Grande</option>
                </select>
              </div>
              <div>
                <label className="label">Margen: {logoMarginPx}px</label>
                <input
                  type="range"
                  min={0}
                  max={128}
                  value={logoMarginPx}
                  onChange={(event) => setLogoMarginPx(Number(event.target.value))}
                  disabled={logoMode === "none"}
                  className="w-full"
                />
                <p className="mt-1 text-[11px] text-zinc-500">
                  El render conserva un margen seguro mínimo para paginación y subtítulos.
                </p>
              </div>
              <div>
                <label className="label">Opacidad: {Math.round(logoOpacity * 100)}%</label>
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.05}
                  value={logoOpacity}
                  onChange={(event) => setLogoOpacity(Number(event.target.value))}
                  disabled={logoMode === "none"}
                  className="w-full"
                />
              </div>
            </div>

            <div className="mt-4 flex flex-wrap gap-4 text-xs text-zinc-300">
              {(["cover", "content", "summary"] as const).map((kind) => (
                <label key={kind} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={logoVisibility[kind]}
                    disabled={logoMode === "none"}
                    onChange={(event) =>
                      setLogoVisibility((current) => ({
                        ...current,
                        [kind]: event.target.checked,
                      }))
                    }
                  />
                  {kind === "cover"
                    ? "Portada"
                    : kind === "content"
                      ? "Contenido"
                      : "Resumen"}
                </label>
              ))}
            </div>

            {selectedLogo && logoMode !== "none" && (
              <div className="mt-5 grid items-start gap-4 sm:grid-cols-2">
                {[
                  { label: "Vista 16:9", className: "aspect-video" },
                  { label: "Vista 9:16", className: "mx-auto aspect-[9/16] w-2/3" },
                ].map((preview) => (
                  <div key={preview.label}>
                    <p className="mb-1 text-[11px] text-zinc-500">{preview.label}</p>
                    <div
                      className={`relative overflow-hidden rounded-lg border border-white/10 bg-[#f8f1e3] p-4 ${preview.className}`}
                    >
                      <p className="max-w-[70%] text-sm font-semibold text-[#1f2937]">
                        Título de ejemplo
                      </p>
                      <p className="mt-2 max-w-[68%] text-[10px] text-[#4b5563]">
                        El logo usa la misma configuración programática del deck.
                      </p>
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={api.profileLogoUrl(id, selectedLogo.id)}
                        alt={selectedLogo.name}
                        className="absolute max-h-[28%] object-contain"
                        style={logoPositionStyle}
                      />
                    </div>
                  </div>
                ))}
              </div>
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
                  {v.tts_provider && v.tts_model && v.tts_voice && (
                    <span
                      className={
                        v.tts_available === false
                          ? "badge-warning font-normal"
                          : "badge-info font-normal"
                      }
                    >
                      {v.tts_provider} · {v.tts_model} · {v.tts_voice}
                    </span>
                  )}
                  {v.subtitles_mode && (
                    <span className="badge-neutral font-normal">
                      {v.subtitles_mode === "none"
                        ? "Sin subtítulos"
                        : v.subtitles_mode === "srt"
                          ? "SRT"
                          : "Subtítulos incrustados + SRT"}
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
                  <span
                    className={
                      v.human_review_enabled
                        ? "badge-warning font-normal"
                        : "badge-neutral font-normal"
                    }
                  >
                    {v.human_review_enabled
                      ? "Aprobación humana"
                      : "Sin aprobación humana"}
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
                  {v.logo_mode && v.logo_mode !== "none" && v.active_logo_id && (
                    <span className="badge-info font-normal">
                      Logo {v.logo_mode === "generated" ? "generado" : "subido"}
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
