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
import {
  ErrorBanner,
  IconChevronLeft,
  IconPlus,
  LoadingScreen,
} from "@/components/ui";

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
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
  const dirty =
    workflow !== null &&
    (name !== workflow.name ||
      description !== workflow.description ||
      JSON.stringify(steps) !== JSON.stringify(workflow.steps));

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
    setError(null);
    try {
      const updated = await api.updateWorkflow(id, { name, description, steps });
      setWorkflow(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
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
    return <LoadingScreen label="Cargando workflow…" />;
  }

  const step = selected !== null ? steps[selected] : null;

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Link
          href="/workflows"
          className="inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <IconChevronLeft size={15} />
          Workflows
        </Link>
        <div className="flex items-center gap-2">
          {dirty && !readOnly && (
            <span className="badge-warning">Cambios sin guardar</span>
          )}
          {saved && <span className="badge-success">Guardado ✓</span>}
          <button onClick={duplicate} className="btn-secondary btn-sm">
            Duplicar
          </button>
          {!readOnly && (
            <>
              <button onClick={remove} className="btn-danger btn-sm">
                Eliminar
              </button>
              <button onClick={save} disabled={!dirty} className="btn-primary btn-sm">
                Guardar
              </button>
            </>
          )}
        </div>
      </div>

      {readOnly && (
        <p className="badge-warning mb-4 px-3 py-2 text-xs">
          Esto es una plantilla de fábrica (solo lectura). Duplícala para editarla.
        </p>
      )}

      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        disabled={readOnly}
        className="mb-1 w-full rounded-lg border border-transparent bg-transparent text-2xl font-semibold tracking-tight text-zinc-50 outline-none focus:border-white/[0.15] disabled:opacity-100"
      />
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        disabled={readOnly}
        placeholder="Descripción"
        className="mb-6 w-full rounded-lg border border-transparent bg-transparent text-sm text-zinc-400 outline-none placeholder:text-zinc-600 focus:border-white/[0.15]"
      />

      <WorkflowCanvas
        steps={steps}
        selectedIndex={selected}
        onSelect={(i) => setSelected(i)}
      />
      <ErrorBanner>{error}</ErrorBanner>

      {!readOnly && (
        <div className="mt-4 flex flex-wrap gap-2">
          {AGENTS.map((a) => (
            <button
              key={a}
              onClick={() => {
                setSteps((prev) => [...prev, { agent: a }]);
                setSelected(steps.length);
              }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-dashed border-white/[0.15] px-3 py-1.5 text-xs font-medium text-zinc-300 transition-colors hover:border-indigo-400/60 hover:bg-indigo-500/[0.06] hover:text-indigo-200"
            >
              <IconPlus size={12} />
              {AGENT_NAMES[a]}
            </button>
          ))}
        </div>
      )}

      {step ? (
        <section className="card animate-in mt-6 p-5">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-zinc-100">
              Paso {selected! + 1} · {AGENT_NAMES[step.agent] ?? step.agent}
            </h2>
            {!readOnly && (
              <div className="flex gap-2">
                <button
                  onClick={() => moveStep(selected!, -1)}
                  disabled={selected === 0}
                  className="btn-secondary btn-sm"
                >
                  ← Mover
                </button>
                <button
                  onClick={() => moveStep(selected!, 1)}
                  disabled={selected === steps.length - 1}
                  className="btn-secondary btn-sm"
                >
                  Mover →
                </button>
                <button
                  onClick={() => {
                    setSteps((prev) => prev.filter((_s, i) => i !== selected));
                    setSelected(null);
                  }}
                  className="btn-danger btn-sm"
                >
                  Quitar
                </button>
              </div>
            )}
          </div>
          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <label className="label">Perfil del agente</label>
              <select
                value={step.profile_id ?? ""}
                onChange={(e) =>
                  updateStep(selected!, { profile_id: e.target.value || null })
                }
                disabled={readOnly}
                className="input"
              >
                <option value="">Perfil por defecto</option>
                {(profiles[step.agent] ?? []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} (v{p.version})
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-3">
              <label className="flex items-start gap-2.5 text-sm text-zinc-300">
                <input
                  type="checkbox"
                  checked={Boolean(step.approval_after)}
                  onChange={(e) =>
                    updateStep(selected!, { approval_after: e.target.checked })
                  }
                  disabled={readOnly}
                  className="mt-0.5 h-4 w-4 accent-indigo-500"
                />
                <span>
                  Pausar para aprobación humana tras este paso
                  <span className="block text-xs text-zinc-500">
                    El workflow espera tu revisión antes de continuar.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2.5 text-sm text-zinc-300">
                <input
                  type="checkbox"
                  checked={Boolean(step.evaluate)}
                  onChange={(e) =>
                    updateStep(selected!, { evaluate: e.target.checked })
                  }
                  disabled={readOnly}
                  className="mt-0.5 h-4 w-4 accent-indigo-500"
                />
                <span>
                  Evaluación automática
                  <span className="block text-xs text-zinc-500">
                    Un juez LLM revisa el resultado y pide correcciones hasta 2
                    veces; después escala a ti.
                  </span>
                </span>
              </label>
            </div>
          </div>
        </section>
      ) : (
        <p className="mt-4 text-sm text-zinc-500">
          Haz clic en un paso del diagrama para configurarlo.
        </p>
      )}
    </div>
  );
}
