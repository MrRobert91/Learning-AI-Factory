"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, type IdeationSessionSummary } from "@/lib/api";

export default function IdeationListPage() {
  const router = useRouter();
  const [sessions, setSessions] = useState<IdeationSessionSummary[] | null>(
    null,
  );
  const [idea, setIdea] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listIdeations().then(setSessions).catch(() => {});
  }, []);

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setStarting(true);
    try {
      const session = await api.createIdeation(idea);
      router.push(`/ideation/${session.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "No se pudo crear la sesión");
      setStarting(false);
    }
  }

  return (
    <main className="mx-auto max-w-3xl p-6">
      <div className="mb-6">
        <Link href="/" className="text-sm text-indigo-400 hover:underline">
          ← Volver al panel
        </Link>
      </div>
      <h1 className="mb-1 text-2xl font-semibold">Asistente de ideación</h1>
      <p className="mb-6 text-sm text-neutral-400">
        Cuéntale tu idea aunque sea vaga: te hará preguntas para afinarla hasta
        tener un brief listo para fabricar el curso.
      </p>

      <form
        onSubmit={start}
        className="mb-10 rounded-xl border border-neutral-800 bg-neutral-900/50 p-5"
      >
        <textarea
          value={idea}
          onChange={(e) => setIdea(e.target.value)}
          rows={3}
          required
          placeholder='Ej.: "algo de computación cuántica para gente técnica" o "un curso corto de RAG"'
          className="mb-3 w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-indigo-500"
        />
        {error && <p className="mb-3 text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={starting || !idea.trim()}
          className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
        >
          {starting ? "Pensando…" : "Empezar a idear"}
        </button>
      </form>

      <h2 className="mb-3 text-lg font-medium">Sesiones anteriores</h2>
      {sessions === null ? (
        <p className="text-neutral-400">Cargando…</p>
      ) : sessions.length === 0 ? (
        <p className="text-sm text-neutral-500">Todavía no hay sesiones.</p>
      ) : (
        <ul className="space-y-2">
          {sessions.map((s) => (
            <li key={s.id}>
              <Link
                href={`/ideation/${s.id}`}
                className="block rounded-lg border border-neutral-800 p-3 text-sm transition hover:border-neutral-600"
              >
                <div className="flex items-center justify-between">
                  <span className="line-clamp-1">{s.initial_idea}</span>
                  <span className="ml-3 shrink-0 rounded-full border border-neutral-700 px-2 py-0.5 text-xs text-neutral-400">
                    {s.status === "finalized"
                      ? "Proyecto creado"
                      : s.has_brief
                        ? "Brief listo"
                        : "En curso"}
                  </span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
