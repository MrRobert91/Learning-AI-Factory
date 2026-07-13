"use client";

import { type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import {
  BrandMark,
  IconBot,
  IconFolder,
  IconLightbulb,
  IconLogout,
  IconTrendingUp,
  IconWorkflow,
} from "@/components/ui";

const NAV = [
  {
    href: "/",
    label: "Proyectos",
    icon: IconFolder,
    match: (p: string) =>
      p === "/" || p.startsWith("/projects") || p.startsWith("/artifacts"),
  },
  {
    href: "/ideation",
    label: "Ideación",
    icon: IconLightbulb,
    match: (p: string) => p.startsWith("/ideation"),
  },
  {
    href: "/workflows",
    label: "Workflows",
    icon: IconWorkflow,
    match: (p: string) => p.startsWith("/workflows"),
  },
  {
    href: "/profiles",
    label: "Agentes",
    icon: IconBot,
    match: (p: string) => p.startsWith("/profiles"),
  },
  {
    href: "/improvements",
    label: "Mejora continua",
    icon: IconTrendingUp,
    match: (p: string) => p.startsWith("/improvements"),
  },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();

  if (pathname === "/login") return <>{children}</>;

  async function logout() {
    await api.logout().catch(() => {});
    router.push("/login");
  }

  const nav = NAV.map((item) => {
    const active = item.match(pathname);
    const Icon = item.icon;
    return (
      <Link
        key={item.href}
        href={item.href}
        className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
          active
            ? "bg-indigo-500/[0.12] text-indigo-200 shadow-[0_0_0_1px_rgba(129,140,248,0.25)_inset]"
            : "text-zinc-400 hover:bg-white/[0.05] hover:text-zinc-200"
        }`}
      >
        <Icon size={17} className={active ? "text-indigo-300" : "text-zinc-500"} />
        <span className="hidden lg:inline">{item.label}</span>
      </Link>
    );
  });

  return (
    <div className="flex min-h-screen">
      {/* Sidebar (desktop) */}
      <aside className="sticky top-0 hidden h-screen w-16 shrink-0 flex-col border-r border-white/[0.06] bg-black/20 px-3 py-5 backdrop-blur-sm sm:flex lg:w-60">
        <Link href="/" className="mb-8 flex items-center gap-3 px-1">
          <BrandMark />
          <span className="hidden min-w-0 lg:block">
            <span className="block truncate text-sm font-semibold tracking-tight text-zinc-50">
              AI Learning Factory
            </span>
            <span className="block text-[11px] text-zinc-500">
              Estudio de cursos con IA
            </span>
          </span>
        </Link>
        <nav className="flex flex-1 flex-col gap-1">{nav}</nav>
        <button
          onClick={logout}
          className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-zinc-500 transition-colors hover:bg-white/[0.05] hover:text-zinc-300"
        >
          <IconLogout size={17} />
          <span className="hidden lg:inline">Cerrar sesión</span>
        </button>
      </aside>

      {/* Mobile top bar */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-2 overflow-x-auto border-b border-white/[0.06] bg-[#0a0c10]/85 px-4 py-3 backdrop-blur-md sm:hidden">
          <BrandMark size={28} />
          <nav className="flex items-center gap-1">{nav}</nav>
          <button
            onClick={logout}
            className="ml-auto flex items-center rounded-lg p-2 text-zinc-500 hover:text-zinc-300"
            aria-label="Cerrar sesión"
          >
            <IconLogout size={17} />
          </button>
        </header>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
