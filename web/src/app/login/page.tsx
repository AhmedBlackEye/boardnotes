"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Avatar } from "@/components/Avatar";
import { API_MODE } from "@/lib/api";
import { DEMO_USERS, useSession } from "@/lib/session";

/** Demo login: pick one of the seeded users. There is no password; real university login is out of scope. */
export default function LoginPage() {
  const { login } = useSession();
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function pick(id: string) {
    setBusy(id);
    setError(null);
    try {
      await login(id);
      router.replace("/lectures");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not sign in");
      setBusy(null);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-6">
      <div className="flex w-full max-w-[440px] flex-col gap-6 rounded-xl border border-default bg-surface p-8 shadow-panel">
        <div className="flex items-center gap-2.5">
          <span className="flex size-[30px] items-center justify-center rounded-md bg-accent font-chalk text-[18px] font-bold text-on-accent">B</span>
          <span className="font-display text-[20px] font-bold text-primary">BoardNotes</span>
        </div>
        <div>
          <h1 className="font-display text-[22px] font-medium leading-7 text-primary">Choose a demo user</h1>
          <p className="text-[13px] text-secondary">
            Lecture videos turned into cited notes. {API_MODE === "mock" ? "Running with built-in sample data." : "Connected to the API."}
          </p>
        </div>
        <ul className="flex flex-col gap-2">
          {DEMO_USERS.map((u) => (
            <li key={u.id}>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => pick(u.id)}
                className="flex w-full items-center gap-3 rounded-lg border border-default bg-surface p-3 text-left hover:bg-subtle disabled:opacity-60"
              >
                <Avatar initials={u.name.split(" ").map((p) => p[0]).join("")} tone={u.role} />
                <span className="flex-1">
                  <span className="block text-[14px] font-semibold text-primary">{u.name}</span>
                  <span className="block text-[12px] text-tertiary">
                    <span className="capitalize">{u.role}</span> · {u.blurb}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
        {error && <p className="text-[13px] text-danger">{error}</p>}
      </div>
    </div>
  );
}
