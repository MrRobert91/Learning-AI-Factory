"use client";

import { useState } from "react";
import type {
  DurationPreset,
  DurationSpec,
  ProjectInput,
} from "@/lib/api";
import { ErrorBanner, Spinner } from "@/components/ui";

const LEVELS = [
  { value: "introductorio", label: "Introductorio" },
  { value: "intermedio", label: "Intermedio" },
  { value: "avanzado", label: "Avanzado" },
];
const FORMATS = [
  { value: "video", label: "Vídeo completo" },
  { value: "slides", label: "Solo diapositivas" },
  { value: "script", label: "Guion docente" },
];
const DURATION_PRESETS: {
  value: Exclude<DurationPreset, "custom">;
  label: string;
  modules: number;
  videos: number;
  minutes: number;
}[] = [
  { value: "microvideo", label: "Microvídeo", modules: 1, videos: 1, minutes: 1 },
  { value: "minicourse", label: "Minicurso", modules: 1, videos: 3, minutes: 5 },
  { value: "short", label: "Curso breve", modules: 2, videos: 3, minutes: 8 },
  { value: "standard", label: "Curso estándar", modules: 3, videos: 4, minutes: 10 },
  { value: "complete", label: "Curso completo", modules: 5, videos: 4, minutes: 15 },
];

function durationSpec(
  preset: DurationPreset,
  modules = 3,
  videos = 4,
  minutes = 10,
): DurationSpec {
  const selected = DURATION_PRESETS.find((item) => item.value === preset);
  const moduleCount = selected?.modules ?? modules;
  const videosPerModule = selected?.videos ?? videos;
  const minutesPerVideo = selected?.minutes ?? minutes;
  return {
    preset,
    module_count: moduleCount,
    videos_per_module: videosPerModule,
    target_minutes_per_video: minutesPerVideo,
    total_videos: moduleCount * videosPerModule,
    total_minutes: moduleCount * videosPerModule * minutesPerVideo,
    tolerance_ratio: 0.2,
  };
}

interface Props {
  initial?: Partial<ProjectInput>;
  submitLabel: string;
  onSubmit: (input: ProjectInput) => Promise<void>;
}

export default function ProjectForm({ initial, submitLabel, onSubmit }: Props) {
  const [form, setForm] = useState<ProjectInput>({
    title: initial?.title ?? "",
    topic: initial?.topic ?? "",
    audience: initial?.audience ?? "",
    level: initial?.level ?? "introductorio",
    language: initial?.language ?? "es",
    style: initial?.style ?? "",
    output_format: initial?.output_format ?? "video",
    duration_spec: initial?.duration_spec ?? durationSpec("standard"),
    research_mode: initial?.research_mode ?? "web_only",
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function set<K extends keyof ProjectInput>(key: K, value: ProjectInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  function setDuration(next: DurationSpec) {
    set("duration_spec", durationSpec(
      next.preset,
      next.module_count,
      next.videos_per_module,
      next.target_minutes_per_video,
    ));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSaving(true);
    try {
      await onSubmit(form);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label className="label">Título *</label>
        <input
          value={form.title}
          onChange={(e) => set("title", e.target.value)}
          required
          placeholder="Introducción a los LLMs"
          className="input"
        />
      </div>
      <div>
        <label className="label">Tema</label>
        <textarea
          value={form.topic}
          onChange={(e) => set("topic", e.target.value)}
          rows={2}
          placeholder="Qué quieres enseñar y con qué enfoque"
          className="input resize-y"
        />
      </div>
      <div className="grid gap-5 sm:grid-cols-2">
        <div>
          <label className="label">Audiencia</label>
          <input
            value={form.audience}
            onChange={(e) => set("audience", e.target.value)}
            placeholder="Perfiles técnicos sin ML"
            className="input"
          />
        </div>
        <div>
          <label className="label">Nivel</label>
          <select
            value={form.level}
            onChange={(e) => set("level", e.target.value)}
            className="input"
          >
            {LEVELS.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="label">Idioma</label>
          <select
            value={form.language}
            onChange={(e) => set("language", e.target.value)}
            className="input"
          >
            <option value="es">Español</option>
            <option value="en">Inglés</option>
          </select>
        </div>
        <div>
          <label className="label">Formato de salida</label>
          <select
            value={form.output_format}
            onChange={(e) => set("output_format", e.target.value)}
            className="input"
          >
            {FORMATS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div>
        <label className="label">Estilo</label>
        <input
          value={form.style}
          onChange={(e) => set("style", e.target.value)}
          placeholder="Práctico, con ejemplos de código"
          className="input"
        />
      </div>
      {form.duration_spec && (
        <fieldset className="rounded-xl border border-white/[0.08] p-4">
          <legend className="px-1 text-sm font-semibold text-zinc-200">
            Duración y estructura
          </legend>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            {[...DURATION_PRESETS, {
              value: "custom" as const,
              label: "Personalizado",
              modules: 3,
              videos: 4,
              minutes: 10,
            }].map((preset) => {
              const active = form.duration_spec?.preset === preset.value;
              return (
                <button
                  key={preset.value}
                  type="button"
                  onClick={() =>
                    setDuration(
                      durationSpec(
                        preset.value,
                        preset.modules,
                        preset.videos,
                        preset.minutes,
                      ),
                    )
                  }
                  className={`rounded-lg border p-3 text-left transition-colors ${
                    active
                      ? "border-indigo-400/60 bg-indigo-500/10 text-indigo-200"
                      : "border-white/[0.07] bg-white/[0.02] text-zinc-400 hover:border-white/15"
                  }`}
                >
                  <span className="block text-sm font-medium">{preset.label}</span>
                  <span className="mt-1 block text-xs">
                    {preset.modules} módulos · {preset.videos} vídeos/módulo ·{" "}
                    {preset.minutes} min
                  </span>
                </button>
              );
            })}
          </div>
          {form.duration_spec.preset === "custom" && (
            <div className="mt-4 grid gap-4 sm:grid-cols-3">
              <label className="text-xs text-zinc-400">
                Módulos (1–5)
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={form.duration_spec.module_count}
                  onChange={(event) =>
                    setDuration({
                      ...form.duration_spec!,
                      module_count: Number(event.target.value),
                    })
                  }
                  className="input mt-1"
                />
              </label>
              <label className="text-xs text-zinc-400">
                Vídeos por módulo (1–5)
                <input
                  type="number"
                  min={1}
                  max={5}
                  value={form.duration_spec.videos_per_module}
                  onChange={(event) =>
                    setDuration({
                      ...form.duration_spec!,
                      videos_per_module: Number(event.target.value),
                    })
                  }
                  className="input mt-1"
                />
              </label>
              <label className="text-xs text-zinc-400">
                Minutos por vídeo (1–60)
                <input
                  type="number"
                  min={1}
                  max={60}
                  value={form.duration_spec.target_minutes_per_video}
                  onChange={(event) =>
                    setDuration({
                      ...form.duration_spec!,
                      target_minutes_per_video: Number(event.target.value),
                    })
                  }
                  className="input mt-1"
                />
              </label>
            </div>
          )}
          <p className="mt-4 text-sm text-zinc-300">
            Total: <strong>{form.duration_spec.total_videos} vídeos</strong> ·{" "}
            <strong>{form.duration_spec.total_minutes} minutos</strong> estimados
            (tolerancia final ±20 %).
          </p>
        </fieldset>
      )}
      <ErrorBanner>{error}</ErrorBanner>
      <button type="submit" disabled={saving} className="btn-primary">
        {saving && <Spinner className="border-white/40 border-t-white" />}
        {saving ? "Guardando…" : submitLabel}
      </button>
    </form>
  );
}
