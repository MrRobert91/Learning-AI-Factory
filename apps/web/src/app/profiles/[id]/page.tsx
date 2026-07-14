"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { api, type AgentProfile, type ProfileVersion } from "@/lib/api";
import {
  ErrorBanner,
  IconChevronLeft,
  IconStar,
  LoadingScreen,
} from "@/components/ui";

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
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  // Only the fields that actually changed are sent, so saving never creates
  // spurious versions nor overwrites config the user didn't touch.
  function buildPatch() {
    if (!profile) return null;
    const patch: {
      name?: string;
      soul_md?: string;
      agents_md?: string;
      model?: string;
      note?: string;
    } = {};
    if (name !== profile.name) patch.name = name;
    if (soul !== profile.soul_md) patch.soul_md = soul;
    if (agentsMd !== profile.agents_md) patch.agents_md = agentsMd;
    // An empty string clears the model override (back to the system default).
    if (model.trim() !== (profile.model ?? "")) patch.model = model.trim();
    return patch;
  }

  const patch = buildPatch();
  const dirty = patch !== null && Object.keys(patch).length > 0;
  const contentChanged =
    patch !== null &&
    (patch.soul_md !== undefined ||
      patch.agents_md !== undefined ||
      patch.model !== undefined);

  async function save() {
    if (!patch || !dirty) return;
    setSaving(true);
    setError(null);
    try {
      await api.updateProfile(id, { ...patch, note });
      setNote("");
      await load();
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error al guardar");
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
    return <LoadingScreen label="Cargando perfil…" />;
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <Link
          href="/profiles"
          className="inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-zinc-300"
        >
          <IconChevronLeft size={15} />
          Agentes y perfiles
        </Link>
        <div className="flex items-center gap-2">
          {!profile.is_default && (
            <>
              <button onClick={makeDefault} className="btn-secondary btn-sm">
                <IconStar size={13} />
                Hacer por defecto
              </button>
              <button onClick={remove} className="btn-danger btn-sm">
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
          className="flex-1 rounded-lg border border-transparent bg-transparent text-2xl font-semibold tracking-tight text-zinc-50 outline-none focus:border-white/[0.15]"
        />
        <span className="badge-neutral shrink-0">v{profile.version}</span>
      </div>
      <p className="mb-6 text-sm text-zinc-500">
        Agente: <span className="text-zinc-400">{profile.agent_type}</span>
        {profile.is_default && (
          <span className="badge-info ml-2 align-middle">
            <IconStar size={10} />
            perfil por defecto
          </span>
        )}
      </p>

      <div className="space-y-5">
        <div className="card p-5">
          <label className="label">soul.md — personalidad y criterio</label>
          <p className="mb-2 text-xs text-zinc-500">
            Cómo piensa y qué prioriza el agente: tono, gustos, criterio
            editorial.
          </p>
          <textarea
            value={soul}
            onChange={(e) => setSoul(e.target.value)}
            rows={8}
            className="input resize-y font-mono text-[13px]"
          />
        </div>
        <div className="card p-5">
          <label className="label">agents.md — instrucciones operativas</label>
          <p className="mb-2 text-xs text-zinc-500">
            Reglas concretas de trabajo: formato, longitudes, restricciones,
            checklist.
          </p>
          <textarea
            value={agentsMd}
            onChange={(e) => setAgentsMd(e.target.value)}
            rows={8}
            className="input resize-y font-mono text-[13px]"
          />
        </div>
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <label className="label">Modelo (slug de OpenRouter)</label>
            <input
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="vacío = modelo por defecto del sistema"
              className="input font-mono text-[13px]"
            />
            <p className="mt-1.5 text-xs text-zinc-500">
              Deja el campo vacío para volver al modelo por defecto.
            </p>
          </div>
          <div>
            <label className="label">Nota de esta versión</label>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="qué has cambiado y por qué"
              className="input"
            />
          </div>
        </div>
        <ErrorBanner>{error}</ErrorBanner>
        <div className="flex items-center gap-3">
          <button onClick={save} disabled={saving || !dirty} className="btn-primary">
            {saving
              ? "Guardando…"
              : contentChanged
                ? "Guardar (crea nueva versión)"
                : "Guardar"}
          </button>
          {dirty && !saving && (
            <span className="badge-warning">Cambios sin guardar</span>
          )}
          {saved && <span className="badge-success">Guardado ✓</span>}
        </div>
      </div>

      <section className="mt-12">
        <h2 className="mb-3 text-base font-semibold tracking-tight text-zinc-100">
          Historial de versiones
        </h2>
        <ul className="space-y-1.5">
          {versions.map((v) => (
            <li key={v.version} className="card px-4 py-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="font-semibold text-zinc-200">v{v.version}</span>
                <span className="text-xs text-zinc-500">
                  {new Date(v.created_at).toLocaleString("es")}
                </span>
              </div>
              {v.note && (
                <p className="mt-1 text-sm leading-relaxed text-zinc-400">
                  {v.note}
                </p>
              )}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
