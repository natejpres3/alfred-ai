"use client";

import { BookOpen, GraduationCap, LayoutDashboard, LogOut, Map, Moon, RotateCcw, Settings, Shield, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import useSWR from "swr";

import { Spinner } from "@/components/ui/primitives";
import { api } from "@/lib/api";
import type { Me } from "@/lib/types";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/roadmap", label: "Roadmap", icon: Map },
  { href: "/reviews", label: "Reviews", icon: RotateCcw },
  { href: "/settings", label: "Settings", icon: Settings },
];

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return <span className="h-9 w-9" />;
  const dark = resolvedTheme === "dark";
  return (
    <button
      aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={() => setTheme(dark ? "light" : "dark")}
      className="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
    >
      {dark ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}

export function useMe(requireOnboarded = true) {
  const router = useRouter();
  const pathname = usePathname();
  const { data, error, isLoading } = useSWR<Me>("/api/auth/me");
  useEffect(() => {
    if (data && requireOnboarded && !data.onboarded && pathname !== "/onboarding") router.replace("/onboarding");
  }, [data, requireOnboarded, pathname, router]);
  return { me: data, error, isLoading };
}

export function AppShell({ children, wide = false, requireOnboarded = true }: { children: React.ReactNode; wide?: boolean; requireOnboarded?: boolean }) {
  const pathname = usePathname();
  const router = useRouter();
  const { me, isLoading } = useMe(requireOnboarded);

  async function logout() {
    await api("/api/auth/logout", { method: "POST" });
    router.push("/login");
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-30 border-b border-border bg-background/90 backdrop-blur">
        <div className={cn("mx-auto flex h-14 items-center gap-4 px-4 sm:px-6", wide ? "max-w-[1400px]" : "max-w-6xl")}>
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <GraduationCap size={20} className="text-primary" />
            <span>AI Academy</span>
          </Link>
          <nav className="ml-4 hidden items-center gap-1 md:flex">
            {NAV.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground",
                  (href === "/" ? pathname === "/" : pathname.startsWith(href)) && "bg-muted text-foreground",
                )}
              >
                <Icon size={15} />
                {label}
              </Link>
            ))}
            {me?.is_admin && (
              <Link href="/admin" className={cn("inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted", pathname.startsWith("/admin") && "bg-muted text-foreground")}>
                <Shield size={15} /> Admin
              </Link>
            )}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            {isLoading ? <Spinner className="text-muted-foreground" /> : <span className="hidden text-sm text-muted-foreground sm:inline">{me?.display_name || me?.email}</span>}
            <ThemeToggle />
            <button onClick={logout} aria-label="Sign out" className="inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground">
              <LogOut size={16} />
            </button>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto border-t border-border px-4 py-1.5 md:hidden">
          {NAV.map(({ href, label, icon: Icon }) => (
            <Link key={href} href={href} className={cn("inline-flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1 text-sm text-muted-foreground", pathname === href && "bg-muted text-foreground")}>
              <Icon size={14} />
              {label}
            </Link>
          ))}
        </nav>
      </header>
      <main className={cn("mx-auto px-4 py-8 sm:px-6", wide ? "max-w-[1400px]" : "max-w-6xl")}>{children}</main>
    </div>
  );
}

export function PageTitle({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="mb-8">
      {eyebrow && <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">{eyebrow}</p>}
      <h1 className="font-serif text-3xl font-semibold tracking-tight">{title}</h1>
      {children && <div className="mt-2 max-w-3xl text-muted-foreground">{children}</div>}
    </div>
  );
}

export { BookOpen };
