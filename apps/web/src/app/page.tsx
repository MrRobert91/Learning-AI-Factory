"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, type Project } from "@/lib/api";
import ProjectForm from "@/components/ProjectForm";

const STATUS_LABELS: Record<string, string> = {
  draft: "Borrador",
  active: "Activo",
  archived: "Archivado",
};

export default function DashboardPage() {
  const router = useRouter();
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    setProjects(await api.listProjects());
  }, []);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  async function logout() {
    await api.logout();
    router.push("/login");
  }

  return (
    <main className="mx-auto max-w-4xl p-6">
      <header className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">AI Learning Factory</h1>
          <p className="text-sm text-neutral-400">Tus proyectos educativos</p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/ideation"
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500"
          >
            💡 Nueva idea (asistente)
          </Link>
          <button
            onClick={() => setShowForm((v) => !v)}
            className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-900"
          >
            {showForm ? "Cancelar" : "Proyecto manual"}
          </button>
          <Link
            href="/workflows"
            className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-900"
          >
            Workflows
          </Link>
          <Link
            href="/profiles"
            className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-900"
          >
            Perfiles
          </Link>
          <button
            onClick={logout}
            className="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 hover:bg-neutral-900"
          >
            Salir
          </button>
        </div>
      </header>

      {showForm && (
        <section className="mb-8 rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
          <h2 className="mb-4 text-lg font-medium">Nuevo proyecto</h2>
          <ProjectForm
            submitLabel="Crear proyecto"
            onSubmit={async (input) => {
              const project = await api.createProject(input);
              setShowForm(false);
              router.push(`/projects/${project.id}`);
            }}
          />
        </section>
      )}

      {projects === null ? (
        <p className="text-neutral-400">Cargando…</p>
      ) : projects.length === 0 ? (
        <div className="rounded-xl border border-dashed border-neutral-800 p-10 text-center text-neutral-400">
          <p className="mb-2">Todavía no tienes proyectos.</p>
          <p className="text-sm">
            Crea uno para empezar a fabricar tu primer curso.
          </p>
        </div>
      ) : (
        <ul className="space-y-3">
          {projects.map((p) => (
            <li key={p.id}>
              <Link
                href={`/projects/${p.id}`}
                className="block rounded-xl border border-neutral-800 p-4 transition hover:border-neutral-600"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium">{p.title}</span>
                  <span className="rounded-full border border-neutral-700 px-2 py-0.5 text-xs text-neutral-400">
                    {STATUS_LABELS[p.status] ?? p.status}
                  </span>
                </div>
                {p.topic && (
                  <p className="mt-1 line-clamp-2 text-sm text-neutral-400">
                    {p.topic}
                  </p>
                )}
                <p className="mt-2 text-xs text-neutral-500">
                  {p.audience && <>Audiencia: {p.audience} · </>}
                  {p.level && <>Nivel: {p.level} · </>}
                  Actualizado: {new Date(p.updated_at).toLocaleString("es")}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
