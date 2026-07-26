"use client";

import { useEffect, useState } from "react";
import {
  api,
  type ProjectCostSummary,
  type UsageAggregate,
} from "@/lib/api";

function money(value: string | null | undefined) {
  if (value == null) return "Sin dato";
  return `$${Number(value).toFixed(4)}`;
}

function Metric({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-white/[0.07] bg-white/[0.025] p-3">
      <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-600">
        {label}
      </p>
      <p className="mt-1 text-lg font-semibold text-zinc-100">{value}</p>
      {hint && <p className="mt-1 text-[11px] text-zinc-500">{hint}</p>}
    </div>
  );
}

function Totals({ usage }: { usage: UsageAggregate }) {
  return (
    <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      <Metric label="Tokens" value={usage.total_tokens.toLocaleString("es-ES")} />
      <Metric
        label="Entrada / salida"
        value={`${usage.input_tokens.toLocaleString("es-ES")} / ${usage.output_tokens.toLocaleString("es-ES")}`}
      />
      <Metric label="Caracteres TTS" value={usage.input_characters.toLocaleString("es-ES")} />
      <Metric label="Imágenes" value={usage.image_count.toLocaleString("es-ES")} />
    </div>
  );
}

export default function UsagePanel({ projectId }: { projectId: string }) {
  const [summary, setSummary] = useState<ProjectCostSummary | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    const load = () =>
      api
        .getProjectCostSummary(projectId)
        .then((value) => {
          if (active) {
            setSummary(value);
            setFailed(false);
          }
        })
        .catch(() => {
          if (active) setFailed(true);
        });
    void load();
    const interval = window.setInterval(load, 15_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [projectId]);

  if (failed) {
    return (
      <section className="card mb-6 p-5">
        <h2 className="text-sm font-semibold text-zinc-200">Uso y costes</h2>
        <p className="mt-2 text-xs text-rose-300">
          No se pudo cargar la información de uso.
        </p>
      </section>
    );
  }

  if (!summary) {
    return (
      <section className="card mb-6 p-5">
        <p className="text-xs text-zinc-500">Cargando uso y costes…</p>
      </section>
    );
  }

  if (!summary.has_data || !summary.historical) {
    return (
      <section className="card mb-6 p-5">
        <h2 className="text-sm font-semibold text-zinc-200">Uso y costes</h2>
        <p className="mt-2 text-xs leading-relaxed text-zinc-500">
          Sin datos persistentes. Las ejecuciones anteriores a esta función no
          se muestran como coste cero.
        </p>
      </section>
    );
  }

  const actual = summary.cost_sources.find(
    (item) => item.key === "provider_actual",
  );
  const estimatedGroups = summary.cost_sources.filter((item) =>
    item.key.startsWith("estimated_"),
  );
  const estimated = estimatedGroups
    .reduce((total, item) => total + Number(item.cost_usd ?? 0), 0);

  return (
    <section className="card mb-6 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-zinc-200">Uso y costes</h2>
          <p className="mt-1 text-xs text-zinc-500">
            USD · histórico inmutable y coste atribuible a la selección actual
          </p>
        </div>
        <div className="flex gap-2 text-xs">
          <a
            href={`/api/projects/${projectId}/costs/export?format=csv`}
            className="btn-secondary btn-sm"
          >
            CSV
          </a>
          <a
            href={`/api/projects/${projectId}/costs/export?format=json`}
            className="btn-secondary btn-sm"
          >
            JSON
          </a>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <Metric
          label="Gasto histórico"
          value={money(summary.historical.cost_usd)}
          hint={`${summary.historical.calls} operaciones, incluidas versiones descartadas`}
        />
        <Metric
          label="Coste activo"
          value={money(summary.active?.cost_usd)}
          hint="Producción atribuible a los artefactos seleccionados"
        />
      </div>

      <Totals usage={summary.historical} />

      <div className="mt-4 flex flex-wrap gap-2 text-[11px]">
        <span className="badge-success">
          Real: {money(actual?.cost_usd)}
        </span>
        <span className="badge-neutral">
          Estimado: {money(estimatedGroups.length > 0 ? String(estimated) : null)}
        </span>
        {summary.historical.unknown_cost_records > 0 && (
          <span className="rounded-full border border-amber-400/25 bg-amber-500/10 px-2.5 py-1 text-amber-200">
            {summary.historical.unknown_cost_records} sin precio fiable
          </span>
        )}
      </div>

      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        className="mt-5 text-xs font-medium text-indigo-300 hover:text-indigo-200"
      >
        {expanded ? "Ocultar desglose" : "Ver desglose por agente"}
      </button>

      {expanded && (
        <div className="mt-3 space-y-2">
          {summary.agents.map((agent) => (
            <div
              key={agent.key}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/[0.07] px-3 py-2.5"
            >
              <div>
                <p className="text-sm font-medium text-zinc-300">{agent.key}</p>
                <p className="text-[11px] text-zinc-600">
                  {agent.calls} llamadas · {agent.total_tokens.toLocaleString("es-ES")} tokens
                  {agent.image_count > 0 ? ` · ${agent.image_count} imágenes` : ""}
                  {agent.input_characters > 0
                    ? ` · ${agent.input_characters.toLocaleString("es-ES")} caracteres`
                    : ""}
                </p>
              </div>
              <span className="text-sm font-semibold text-zinc-200">
                {money(agent.cost_usd)}
              </span>
            </div>
          ))}
          {summary.models.length > 0 && (
            <p className="pt-2 text-[11px] text-zinc-600">
              Modelos: {summary.models.join(", ")}
            </p>
          )}
          {summary.runs.length > 0 && (
            <div className="pt-3">
              <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-zinc-600">
                Por ejecución
              </p>
              <div className="space-y-1.5">
                {summary.runs.map((run) => (
                  <div
                    key={run.key}
                    className="flex items-center justify-between gap-3 text-[11px]"
                  >
                    <span className="truncate text-zinc-500">
                      {run.kind ?? "run"} · {run.key.slice(0, 8)}
                    </span>
                    <span className={run.has_data === false ? "text-zinc-600" : "text-zinc-300"}>
                      {run.has_data === false ? "Sin datos" : money(run.cost_usd)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {summary.last_updated && (
            <p className="text-[10px] text-zinc-700">
              Actualizado: {new Date(summary.last_updated).toLocaleString("es-ES")}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
