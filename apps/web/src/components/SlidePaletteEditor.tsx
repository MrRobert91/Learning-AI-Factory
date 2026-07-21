"use client";

import type { PaletteOptions, SlidePalette } from "@/lib/api";

const FIELDS: { key: keyof SlidePalette; label: string }[] = [
  { key: "background", label: "Fondo" },
  { key: "text", label: "Texto" },
  { key: "headings", label: "Títulos" },
  { key: "primary", label: "Principal" },
  { key: "secondary", label: "Secundario" },
  { key: "code_background", label: "Código · fondo" },
  { key: "code_text", label: "Código · texto" },
  { key: "links", label: "Enlaces" },
];

function luminance(color: string): number {
  const value = color.replace("#", "");
  const channels = [0, 2, 4].map(
    (index) => parseInt(value.slice(index, index + 2), 16) / 255,
  );
  const linear = channels.map((channel) =>
    channel <= 0.04045
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function ratio(first: string, second: string): number {
  const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

export function paletteWarnings(palette: SlidePalette): string[] {
  const checks = [
    { label: "texto sobre fondo", ratio: ratio(palette.text, palette.background), minimum: 4.5 },
    { label: "títulos sobre fondo", ratio: ratio(palette.headings, palette.background), minimum: 3 },
    { label: "enlaces sobre fondo", ratio: ratio(palette.links, palette.background), minimum: 4.5 },
    {
      label: "texto de código",
      ratio: ratio(palette.code_text, palette.code_background),
      minimum: 4.5,
    },
  ];
  return checks
    .filter((check) => check.ratio < check.minimum)
    .map(
      (check) =>
        `${check.label}: ${check.ratio.toFixed(2)}:1 (mínimo ${check.minimum}:1)`,
    );
}

function matchingPreset(palette: SlidePalette, options: PaletteOptions): string {
  return (
    options.presets.find((preset) =>
      FIELDS.every(({ key }) => preset.colors[key] === palette[key]),
    )?.id ?? "custom"
  );
}

export default function SlidePaletteEditor({
  palette,
  options,
  onChange,
  disabled = false,
}: {
  palette: SlidePalette;
  options: PaletteOptions;
  onChange: (palette: SlidePalette) => void;
  disabled?: boolean;
}) {
  const warnings = paletteWarnings(palette);
  return (
    <div className="space-y-4">
      <div>
        <label className="label">Preset</label>
        <select
          value={matchingPreset(palette, options)}
          disabled={disabled}
          onChange={(event) => {
            const preset = options.presets.find((item) => item.id === event.target.value);
            if (preset) onChange({ ...preset.colors });
          }}
          className="input"
        >
          {options.presets.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.label}
            </option>
          ))}
          <option value="custom">Personalizada</option>
        </select>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {FIELDS.map(({ key, label }) => (
          <label key={key} className="text-xs text-zinc-400">
            <span className="mb-1.5 block">{label}</span>
            <span className="flex gap-2">
              <input
                type="color"
                value={palette[key]}
                disabled={disabled}
                onChange={(event) =>
                  onChange({ ...palette, [key]: event.target.value.toUpperCase() })
                }
                className="h-10 w-12 rounded border border-white/[0.12] bg-transparent p-1"
              />
              <input
                value={palette[key]}
                disabled={disabled}
                pattern="#[0-9A-Fa-f]{6}"
                onChange={(event) =>
                  onChange({ ...palette, [key]: event.target.value.toUpperCase() })
                }
                className="input font-mono text-xs"
              />
            </span>
          </label>
        ))}
      </div>
      <div
        className="rounded-lg border border-white/[0.1] p-4"
        style={{ background: palette.background, color: palette.text }}
      >
        <p className="text-lg font-semibold" style={{ color: palette.headings }}>
          Vista rápida de la paleta
        </p>
        <p className="mt-1 text-sm">
          Texto normal, <strong style={{ color: palette.primary }}>énfasis principal</strong> y{" "}
          <span style={{ color: palette.links }}>enlace de ejemplo</span>.
        </p>
        <code
          className="mt-3 block rounded px-3 py-2 text-xs"
          style={{ background: palette.code_background, color: palette.code_text }}
        >
          const curso = &quot;AI Learning Factory&quot;;
        </code>
      </div>
      {warnings.length > 0 && (
        <div className="rounded-lg border border-amber-400/30 bg-amber-400/[0.08] p-3 text-xs text-amber-200">
          <p className="mb-1 font-semibold">Advertencias WCAG</p>
          <ul className="list-disc space-y-1 pl-5">
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
