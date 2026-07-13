"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import { BrandMark, ErrorBanner, Spinner } from "@/components/ui";

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
      <div className="grid w-full max-w-4xl overflow-hidden rounded-3xl border border-white/[0.08] bg-white/[0.02] shadow-[0_20px_70px_rgba(0,0,0,0.5)] md:grid-cols-2">
        {/* Brand panel */}
        <div className="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-indigo-600/25 via-violet-600/15 to-transparent p-10 md:flex">
          <div
            className="pointer-events-none absolute inset-0 opacity-40"
            style={{
              backgroundImage:
                "radial-gradient(circle at 20% 15%, rgba(129,140,248,0.35), transparent 45%), radial-gradient(circle at 85% 85%, rgba(167,139,250,0.25), transparent 45%)",
            }}
          />
          <div className="relative flex items-center gap-3">
            <BrandMark size={40} />
            <div>
              <p className="text-base font-semibold tracking-tight text-zinc-50">
                AI Learning Factory
              </p>
              <p className="text-xs text-zinc-400">Estudio de cursos con IA</p>
            </div>
          </div>
          <div className="relative">
            <p className="mb-5 text-lg font-medium leading-snug text-zinc-100">
              De una idea vaga a un curso completo publicado, con agentes
              especializados y tu aprobación en cada hito.
            </p>
            <ol className="space-y-2">
              {PIPELINE.map((step, i) => (
                <li key={step} className="flex items-center gap-3 text-sm text-zinc-300">
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-white/[0.08] text-[10px] font-semibold text-indigo-300">
                    {i + 1}
                  </span>
                  {step}
                </li>
              ))}
            </ol>
          </div>
        </div>

        {/* Form */}
        <div className="flex flex-col justify-center p-8 sm:p-12">
          <div className="mb-8 flex items-center gap-3 md:hidden">
            <BrandMark size={36} />
            <div>
              <p className="text-base font-semibold text-zinc-50">
                AI Learning Factory
              </p>
              <p className="text-xs text-zinc-400">Estudio de cursos con IA</p>
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
        </div>
      </div>
    </main>
  );
}
