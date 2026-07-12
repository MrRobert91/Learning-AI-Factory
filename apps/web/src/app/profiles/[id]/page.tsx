"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api, type AgentProfile, type ProfileVersion } from "@/lib/api";

const areaClass =
  "w-full rounded-lg border border-neutral-700 bg-neutral-900 px-3 py-2 font-mono text-sm outline-none focus:border-indigo-500";

export default function ProfileEditorPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [profile, setProfile] = useState<AgentProfile | null>(null);
  const [versions, setVersions] = useState<ProfileVersion[]>([]);
  const [name, setName] = useState("");
  const [soul, setSoul] = useState("");
  const [agentsMd, setAgentsMd] = useState("");
  const [model, setModel] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    const p = await api.getProfile(id);
    setProfile(p);
    setName(p.name);
    setSoul(p.soul_md);
    setAgentsMd(p.agents_md);
    setModel(p.model ?? "");
    setVersions(await api.getProfileVersions(id));
  }

  useEffect(() => {
    load().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function save() {
    setSaving(true);
    setMessage(null);
    try {
      await api.updateProfile(id, {
        name,
        soul_md: soul,
        agents_md: agentsMd,
        model: model || undefined,
        note,
      });
      setNote("");
      await load();
      setMessage("Guardado ✓");
      setTimeout(() => setMessage(null), 2000);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Error al guardar");
    } finally {
      setSaving(false);
    }
  }

  async function makeDefault() {
    await api.updateProfile(id, { is_default: true });
    await load();
  }

  async function remove() {
    if (!confirm("¿Eliminar este perfil?")) return;
    await api.deleteProfile(id);
    router.push("/profiles");
  }

  if (!profile) {
    return (
      <main className="mx-auto max-w-3xl p-6 text-neutral-400">Cargando…</main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <Link href="/profiles" className="text-sm text-indigo-400 hover:underline">
          ← Perfiles
        </Link>
        <div className="flex gap-2">
          {!profile.is_default && (
            <>
              <button
                onClick={makeDefault}
                className="rounded-lg border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-900"
              >
                Hacer por defecto
              </button>
              <button
                onClick={remove}
                className="rounded-lg border border-red-900 px-3 py-1.5 text-sm text-red-400 hover:bg-red-950"
              >
                Eliminar
              </button>
            </>
          )}
        </div>
      </div>

      <div className="mb-1 flex items-center gap-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="flex-1 rounded-lg border border-transparent bg-transparent text-2xl font-semibold outline-none focus:border-neutral-700"
        />
        <span className="text-sm text-neutral-500">v{profile.version}</span>
      </div>
      <p className="mb-6 text-sm text-neutral-500">
        Agente: {profile.agent_type}
        {profile.is_default && " · perfil por defecto"}
      </p>

      <div className="space-y-5">
        <div>
          <label className="mb-1 block text-sm font-medium text-neutral-300">
            soul.md — personalidad y criterio
          </label>
          <textarea
            value={soul}
            onChange={(e) => setSoul(e.target.value)}
            rows={8}
            className={areaClass}
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-neutral-300">
            agents.md — instrucciones operativas
          </label>
          <textarea
            value={agentsMd}
            onChange={(e) => setAgentsMd(e.target.value)}
            rows={8}
            className={areaClass}
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="mb-1 block text-sm text-neutral-300">
              Modelo (opcional, slug de OpenRouter)
            </label>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="por defecto del sistema"
              className={areaClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm text-neutral-300">
              Nota de esta versión
            </label>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="qué has cambiado y por qué"
              className={areaClass}
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={save}
            disabled={saving}
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium hover:bg-indigo-500 disabled:opacity-50"
          >
            {saving ? "Guardando…" : "Guardar (nueva versión)"}
          </button>
          {message && <span className="text-sm text-emerald-400">{message}</span>}
        </div>
      </div>

      <section className="mt-10">
        <h2 className="mb-3 text-lg font-medium">Historial de versiones</h2>
        <ul className="space-y-2">
          {versions.map((v) => (
            <li
              key={v.version}
              className="rounded-lg border border-neutral-800 p-3 text-sm"
            >
              <div className="flex items-center justify-between">
                <span className="font-medium">v{v.version}</span>
                <span className="text-xs text-neutral-500">
                  {new Date(v.created_at).toLocaleString("es")}
                </span>
              </div>
              {v.note && <p className="mt-1 text-neutral-400">{v.note}</p>}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
