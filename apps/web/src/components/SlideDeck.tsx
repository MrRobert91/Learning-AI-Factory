"use client";

import { useMemo, useState } from "react";
import Markdown from "@/components/Markdown";
import { IconChevronLeft } from "@/components/ui";

interface Slide {
  body: string;
  notes: string;
}

/** Marp directive comments we never want to show as speaker notes. */
const DIRECTIVE = /^\s*_?[a-zA-Z][\w-]*\s*:/;

function parseDeck(markdown: string): Slide[] {
  let src = markdown.replace(/\r\n/g, "\n").trim();

  // Drop the leading YAML front-matter (--- ... ---) if present.
  if (src.startsWith("---")) {
    const end = src.indexOf("\n---", 3);
    if (end !== -1) {
      const after = src.indexOf("\n", end + 1);
      src = after !== -1 ? src.slice(after + 1) : "";
    }
  }

  const rawSlides = src
    .split(/^\s*---\s*$/m)
    .map((s) => s.trim())
    .filter((s) => s.length > 0);

  return rawSlides.map((raw) => {
    const notes: string[] = [];
    // Pull out HTML comments; treat non-directive ones as speaker notes.
    const body = raw
      .replace(/<!--([\s\S]*?)-->/g, (_all, inner: string) => {
        const text = inner.trim();
        if (text && !DIRECTIVE.test(text)) notes.push(text);
        return "";
      })
      .trim();
    return { body, notes: notes.join("\n\n") };
  });
}

export default function SlideDeck({ markdown }: { markdown: string }) {
  const slides = useMemo(() => parseDeck(markdown), [markdown]);
  const [index, setIndex] = useState(0);

  if (slides.length === 0) {
    return (
      <p className="text-sm text-zinc-500">
        No se han podido extraer slides de este documento.
      </p>
    );
  }

  const current = slides[Math.min(index, slides.length - 1)];
  const go = (i: number) => setIndex(Math.max(0, Math.min(slides.length - 1, i)));

  return (
    <div className="slide-deck">
      {/* Main slide surface (16:9), rendered from the Marp Markdown itself. */}
      <div className="slide-stage">
        <div className="slide-canvas">
          <Markdown className="slide-md">{current.body}</Markdown>
        </div>
        <span className="slide-page">
          {index + 1} / {slides.length}
        </span>
      </div>

      {/* Prev / next controls */}
      <div className="mt-3 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => go(index - 1)}
          disabled={index === 0}
          className="btn-secondary btn-sm"
        >
          <IconChevronLeft size={14} />
          Anterior
        </button>
        <div className="hidden flex-1 flex-wrap items-center justify-center gap-1.5 sm:flex">
          {slides.map((_, i) => (
            <button
              key={i}
              type="button"
              onClick={() => go(i)}
              aria-label={`Ir a la slide ${i + 1}`}
              className={`slide-dot ${i === index ? "slide-dot-active" : ""}`}
            />
          ))}
        </div>
        <button
          type="button"
          onClick={() => go(index + 1)}
          disabled={index === slides.length - 1}
          className="btn-secondary btn-sm"
        >
          Siguiente
          <span className="rotate-180">
            <IconChevronLeft size={14} />
          </span>
        </button>
      </div>

      {/* Speaker notes for this slide, rendered as Markdown. */}
      {current.notes && (
        <div className="slide-notes">
          <p className="slide-notes-label">Notas de esta slide</p>
          <Markdown className="text-[13px]">{current.notes}</Markdown>
        </div>
      )}
    </div>
  );
}
