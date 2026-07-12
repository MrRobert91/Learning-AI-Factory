"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  api,
  type AgentProfile,
  type Workflow,
  type WorkflowStep,
} from "@/lib/api";
import WorkflowCanvas from "@/components/WorkflowCanvas";

const AGENTS = [
  "curator",
  "planner",
  "lessons",
  "slides",
  "script",
  "voice",
  "video",
  "publisher",
];
const PROFILE_AGENTS = [
  "curator",
  "planner",
  "lessons",
  "slides",
  "script",
  "voice",
  "publisher",
];
const AGENT_NAMES: Record<string, string> = {
  curator: "Curador",
  planner: "Plan del curso",
  lessons: "Lecciones",
  slides: "Slides",
  script: "Guion docente",
  voice: "Adaptación a voz",
  video: "Vídeo",
  publisher: "Publicación",
};

export default function WorkflowEditorPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [workflow, setWorkflow] = useState<Workflow | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [profiles, setProfiles] = useState<Record<string, AgentProfile[]>>({});
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    api
      .getWorkflow(id)
      .then((w) => {
        setWorkflow(w);
        setName(w.name);
        setDescription(w.description);
        setSteps(w.steps);
      })
      .catch(() => {});
    Promise.all(
      PROFILE_AGENTS.map(async (a) => [a, await api.listProfiles(a)] as const),
    ).then((entries) => setProfiles(Object.fromEntries(entries)));
  }, [id]);

  const readOnly = workflow?.is_template ?? false;

  function updateStep(index: number, patch: Partial<WorkflowStep>) {
    setSteps((prev) =>
      prev.map((s, i) => (i === index ? { ...s, ...patch } : s)),
    );
  }

  function moveStep(index: number, delta: number) {
    const j = index + delta;
    if (j < 0 || j >= steps.length) return;
    setSteps((prev) => {
      const next = [...prev];
      [next[index], next[j]] = [next[j], next[index]];
      return next;
    });
    setSelected(j);
  }

  async function save() {
    setMessage(null);
    try {
      const updated = await api.updateWorkflow(id, { name, description, steps });
      setWorkflow(updated);
      setMessage("Guardado ✓");
      setTimeout(() => setMessage(null), 2000);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Error al guardar");
    }
  }

  async function duplicate() {
    const copy = await api.createWorkflow({
      name: `${name} (copia)`,
      description,
      steps,
    });
    router.push(`/workflows/${copy.id}`);
  }

  async function remove() {
    if (!confirm("¿Eliminar este workflow?")) return;
    await api.deleteWorkflow(id);
    router.push("/workflows");
  }

  if (!workflow) {
    return (
      <main className="mx-auto max-w-4xl p-6 text-neutral-400">Cargando…</main>
    );
  }

  const step = selected !== null ? steps[selected] : null;

  return (
    <main className="mx-auto max-w-4xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <Link href="/workflows" className="text-sm text-indigo-400 hover:underline">
          ← Workflows
        </Link>
        <div className="flex gap-2">
          <button
            onClick={duplicate}
            className="rounded-lg border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-900"
          >
            Duplicar
          </button>
          {!readOnly && (
            <>
              <button
                onClick={remove}
                className="rounded-lg border border-red-900 px-3 py-1.5 text-sm text-red-400 hover:bg-red-950"
              >
                Eliminar
              </button>
              <button
                onClick={save}
                className="rounded-lg bg-indigo-600 px-4 py-1.5 text-sm font-medium hover:bg-indigo-500"
              >
                Guardar
              </button>
            </>
          )}
        </div>
      </div>

      {readOnly && (
        <p className="mb-4 rounded-lg border border-amber-900/60 bg-amber-950/30 p-3 text-sm text-amber-300">
          Esto es una plantilla de fábrica (solo lectura). Duplícala para editarla.
        </p>
      )}

      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        disabled={readOnly}
        className="mb-1 w-full rounded-lg border border-transparent bg-transparent text-2xl font-semibold outline-none focus:border-neutral-700 disabled:opacity-100"
      />
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        disabled={readOnly}
        placeholder="Descripción"
        className="mb-6 w-full rounded-lg border border-transparent bg-transparent text-sm text-neutral-400 outline-none focus:border-neutral-700"
      />

      <WorkflowCanvas
        steps={steps}
        selectedIndex={selected}
        onSelect={(i) => setSelected(i)}
      />
      {message && <p className="mt-2 text-sm text-emerald-400">{message}</p>}

      {!readOnly && (
        <div className="mt-4 flex flex-wrap gap-2">
          {AGENTS.map((a) => (
            <button
              key={a}
              onClick={() => {
                setSteps((prev) => [...prev, { agent: a }]);
                setSelected(steps.length);
              }}
              className="rounded-lg border border-dashed border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:border-indigo-500"
            >
              + {AGENT_NAMES[a]}
            </button>
          ))}
        </div>
      )}

      {step && (
        <section className="mt-6 rounded-xl border border-neutral-800 bg-neutral-900/50 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-medium">
              Paso {selected! + 1}: {AGENT_NAMES[step.agent] ?? step.agent}
            </h2>
            {!readOnly && (
              <div className="flex gap-2 text-xs">
                <button
                  onClick={() => moveStep(selected!, -1)}
                  className="rounded border border-neutral-700 px-2 py-1 hover:bg-neutral-900"
                >
                  ← mover
                </button>
                <button
                  onClick={() => moveStep(selected!, 1)}
                  className="rounded border border-neutral-700 px-2 py-1 hover:bg-neutral-900"
                >
                  mover →
                </button>
                <button
                  onClick={() => {
                    setSteps((prev) => prev.filter((_s, i) => i !== selected));
                    setSelected(null);
                  }}
                  className="rounded border border-red-900 px-2 py-1 text-red-400 hover:bg-red-950"
                >
                  quitar
                </button>
              </div>
            )}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs text-neutral-400">
                Perfil del agente
              </label>
              <select
                value={step.profile_id ?? ""}
                onChange={(e) =>
                  updateStep(selected!, { profile_id: e.target.value || null })
                }
                disabled={readOnly}
                className="w-full rounded-lg border border-neutral-700 bg-neutral-900 px-2 py-1.5 text-sm outline-none"
              >
                <option value="">Perfil por defecto</option>
                {(profiles[step.agent] ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} (v{p.version})
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <label className="flex items-center gap-2 text-sm text-neutral-300">
                <input
                  type="checkbox"
                  checked={Boolean(step.approval_after)}
                  onChange={(e) =>
                    updateStep(selected!, { approval_after: e.target.checked })
                  }
                  disabled={readOnly}
                  className="h-4 w-4"
                />
                Pausar para aprobación humana tras este paso
              </label>
              <label className="flex items-center gap-2 text-sm text-neutral-300">
                <input
                  type="checkbox"
                  checked={Boolean(step.evaluate)}
                  onChange={(e) =>
                    updateStep(selected!, { evaluate: e.target.checked })
                  }
                  disabled={readOnly}
                  className="h-4 w-4"
                />
                Evaluación automática (revisa y corrige hasta 2 veces, luego
                escala a ti)
              </label>
            </div>
          </div>
        </section>
      )}
    </main>
  );
}
