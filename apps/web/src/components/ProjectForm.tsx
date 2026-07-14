"use client";

import { useState } from "react";
import type { ProjectInput } from "@/lib/api";
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
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function set<K extends keyof ProjectInput>(key: K, value: ProjectInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
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
      <ErrorBanner>{error}</ErrorBanner>
      <button type="submit" disabled={saving} className="btn-primary">
        {saving && <Spinner className="border-white/40 border-t-white" />}
        {saving ? "Guardando…" : submitLabel}
      </button>
    </form>
  );
}
