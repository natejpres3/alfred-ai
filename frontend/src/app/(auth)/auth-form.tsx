"use client";

import { GraduationCap } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Button, Input, Label, Spinner } from "@/components/ui/primitives";
import { api, ApiError } from "@/lib/api";
import type { Me } from "@/lib/types";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const router = useRouter();
  const params = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const me = await api<Me>(`/api/auth/${mode}`, {
        method: "POST",
        json: mode === "login" ? { email, password } : { email, password, display_name: name },
      });
      router.push(!me.onboarded ? "/onboarding" : params.get("next") || "/");
    } catch (err) {
      const detail = err instanceof ApiError ? err.detail : null;
      setError(Array.isArray(detail) ? "Password must be at least 10 characters and the email must be valid." : err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <GraduationCap className="mx-auto mb-3 text-primary" size={32} />
          <h1 className="font-serif text-2xl font-semibold">{mode === "login" ? "Welcome back" : "Start AI Academy"}</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {mode === "login" ? "Continue where you left off." : "Mastery-based AI education, from first principles."}
          </p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-lg border border-border bg-card p-6">
          {mode === "register" && (
            <div className="space-y-1.5">
              <Label htmlFor="name">Name</Label>
              <Input id="name" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" />
            </div>
          )}
          <div className="space-y-1.5">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              required
              minLength={mode === "register" ? 10 : undefined}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
            />
          </div>
          {error && <p className="text-sm text-danger">{error}</p>}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy && <Spinner />} {mode === "login" ? "Sign in" : "Create account"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          {mode === "login" ? (
            <>No account? <Link className="text-primary underline-offset-4 hover:underline" href="/register">Create one</Link></>
          ) : (
            <>Already registered? <Link className="text-primary underline-offset-4 hover:underline" href="/login">Sign in</Link></>
          )}
        </p>
      </div>
    </div>
  );
}
