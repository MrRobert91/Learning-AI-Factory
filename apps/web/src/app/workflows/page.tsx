"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, type Workflow } from "@/lib/api";
import {
  EmptyState,
  IconPlus,
  IconWorkflow,
  LoadingScreen,
  PageHeader,
} from "@/components/ui";
import {
  ARTIFACT_NAMES,
  requiredInitialArtifacts,
  validateWorkflowSteps,
} from "@/lib/workflowRules";

export default function WorkflowsPage() {
  const router = useRouter();
  const [workflows, setWorkflows] = useState<Workflow[] | null>(null);

  useEffect(() => {
    api.listWorkflows().then(setWorkflows).catch(() => {});
  }, []);

  async function duplicate(w: Workflow) {
    const copy = await api.createWorkflow({
      name: `${w.name} (copia)`,
      description: w.description,
      steps: w.steps,
    });
    router.push(`/workflows/${copy.id}`);
  }

  async function createNew() {
    const w = await api.createWorkflow({
      name: "Nuevo workflow",
      steps: [{ agent: "curator" }],
    });
    router.push(`/workflows/${w.id}`);
  }

  const templates = workflows?.filter((w) => w.is_template) ?? [];
  const own = workflows?.filter((w) => !w.is_template) ?? [];

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <PageHeader
        title="Workflows"
        description="Cadenas de agentes con puntos de aprobación humana. Usa una plantilla tal cual, duplícala para personalizarla, o crea la tuya desde cero."
        actions={
          <button onClick={createNew} className="btn-primary">
            <IconPlus size={15} />
            Nuevo workflow
          </button>
        }
      />

      {workflows === null ? (
        <LoadingScreen label="Cargando workflows…" />
      ) : (
        <>
          <h2 className="mb-3 text-base font-semibold tracking-tight text-zinc-100">
            Plantillas
          </h2>
          <ul className="mb-10 space-y-2">
            {templates.map((w) => (
              <li
                key={w.id}
                className="card card-hover flex items-center gap-4 p-4"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-indigo-500/[0.12] text-indigo-300">
                  <IconWorkflow size={17} />
                </span>
                <div className="min-w-0 flex-1">
                  <Link
                    href={`/workflows/${w.id}`}
                    className="text-sm font-semibold text-zinc-100 hover:underline"
                  >
                    {w.name}
                  </Link>
                  <p className="truncate text-xs text-zinc-500">
                    {w.description || `${w.steps.length} pasos`}
                  </p>
                  {requiredInitialArtifacts(w.steps).length > 0 && (
                    <p className="mt-1 text-xs text-amber-300">
                      Para ejecutarlo, el proyecto debe tener:{" "}
                      {requiredInitialArtifacts(w.steps)
                        .map((type) => ARTIFACT_NAMES[type] ?? type)
                        .join(", ")}
                    </p>
                  )}
                </div>
                <span className="badge-neutral shrink-0">
                  {w.steps.length} pasos
                </span>
                <button
                  onClick={() => duplicate(w)}
                  className="btn-secondary btn-sm shrink-0"
                  disabled={validateWorkflowSteps(w.steps).length > 0}
                  title={
                    validateWorkflowSteps(w.steps)[0] ??
                    "Duplicar esta plantilla"
                  }
                >
                  Duplicar
                </button>
              </li>
            ))}
          </ul>

          <h2 className="mb-3 text-base font-semibold tracking-tight text-zinc-100">
            Mis workflows
          </h2>
          {own.length === 0 ? (
            <EmptyState
              icon={<IconWorkflow size={22} />}
              title="Todavía no tienes workflows propios"
              description="Duplica una plantilla o crea uno nuevo para personalizar la cadena de agentes."
            />
          ) : (
            <ul className="space-y-2">
              {own.map((w) => (
                <li key={w.id}>
                  <Link
                    href={`/workflows/${w.id}`}
                    className="card card-hover flex items-center gap-4 p-4 text-sm"
                  >
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white/[0.05] text-zinc-400">
                      <IconWorkflow size={17} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-semibold text-zinc-100">
                        {w.name}
                      </span>
                      {w.description && (
                        <span className="block truncate text-xs text-zinc-500">
                          {w.description}
                        </span>
                      )}
                    </span>
                    <span className="badge-neutral shrink-0">
                      {w.steps.length} pasos
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
