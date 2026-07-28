"use client";

import { type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { api } from "@/lib/api";
import {
  BrandMark,
  IconBot,
  IconFileText,
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

  if (
    pathname === "/login" ||
    pathname === "/privacy" ||
    pathname === "/terms"
  ) {
    return <>{children}</>;
  }

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
        className={`flex items-center gap-3 rounded-md border-2 px-3 py-2 text-sm font-semibold transition-all ${
          active
            ? "border-[#241d18] bg-[var(--rust)] text-[#fbf6ea] shadow-[2px_2px_0_0_var(--shadow)]"
            : "border-transparent text-zinc-400 hover:border-[#241d18] hover:bg-[#f2e9d8] hover:text-zinc-100"
        }`}
      >
        <Icon size={17} className={active ? "text-[#fbf6ea]" : "text-zinc-500"} />
        <span className="hidden lg:inline">{item.label}</span>
      </Link>
    );
  });

  return (
    <div className="flex min-h-screen">
      {/* Sidebar (desktop) */}
      <aside className="sticky top-0 hidden h-screen w-16 shrink-0 flex-col border-r-2 border-[#241d18] bg-[var(--paper-sheet)] px-3 py-5 sm:flex lg:w-60">
        <Link href="/" className="mb-8 flex items-center gap-3 px-1">
          <BrandMark />
          <span className="hidden min-w-0 lg:block">
            <span className="block truncate text-sm font-extrabold tracking-tight text-zinc-50">
              RustyRoboz Labs
            </span>
            <span className="block text-[11px] font-medium text-zinc-500">
              AI Learning Factory
            </span>
          </span>
        </Link>
        <nav className="flex flex-1 flex-col gap-1.5">{nav}</nav>
        <Link
          href="/terms"
          className="mb-1 flex items-center gap-3 rounded-md border-2 border-transparent px-3 py-2 text-sm font-semibold text-zinc-500 transition-all hover:border-[#241d18] hover:bg-[#f2e9d8] hover:text-zinc-200"
        >
          <IconFileText size={17} />
          <span className="hidden lg:inline">Condiciones</span>
        </Link>
        <Link
          href="/privacy"
          className="mb-1 flex items-center gap-3 rounded-md border-2 border-transparent px-3 py-2 text-sm font-semibold text-zinc-500 transition-all hover:border-[#241d18] hover:bg-[#f2e9d8] hover:text-zinc-200"
        >
          <IconFileText size={17} />
          <span className="hidden lg:inline">Privacidad</span>
        </Link>
        <button
          onClick={logout}
          className="flex items-center gap-3 rounded-md border-2 border-transparent px-3 py-2 text-sm font-semibold text-zinc-500 transition-all hover:border-[#241d18] hover:bg-[#f2e9d8] hover:text-zinc-200"
        >
          <IconLogout size={17} />
          <span className="hidden lg:inline">Cerrar sesión</span>
        </button>
      </aside>

      {/* Mobile top bar */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center gap-2 overflow-x-auto border-b-2 border-[#241d18] bg-[var(--paper-sheet)] px-4 py-3 sm:hidden">
          <BrandMark size={28} />
          <nav className="flex items-center gap-1">{nav}</nav>
          <Link
            href="/privacy"
            className="ml-auto flex items-center rounded-lg p-2 text-zinc-500 hover:text-zinc-300"
            aria-label="Política de privacidad"
            title="Política de privacidad"
          >
            <IconFileText size={17} />
          </Link>
          <button
            onClick={logout}
            className="flex items-center rounded-lg p-2 text-zinc-500 hover:text-zinc-300"
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
