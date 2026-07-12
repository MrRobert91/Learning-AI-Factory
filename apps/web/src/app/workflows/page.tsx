"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, type Workflow } from "@/lib/api";

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
    <main className="mx-auto max-w-4xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <Link href="/" className="text-sm text-indigo-400 hover:underline">
          ← Volver al panel
        </Link>
        <button
          onClick={createNew}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500"
        >
          Nuevo workflow
        </button>
      </div>
      <h1 className="mb-1 text-2xl font-semibold">Workflows</h1>
      <p className="mb-8 text-sm text-neutral-400">
        Cadenas de agentes con puntos de aprobación humana. Usa una plantilla tal
        cual, duplícala para personalizarla, o crea la tuya.
      </p>

      {workflows === null ? (
        <p className="text-neutral-400">Cargando…</p>
      ) : (
        <>
          <h2 className="mb-3 text-lg font-medium">Plantillas</h2>
          <ul className="mb-8 space-y-2">
            {templates.map((w) => (
              <li
                key={w.id}
                className="flex items-center justify-between rounded-lg border border-neutral-800 p-3 text-sm"
              >
                <div className="min-w-0">
                  <Link
                    href={`/workflows/${w.id}`}
                    className="font-medium hover:underline"
                  >
                    {w.name}
                  </Link>
                  <p className="text-xs text-neutral-500">{w.description}</p>
                </div>
                <button
                  onClick={() => duplicate(w)}
                  className="ml-3 shrink-0 rounded-lg border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:bg-neutral-900"
                >
                  Duplicar
                </button>
              </li>
            ))}
          </ul>

          <h2 className="mb-3 text-lg font-medium">Mis workflows</h2>
          {own.length === 0 ? (
            <p className="text-sm text-neutral-500">
              Todavía no tienes workflows propios.
            </p>
          ) : (
            <ul className="space-y-2">
              {own.map((w) => (
                <li key={w.id}>
                  <Link
                    href={`/workflows/${w.id}`}
                    className="flex items-center justify-between rounded-lg border border-neutral-800 p-3 text-sm transition hover:border-neutral-600"
                  >
                    <span>{w.name}</span>
                    <span className="text-xs text-neutral-500">
                      {w.steps.length} pasos
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </main>
  );
}
