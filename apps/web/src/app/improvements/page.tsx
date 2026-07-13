"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type ImprovementProposal } from "@/lib/api";
import {
  EmptyState,
  IconCheck,
  IconTrendingUp,
  IconX,
  LoadingScreen,
  PageHeader,
} from "@/components/ui";

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
    <li className="card animate-in p-5">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-semibold text-zinc-100">
          {proposal.title}
        </span>
        <span className="badge-neutral shrink-0">
          {KIND_LABELS[proposal.kind]}
          {proposal.agent_type && ` · ${proposal.agent_type}`}
        </span>
      </div>
      <p className="mb-4 text-sm leading-relaxed text-zinc-400">
        <span className="font-medium text-zinc-300">Evidencia:</span>{" "}
        {proposal.evidence}
      </p>
      <div className="mb-3 rounded-xl border border-emerald-400/20 bg-emerald-500/[0.05] p-4">
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-emerald-400">
          Contenido propuesto
        </p>
        <pre className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-200">
          {proposal.proposed_content}
        </pre>
      </div>
      {showDiff && current !== null && (
        <div className="animate-in mb-3 rounded-xl border border-white/[0.07] bg-white/[0.02] p-4">
          <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
            Contenido actual (se sustituiría)
          </p>
          <pre className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-400">
            {current || "(vacío)"}
          </pre>
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => decide(true)}
          disabled={busy}
          className="btn-success btn-sm"
        >
          <IconCheck size={13} />
          Aprobar y aplicar
        </button>
        <button
          onClick={() => decide(false)}
          disabled={busy}
          className="btn-danger btn-sm"
        >
          <IconX size={13} />
          Rechazar
        </button>
        <button onClick={loadCurrent} className="btn-secondary btn-sm">
          {showDiff ? "Ocultar actual" : "Comparar con actual"}
        </button>
      </div>
    </li>
  );
}

export default function ImprovementsPage() {
  const [pending, setPending] = useState<ImprovementProposal[] | null>(null);
  const [reviewed, setReviewed] = useState<ImprovementProposal[]>([]);
  const [showReviewed, setShowReviewed] = useState(false);

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
    <div className="mx-auto max-w-4xl px-6 py-8">
      <PageHeader
        title="Mejora continua"
        description={
          <>
            El Analista estudia las métricas y comentarios de tus vídeos
            publicados y propone mejoras a la memoria del canal o a los{" "}
            <code>agents.md</code> de los agentes. Nada se aplica sin tu
            aprobación. Lanza un análisis desde la página de cada proyecto
            («Analizar rendimiento»).
          </>
        }
      />

      <h2 className="mb-3 text-base font-semibold tracking-tight text-zinc-100">
        Propuestas pendientes
      </h2>
      {pending === null ? (
        <LoadingScreen label="Cargando propuestas…" />
      ) : pending.length === 0 ? (
        <EmptyState
          icon={<IconTrendingUp size={22} />}
          title="No hay propuestas pendientes"
          description="Cuando el Analista encuentre patrones en las métricas de tus vídeos, sus propuestas aparecerán aquí para que las revises."
        />
      ) : (
        <ul className="mb-8 space-y-3">
          {pending.map((p) => (
            <ProposalCard key={p.id} proposal={p} onDecided={load} />
          ))}
        </ul>
      )}

      {reviewed.length > 0 && (
        <div className="mt-8">
          <button
            onClick={() => setShowReviewed((v) => !v)}
            className="btn-ghost btn-sm -ml-2"
          >
            {showReviewed
              ? "Ocultar historial"
              : `Historial de propuestas revisadas (${reviewed.length})`}
          </button>
          {showReviewed && (
            <ul className="animate-in mt-2 space-y-1.5">
              {reviewed.map((p) => (
                <li
                  key={p.id}
                  className="card flex items-center justify-between gap-3 px-4 py-2.5 text-sm"
                >
                  <span className="min-w-0 truncate text-zinc-300">
                    {p.title}
                  </span>
                  <span
                    className={
                      p.status === "approved" ? "badge-success" : "badge-danger"
                    }
                  >
                    {p.status === "approved" ? "Aprobada" : "Rechazada"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
