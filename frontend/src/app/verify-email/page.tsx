"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { api } from "@/lib/api";

function Verify() {
  const token = useSearchParams().get("token");
  const [status, setStatus] = useState<"working" | "ok" | "error">("working");
  useEffect(() => {
    if (!token) return setStatus("error");
    api("/api/auth/verify-email", { method: "POST", json: { token } }).then(() => setStatus("ok"), () => setStatus("error"));
  }, [token]);
  return (
    <div className="flex min-h-screen items-center justify-center px-4 text-center">
      <div>
        <h1 className="font-serif text-2xl font-semibold">
          {status === "working" ? "Confirming…" : status === "ok" ? "Email confirmed" : "This link is invalid or has expired"}
        </h1>
        <Link href="/" className="mt-4 inline-block text-primary hover:underline">Go to your dashboard</Link>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <Verify />
    </Suspense>
  );
}
