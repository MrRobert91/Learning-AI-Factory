"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { BrandMark, ErrorBanner, IconFlask, Spinner } from "@/components/ui";

const PIPELINE = [
  "Ideación asistida",
  "Investigación",
  "Plan del curso",
  "Lecciones",
  "Slides",
  "Vídeo con voz",
  "Publicación",
];

export default function LoginPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.login(password);
      router.push("/");
      router.refresh();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "No se pudo iniciar sesión",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="card grid w-full max-w-4xl overflow-hidden !p-0 md:grid-cols-2">
        {/* Brand panel */}
        <div className="relative hidden flex-col justify-between overflow-hidden border-r-2 border-[#241d18] bg-[var(--rust)] p-10 text-[#fbf6ea] md:flex">
          <div className="relative flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-md border-2 border-[#241d18] bg-[#fbf6ea] text-[var(--rust)] shadow-[3px_3px_0_0_var(--shadow)]">
              <IconFlask size={22} />
            </span>
            <div>
              <p className="text-base font-extrabold tracking-tight text-[#fbf6ea]">
                RustyRoboz Labs
              </p>
              <p className="text-xs text-[#fbf6ea]/80">AI Learning Factory</p>
            </div>
          </div>
          <div className="relative">
            <p className="mb-5 text-lg font-bold leading-snug text-[#fbf6ea]">
              De una idea vaga a un curso completo publicado, con agentes
              especializados y tu aprobación en cada hito.
            </p>
            <ol className="space-y-2">
              {PIPELINE.map((step, i) => (
                <li key={step} className="flex items-center gap-3 text-sm font-medium text-[#fbf6ea]">
                  <span className="flex h-6 w-6 items-center justify-center rounded border-2 border-[#241d18] bg-[#fbf6ea] text-[11px] font-bold text-[var(--rust-deep)]">
                    {i + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        </div>

        {/* Form */}
        <div className="flex flex-col justify-center bg-[var(--paper-sheet)] p-8 sm:p-12">
          <div className="mb-8 flex items-center gap-3 md:hidden">
            <BrandMark size={36} />
            <div>
              <p className="text-base font-extrabold text-zinc-50">
                RustyRoboz Labs
              </p>
              <p className="text-xs text-zinc-400">AI Learning Factory</p>
            </div>
          </div>
          <h1 className="mb-1 text-xl font-semibold tracking-tight text-zinc-50">
            Bienvenido de nuevo
          </h1>
          <p className="mb-8 text-sm text-zinc-400">
            Introduce tu contraseña para acceder al estudio.
          </p>
          <form onSubmit={onSubmit} className="space-y-5">
            <div>
              <label htmlFor="password" className="label">
                Contraseña
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
                required
                placeholder="••••••••"
                className="input"
              />
            </div>
            <ErrorBanner>{error}</ErrorBanner>
            <button type="submit" disabled={loading} className="btn-primary w-full">
              {loading && <Spinner className="border-white/40 border-t-white" />}
              {loading ? "Entrando…" : "Entrar al estudio"}
            </button>
          </form>
          <p className="mt-7 text-center text-xs text-zinc-500">
            Al usar la aplicación, aceptas las{" "}
            <Link
              href="/terms"
              className="font-semibold text-[var(--rust-deep)] underline decoration-2 underline-offset-2 hover:text-[var(--rust)]"
            >
              condiciones del servicio
            </Link>{" "}
            y confirmas que has leído la{" "}
            <Link
              href="/privacy"
              className="font-semibold text-[var(--rust-deep)] underline decoration-2 underline-offset-2 hover:text-[var(--rust)]"
            >
              política de privacidad
            </Link>
            .
          </p>
        </div>
      </div>
    </main>
  );
}
