"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type WikiPage } from "@/lib/api";
import { IconBook, IconPlus } from "@/components/ui";
import Markdown from "@/components/Markdown";

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
    await api.upsertWikiPage(projectId, slug, {
      title: newSlug.trim(),
      content_md: "",
    });
    setNewSlug("");
    await load();
  }

  return (
    <section className="mt-12">
      <div className="mb-1 flex items-center gap-2">
        <IconBook size={17} className="text-zinc-400" />
        <h2 className="text-lg font-semibold tracking-tight text-zinc-50">
          Memoria del proyecto
        </h2>
      </div>
      <p className="mb-4 max-w-3xl text-sm leading-relaxed text-zinc-400">
        El bibliotecario consolida aquí decisiones, glosario y estilo tras cada
        ejecución; los agentes la leen para mantener la coherencia. Puedes
        editarla directamente.
      </p>

      {pages.length === 0 && (
        <div className="card mb-3 border-dashed p-6 text-center text-sm text-zinc-500">
          La memoria está vacía: se irá llenando sola al ejecutar agentes.
        </div>
      )}

      <ul className="space-y-2">
        {pages.map((page) => (
          <li key={page.slug} className="card p-4">
            <div className="flex items-center justify-between gap-3">
              <span className="min-w-0 truncate text-sm font-semibold text-zinc-100">
                {page.title}
              </span>
              <div className="flex shrink-0 gap-2">
                <button
                  onClick={() => {
                    setEditing(editing === page.slug ? null : page.slug);
                    setDraft(page.content_md);
                  }}
                  className="btn-secondary btn-sm"
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
                  className="btn-danger btn-sm"
                >
                  Eliminar
                </button>
              </div>
            </div>
            {editing === page.slug ? (
              <div className="mt-3">
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  rows={7}
                  className="input resize-y font-mono text-[13px]"
                />
                <button
                  onClick={() => save(page.slug, page.title)}
                  className="btn-primary btn-sm mt-2"
                >
                  Guardar
                </button>
              </div>
            ) : (
              <article className="notebook-sheet mt-3 rounded-md border border-zinc-300 p-4">
                <Markdown>
                {page.content_md || "(vacía)"}
                </Markdown>
              </article>
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
          className="input flex-1"
        />
        <button
          type="submit"
          disabled={!newSlug.trim()}
          className="btn-secondary"
        >
          <IconPlus size={14} />
          Añadir
        </button>
      </form>
    </section>
  );
}
