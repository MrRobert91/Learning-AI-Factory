"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { api, type ImprovementProposal } from "@/lib/api";

const KIND_LABELS: Record<string, string> = {
  wiki: "Memoria del canal",
  agents_md: "agents.md",
};

function ProposalCard({
  proposal,
  onDecided,
}: {
  proposal: ImprovementProposal;
  onDecided: () => void;
}) {
  const [current, setCurrent] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showDiff, setShowDiff] = useState(false);

  async function loadCurrent() {
    if (current === null) {
      const data = await api.getImprovementCurrent(proposal.id);
      setCurrent(data.current);
    }
    setShowDiff((v) => !v);
  }

  async function decide(approve: boolean) {
    setBusy(true);
    try {
      if (approve) await api.approveImprovement(proposal.id);
      else await api.rejectImprovement(proposal.id);
      onDecided();
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="rounded-xl border border-neutral-800 p-4">
      <div className="mb-1 flex items-center justify-between">
        <span className="font-medium">{proposal.title}</span>
        <span className="rounded-full border border-neutral-700 px-2 py-0.5 text-xs text-neutral-400">
          {KIND_LABELS[proposal.kind]}
          {proposal.agent_type && ` · ${proposal.agent_type}`}
        </span>
      </div>
      <p className="mb-3 text-sm text-neutral-400">
        <span className="font-medium text-neutral-300">Evidencia:</span>{" "}
        {proposal.evidence}
      </p>
      <div className="mb-3 rounded-lg border border-emerald-900/50 bg-emerald-950/20 p-3">
        <p className="mb-1 text-xs uppercase tracking-wide text-emerald-400">
          Contenido propuesto
        </p>
        <pre className="whitespace-pre-wrap text-sm text-neutral-200">
          {proposal.proposed_content}
        </pre>
      </div>
      {showDiff && current !== null && (
        <div className="mb-3 rounded-lg border border-neutral-800 bg-neutral-900/50 p-3">
          <p className="mb-1 text-xs uppercase tracking-wide text-neutral-500">
            Contenido actual (se sustituiría)
          </p>
          <pre className="whitespace-pre-wrap text-sm text-neutral-400">
            {current || "(vacío)"}
          </pre>
        </div>
      )}
      <div className="flex gap-2">
        <button
          onClick={() => decide(true)}
          disabled={busy}
          className="rounded-lg bg-emerald-600 px-4 py-1.5 text-sm font-medium hover:bg-emerald-500 disabled:opacity-50"
        >
          Aprobar y aplicar
        </button>
        <button
          onClick={() => decide(false)}
          disabled={busy}
          className="rounded-lg border border-red-900 px-4 py-1.5 text-sm text-red-400 hover:bg-red-950 disabled:opacity-50"
        >
          Rechazar
        </button>
        <button
          onClick={loadCurrent}
          className="rounded-lg border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:bg-neutral-900"
        >
          {showDiff ? "Ocultar actual" : "Comparar con actual"}
        </button>
      </div>
    </li>
  );
}

export default function ImprovementsPage() {
  const [pending, setPending] = useState<ImprovementProposal[] | null>(null);
  const [reviewed, setReviewed] = useState<ImprovementProposal[]>([]);

  const load = useCallback(async () => {
    const [p, all] = await Promise.all([
      api.listImprovements("pending"),
      api.listImprovements("all"),
    ]);
    setPending(p);
    setReviewed(all.filter((x) => x.status !== "pending").slice(0, 20));
  }, []);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  return (
    <main className="mx-auto max-w-4xl p-6">
      <div className="mb-6">
        <Link href="/" className="text-sm text-indigo-400 hover:underline">
          ← Volver al panel
        </Link>
      </div>
      <h1 className="mb-1 text-2xl font-semibold">Mejora continua</h1>
      <p className="mb-8 text-sm text-neutral-400">
        El Analista estudia las métricas y comentarios de tus vídeos publicados y
        propone mejoras a la memoria del canal o a los <code>agents.md</code> de
        los agentes. Nada se aplica sin tu aprobación. Lanza un análisis desde la
        página de cada proyecto («📈 Analizar rendimiento»).
      </p>

      <h2 className="mb-3 text-lg font-medium">Propuestas pendientes</h2>
      {pending === null ? (
        <p className="text-neutral-400">Cargando…</p>
      ) : pending.length === 0 ? (
        <p className="mb-8 text-sm text-neutral-500">
          No hay propuestas pendientes.
        </p>
      ) : (
        <ul className="mb-8 space-y-3">
          {pending.map((p) => (
            <ProposalCard key={p.id} proposal={p} onDecided={load} />
          ))}
        </ul>
      )}

      {reviewed.length > 0 && (
        <details>
          <summary className="cursor-pointer text-sm text-neutral-400">
            Historial de propuestas revisadas ({reviewed.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {reviewed.map((p) => (
              <li
                key={p.id}
                className="flex items-center justify-between rounded-lg border border-neutral-800 p-3 text-sm"
              >
                <span>{p.title}</span>
                <span
                  className={
                    p.status === "approved" ? "text-emerald-400" : "text-red-400"
                  }
                >
                  {p.status === "approved" ? "Aprobada" : "Rechazada"}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </main>
  );
}
