"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { Me } from "@/contracts/Me";
import { api } from "@/lib/client";

export type Role = Me["role"];

interface SessionValue {
  me: Me | null;
  ready: boolean;
  /** Lecturer previewing the student experience. Client state only: nothing is saved while it is on. */
  viewAsStudent: boolean;
  setViewAsStudent: (on: boolean) => void;
  /** Role the pages render for: a lecturer viewing as student sees the student UI. */
  role: Role;
  login: (userId: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<SessionValue | null>(null);

export const DEMO_USERS = [
  { id: "u_lecturer", name: "Dr. Rivera", role: "lecturer", blurb: "Review fixes, approve notes, upload lectures" },
  { id: "u_sam", name: "Sam Patel", role: "student", blurb: "Read notes, suggest fixes, ask the lecture" },
  { id: "u_riya", name: "Riya Kapoor", role: "student", blurb: "Student with an upvoted fix" },
  { id: "u_tom", name: "Tom Wells", role: "student", blurb: "Student" },
] as const;

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  const [viewAsStudent, setViewAsStudent] = useState(false);

  useEffect(() => {
    let live = true;
    api
      .me()
      .then((m) => live && setMe(m))
      .catch(() => undefined)
      .finally(() => live && setReady(true));
    return () => {
      live = false;
    };
  }, []);

  const login = useCallback(async (userId: string) => {
    setMe(await api.login(userId));
    setViewAsStudent(false);
  }, []);
  const logout = useCallback(async () => {
    await api.logout();
    setMe(null);
    setViewAsStudent(false);
  }, []);

  const value = useMemo<SessionValue>(
    () => ({
      me,
      ready,
      viewAsStudent,
      setViewAsStudent,
      role: me?.role === "lecturer" && !viewAsStudent ? "lecturer" : "student",
      login,
      logout,
    }),
    [me, ready, viewAsStudent, login, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): SessionValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession outside SessionProvider");
  return v;
}
