"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type WikiPage } from "@/lib/api";

export default function WikiPanel({ projectId }: { projectId: string }) {
  const [pages, setPages] = useState<WikiPage[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [newSlug, setNewSlug] = useState("");

  const load = useCallback(async () => {
    setPages(await api.listProjectWiki(projectId));
  }, [projectId]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  async function save(slug: string, title: string) {
    await api.upsertWikiPage(projectId, slug, { title, content_md: draft });
    setEditing(null);
    await load();
  }

  async function createPage() {
    const slug = newSlug
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
    if (!slug) return;
    await api.upsertWikiPage(projectId, slug, { title: newSlug.trim(), content_md: "" });
    setNewSlug("");
    await load();
  }

  return (
    <section className="mt-10">
      <h2 className="mb-1 text-lg font-medium">Memoria del proyecto (wiki)</h2>
      <p className="mb-4 text-sm text-neutral-400">
        El bibliotecario consolida aquí decisiones, glosario y estilo tras cada
        ejecución; los agentes la leen para mantener la coherencia. Puedes
        editarla directamente.
      </p>

      {pages.length === 0 && (
        <p className="mb-3 text-sm text-neutral-500">
          La wiki está vacía: se irá llenando sola al ejecutar agentes.
        </p>
      )}

      <ul className="space-y-2">
        {pages.map((page) => (
          <li key={page.slug} className="rounded-lg border border-neutral-800 p-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{page.title}</span>
              <div className="flex gap-2 text-xs">
                <button
                  onClick={() => {
                    setEditing(editing === page.slug ? null : page.slug);
                    setDraft(page.content_md);
                  }}
                  className="rounded border border-neutral-700 px-2 py-1 text-neutral-300 hover:bg-neutral-900"
                >
                  {editing === page.slug ? "Cancelar" : "Editar"}
                </button>
                <button
                  onClick={async () => {
                    if (confirm(`¿Eliminar la página «${page.title}»?`)) {
                      await api.deleteWikiPage(projectId, page.slug);
                      await load();
                    }
                  }}
                  className="rounded border border-red-900 px-2 py-1 text-red-400 hover:bg-red-950"
                >
                  Eliminar
                </button>
              </div>
            </div>
            {editing === page.slug ? (
              <div className="mt-2">
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  rows={6}
                  className="w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 font-mono text-sm outline-none focus:border-indigo-500"
                />
                <button
                  onClick={() => save(page.slug, page.title)}
                  className="mt-2 rounded-lg bg-indigo-600 px-3 py-1.5 text-sm font-medium hover:bg-indigo-500"
                >
                  Guardar
                </button>
              </div>
            ) : (
              <pre className="mt-2 whitespace-pre-wrap text-sm text-neutral-400">
                {page.content_md || "(vacía)"}
              </pre>
            )}
          </li>
        ))}
      </ul>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          createPage();
        }}
        className="mt-3 flex gap-2"
      >
        <input
          value={newSlug}
          onChange={(e) => setNewSlug(e.target.value)}
          placeholder="Nueva página (ej. referencias)"
          className="flex-1 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        <button
          type="submit"
          disabled={!newSlug.trim()}
          className="rounded-lg border border-neutral-700 px-3 py-2 text-sm text-neutral-300 hover:bg-neutral-900 disabled:opacity-50"
        >
          Añadir
        </button>
      </form>
    </section>
  );
}
