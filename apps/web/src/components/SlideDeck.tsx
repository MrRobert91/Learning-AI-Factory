"use client";

export default function SlideDeck({
  artifactId,
  orientation = "horizontal",
}: {
  artifactId: string;
  orientation?: "horizontal" | "vertical";
}) {
  return (
    <div className="slide-deck">
      <iframe
        key={artifactId}
        src={`/api/artifacts/${artifactId}/render/html`}
        title="Vista previa exacta de las slides"
        className={`w-full rounded-md border-2 border-zinc-300 bg-white ${
          orientation === "vertical"
            ? "mx-auto aspect-[9/16] max-w-md"
            : "aspect-video"
        }`}
        allowFullScreen
      />
      <p className="mt-2 text-xs text-zinc-500">
        Esta vista usa el mismo HTML de Marp que genera los ficheros PDF y
        PPTX, sin aplicar estilos propios de la web.
      </p>
    </div>
  );
}
