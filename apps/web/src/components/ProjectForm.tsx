"use client";

import { useState } from "react";
import type { ProjectInput } from "@/lib/api";

const LEVELS = ["introductorio", "intermedio", "avanzado"];
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

const inputClass =
  "w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-indigo-500";

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
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="mb-1 block text-sm text-neutral-300">Título *</label>
        <input
          value={form.title}
          onChange={(e) => set("title", e.target.value)}
          required
          placeholder="Introducción a los LLMs"
          className={inputClass}
        />
      </div>
      <div>
        <label className="mb-1 block text-sm text-neutral-300">Tema</label>
        <textarea
          value={form.topic}
          onChange={(e) => set("topic", e.target.value)}
          rows={2}
          placeholder="Qué quieres enseñar y con qué enfoque"
          className={inputClass}
        />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="mb-1 block text-sm text-neutral-300">
            Audiencia
          </label>
          <input
            value={form.audience}
            onChange={(e) => set("audience", e.target.value)}
            placeholder="Perfiles técnicos sin ML"
            className={inputClass}
          />
        </div>
        <div>
          <label className="mb-1 block text-sm text-neutral-300">Nivel</label>
          <select
            value={form.level}
            onChange={(e) => set("level", e.target.value)}
            className={inputClass}
          >
            {LEVELS.map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-sm text-neutral-300">Idioma</label>
          <select
            value={form.language}
            onChange={(e) => set("language", e.target.value)}
            className={inputClass}
          >
            <option value="es">Español</option>
            <option value="en">Inglés</option>
          </select>
        </div>
        <div>
          <label className="mb-1 block text-sm text-neutral-300">
            Formato de salida
          </label>
          <select
            value={form.output_format}
            onChange={(e) => set("output_format", e.target.value)}
            className={inputClass}
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
        <label className="mb-1 block text-sm text-neutral-300">Estilo</label>
        <input
          value={form.style}
          onChange={(e) => set("style", e.target.value)}
          placeholder="Práctico, con ejemplos de código"
          className={inputClass}
        />
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
      <button
        type="submit"
        disabled={saving}
        className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
      >
        {saving ? "Guardando…" : submitLabel}
      </button>
    </form>
  );
}
