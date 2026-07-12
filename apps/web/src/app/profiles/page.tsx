"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type AgentProfile, type AgentSpec } from "@/lib/api";

export default function ProfilesPage() {
  const [agents, setAgents] = useState<AgentSpec[]>([]);
  const [profiles, setProfiles] = useState<Record<string, AgentProfile[]>>({});
  const [creating, setCreating] = useState<string | null>(null);
  const [newName, setNewName] = useState("");

  const load = useCallback(async () => {
    const specs = await api.listAgents();
    setAgents(specs);
    const byType: Record<string, AgentProfile[]> = {};
    await Promise.all(
      specs.map(async (s) => {
        byType[s.name] = await api.listProfiles(s.name);
      }),
    );
    setProfiles(byType);
  }, []);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  async function createProfile(agentType: string) {
    if (!newName.trim()) return;
    await api.createProfile(agentType, { name: newName.trim() });
    setCreating(null);
    setNewName("");
    await load();
  }

  return (
    <main className="mx-auto max-w-4xl p-6">
      <div className="mb-6">
        <Link href="/" className="text-sm text-indigo-400 hover:underline">
          ← Volver al panel
        </Link>
      </div>
      <h1 className="mb-1 text-2xl font-semibold">Perfiles de agentes</h1>
      <p className="mb-8 text-sm text-neutral-400">
        Cada perfil define la personalidad (<code>soul.md</code>) y las reglas
        operativas (<code>agents.md</code>) de un agente. Puedes tener varios y
        elegir cuál usar en cada ejecución.
      </p>

      {agents.map((agent) => (
        <section key={agent.name} className="mb-8">
          <div className="mb-2 flex items-center justify-between">
            <div>
              <h2 className="text-lg font-medium">{agent.display_name}</h2>
              <p className="text-sm text-neutral-400">{agent.description}</p>
            </div>
            <button
              onClick={() => {
                setCreating(creating === agent.name ? null : agent.name);
                setNewName("");
              }}
              className="rounded-lg border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-900"
            >
              Nuevo perfil
            </button>
          </div>
          {creating === agent.name && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                createProfile(agent.name);
              }}
              className="mb-3 flex gap-2"
            >
              <input
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                autoFocus
                placeholder="Nombre del perfil (ej. Curador divulgativo)"
                className="flex-1 rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 text-sm outline-none focus:border-indigo-500"
              />
              <button
                type="submit"
                className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500"
              >
                Crear
              </button>
            </form>
          )}
          <ul className="space-y-2">
            {(profiles[agent.name] ?? []).map((p) => (
              <li key={p.id}>
                <Link
                  href={`/profiles/${p.id}`}
                  className="flex items-center justify-between rounded-lg border border-neutral-800 p-3 text-sm transition hover:border-neutral-600"
                >
                  <span>{p.name}</span>
                  <span className="flex items-center gap-2 text-xs text-neutral-500">
                    v{p.version}
                    {p.is_default && (
                      <span className="rounded-full border border-indigo-800 px-2 py-0.5 text-indigo-400">
                        por defecto
                      </span>
                    )}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ))}
    </main>
  );
}
