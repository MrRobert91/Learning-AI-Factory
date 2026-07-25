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
  ConfirmDialog,
  ErrorBanner,
  IconChevronLeft,
  IconPlus,
  LoadingScreen,
} from "@/components/ui";
import {
  unavailableReason,
  ARTIFACT_NAMES,
  requiredInitialArtifacts,
  validateWorkflowSteps,
  WORKFLOW_AGENTS,
} from "@/lib/workflowRules";

const PROFILE_AGENTS = [
  "curator",
  "planner",
  "lessons",
  "slides",
  "script",
  "voice",
  "video",
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
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

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

  function reorderedSteps(index: number, delta: number): WorkflowStep[] | null {
    const target = index + delta;
    if (target < 0 || target >= steps.length) return null;
    const next = [...steps];
    [next[index], next[target]] = [next[target], next[index]];
    return next;
  }

  function moveStep(index: number, delta: number) {
    const next = reorderedSteps(index, delta);
    if (!next || validateWorkflowSteps(next).length > 0) return;
    setSteps(next);
    setSelected(index + delta);
  }

  function canMoveStep(index: number, delta: number): boolean {
    const next = reorderedSteps(index, delta);
    return next !== null && validateWorkflowSteps(next).length === 0;
  }

  async function save() {
    setError(null);
    const problems = validateWorkflowSteps(steps);
    if (problems.length > 0) {
      setError(problems[0]);
      return;
    }
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
    setDeleting(true);
    try {
      await api.deleteWorkflow(id);
      router.push("/workflows");
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo eliminar");
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  if (!workflow) {
    return <LoadingScreen label="Cargando workflow…" />;
  }

  const step = selected !== null ? steps[selected] : null;
  const selectedStepProfile = step
    ? step.profile_id
      ? (profiles[step.agent] ?? []).find(
          (profile) => profile.id === step.profile_id,
        )
      : (profiles[step.agent] ?? []).find((profile) => profile.is_default) ??
        (profiles[step.agent] ?? [])[0]
    : undefined;

  const workflowProblems = validateWorkflowSteps(steps);
  return (
    <div className="mx-auto max-w-[1600px] px-6 py-8">
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
          <button
            onClick={duplicate}
            disabled={workflowProblems.length > 0}
            title={workflowProblems[0]}
            className="btn-secondary btn-sm"
          >
            Duplicar
          </button>
          {!readOnly && (
            <>
              <button onClick={() => setConfirmDelete(true)} className="btn-danger btn-sm">
                Eliminar
              </button>
              <button
                onClick={save}
                disabled={!dirty || workflowProblems.length > 0}
                className="btn-primary btn-sm"
              >
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

      <section className="card mb-4 grid gap-3 p-4 md:grid-cols-[auto_1fr]">
        <span className="flex h-8 w-8 items-center justify-center rounded-md border-2 border-zinc-300 bg-[#f4ead7] text-sm font-bold text-indigo-500">
          ?
        </span>
        <div>
          <h2 className="text-sm font-semibold text-zinc-100">
            C&oacute;mo construir el workflow
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-zinc-400">
            Puedes empezar por cualquier agente. Los materiales que necesite el
            primero se consideran requisitos del proyecto; los pasos siguientes
            deben consumir resultados ya disponibles. Haz clic en un nodo para
            configurar su perfil. Las revisiones autom&aacute;tica y humana se
            configuran y versionan dentro de cada perfil.
          </p>
          {requiredInitialArtifacts(steps).length > 0 && (
            <p className="mt-2 text-xs font-medium text-amber-300">
              Para ejecutarlo, el proyecto debe tener:{" "}
              {requiredInitialArtifacts(steps)
                .map((type) => ARTIFACT_NAMES[type] ?? type)
                .join(", ")}
            </p>
          )}
          <p className="mt-1 text-xs text-zinc-500">
            Si falta alguno, la ejecuci&oacute;n se desactiva e indica el motivo.
          </p>
        </div>
      </section>
      <WorkflowCanvas
        steps={steps}
        selectedIndex={selected}
        onSelect={(i) => setSelected(i)}
      />
      <ErrorBanner>{error ?? (!readOnly ? workflowProblems[0] : null)}</ErrorBanner>

      {!readOnly && (
        <section className="card mt-4 p-4">
          <div className="mb-3">
            <h2 className="text-sm font-semibold text-zinc-100">
              A&ntilde;adir el siguiente agente
            </h2>
            <p className="mt-1 text-xs text-zinc-500">
              Los agentes en gris todav&iacute;a no son compatibles. Pasa el cursor
              sobre ellos para ver qu&eacute; material necesitan.
            </p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {WORKFLOW_AGENTS.map((agent) => {
              const reason = unavailableReason(agent, steps);
              const available = reason === null;
              return (
                <button
                  key={agent}
                  disabled={!available}
                  title={reason ?? `A\u00f1adir ${AGENT_NAMES[agent]}`}
                  onClick={() => {
                    setSteps((prev) => [...prev, { agent }]);
                    setSelected(steps.length);
                  }}
                  className={
                    available
                      ? "flex min-h-20 items-start gap-2 rounded-md border-2 border-indigo-400 bg-[#f8eee0] p-3 text-left transition-colors hover:bg-[#f1dfca]"
                      : "flex min-h-20 cursor-not-allowed items-start gap-2 rounded-md border-2 border-zinc-300 bg-zinc-500/10 p-3 text-left opacity-55"
                  }
                >
                  <IconPlus size={14} className="mt-0.5 shrink-0" />
                  <span className="min-w-0">
                    <span className="block text-xs font-bold text-[#241d18]">
                      {AGENT_NAMES[agent]}
                    </span>
                    <span className="mt-1 block text-[11px] leading-snug text-zinc-700">
                      {reason ?? "Disponible como siguiente paso"}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </section>
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
                  disabled={!canMoveStep(selected!, -1)}
                  className="btn-secondary btn-sm"
                >
                  ← Mover
                </button>
                <button
                  onClick={() => moveStep(selected!, 1)}
                  disabled={!canMoveStep(selected!, 1)}
                  className="btn-secondary btn-sm"
                >
                  Mover →
                </button>
                <button
                  onClick={() => {
                    setSteps((prev) => prev.slice(0, -1));
                    setSelected(steps.length > 1 ? steps.length - 2 : null);
                  }}
                  disabled={selected !== steps.length - 1}
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
                    {p.orientation
                      ? ` · ${p.orientation === "vertical" ? "9:16" : "16:9"}`
                      : ""}
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <p className="rounded-md border border-white/[0.08] bg-black/20 p-3 text-xs leading-relaxed text-zinc-400">
                Revisión automática: {selectedStepProfile?.automatic_review_enabled
                  ? `sí · ${selectedStepProfile.max_automatic_regenerations} regeneraciones`
                  : "no"}
              </p>
              <p className="rounded-md border border-white/[0.08] bg-black/20 p-3 text-xs leading-relaxed text-zinc-400">
                Aprobación humana: {selectedStepProfile?.human_review_enabled
                  ? "sí · el workflow esperará tu decisión"
                  : "no · continuará automáticamente"}
                <span className="mt-1 block text-zinc-500">
                  Ambas políticas pertenecen al perfil y quedan congeladas al iniciar el run.
                </span>
              </p>
            </div>
          </div>
        </section>
      ) : (
        <p className="mt-4 text-sm text-zinc-500">
          Haz clic en un paso del diagrama para configurarlo.
        </p>
      )}
      <ConfirmDialog
        open={confirmDelete}
        title="Eliminar workflow"
        description={`Se eliminará «${workflow.name}». Esta acción no se puede deshacer.`}
        busy={deleting}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={remove}
      />
    </div>
  );
}
