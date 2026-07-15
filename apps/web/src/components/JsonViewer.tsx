"use client";

import type { ReactNode } from "react";

type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;
type JsonObject = { [key: string]: JsonValue };

function humanizeKey(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function valueSummary(value: JsonValue): string {
  if (Array.isArray(value)) {
    return `${value.length} elemento${value.length === 1 ? "" : "s"}`;
  }
  if (value && typeof value === "object") {
    const count = Object.keys(value).length;
    return `${count} campo${count === 1 ? "" : "s"}`;
  }
  return "";
}

function Primitive({
  value,
}: {
  value: Exclude<JsonValue, JsonValue[] | JsonObject>;
}) {
  if (value === null) {
    return <span className="italic text-zinc-500">Sin valor</span>;
  }
  if (typeof value === "boolean") {
    return (
      <span
        className={
          value
            ? "font-semibold text-emerald-600"
            : "font-semibold text-red-500"
        }
      >
        {value ? "S\u00ed" : "No"}
      </span>
    );
  }
  if (typeof value === "number") {
    return (
      <span className="font-mono font-semibold text-indigo-600">{value}</span>
    );
  }
  return (
    <span className="whitespace-pre-wrap leading-relaxed text-zinc-800">
      {value}
    </span>
  );
}

function JsonBranch({
  value,
  depth = 0,
}: {
  value: JsonValue;
  depth?: number;
}): ReactNode {
  if (value === null || typeof value !== "object") {
    return <Primitive value={value} />;
  }

  const entries: [string, JsonValue][] = Array.isArray(value)
    ? value.map((item, index) => [String(index + 1), item])
    : Object.entries(value);

  if (entries.length === 0) {
    return <span className="italic text-zinc-500">Vac&iacute;o</span>;
  }

  return (
    <div
      className={
        depth > 0
          ? "mt-2 space-y-2 border-l-2 border-zinc-200 pl-3"
          : "space-y-2"
      }
    >
      {entries.map(([key, child]) => {
        const expandable = child !== null && typeof child === "object";
        const label = Array.isArray(value)
          ? `Elemento ${key}`
          : humanizeKey(key);
        if (!expandable) {
          return (
            <div
              key={key}
              className="grid gap-1 rounded-md border border-zinc-200 bg-white/55 px-3 py-2 sm:grid-cols-[minmax(9rem,0.35fr)_1fr] sm:gap-4"
            >
              <span className="text-xs font-bold tracking-wide text-zinc-600">
                {label}
              </span>
              <Primitive
                value={
                  child as Exclude<JsonValue, JsonValue[] | JsonObject>
                }
              />
            </div>
          );
        }
        return (
          <details
            key={key}
            open={depth === 0}
            className="group rounded-md border-2 border-zinc-200 bg-white/60"
          >
            <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 marker:content-none">
              <span className="flex h-5 w-5 items-center justify-center rounded border border-zinc-300 text-xs font-bold text-zinc-400 transition-transform group-open:rotate-90">
                &rsaquo;
              </span>
              <span className="font-semibold text-[#241d18]">{label}</span>
              <span className="ml-auto text-xs text-zinc-500">
                {valueSummary(child)}
              </span>
            </summary>
            <div className="border-t border-zinc-200 px-3 py-3">
              <JsonBranch value={child} depth={depth + 1} />
            </div>
          </details>
        );
      })}
    </div>
  );
}

export default function JsonViewer({ source }: { source: string }) {
  let parsed: JsonValue;
  try {
    parsed = JSON.parse(source) as JsonValue;
  } catch {
    return (
      <pre className="overflow-x-auto whitespace-pre-wrap rounded-md border-2 border-zinc-300 bg-white/60 p-4 font-mono text-[13px] leading-relaxed text-zinc-800">
        {source}
      </pre>
    );
  }

  return (
    <div className="rounded-md border-2 border-zinc-300 bg-[#f6efdf] p-3 sm:p-4">
      <JsonBranch value={parsed} />
    </div>
  );
}
