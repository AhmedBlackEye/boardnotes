"use client";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { ConnectedSidebar } from "@/components/Sidebar";
import { useSession } from "@/lib/session";

/** Signed-in frame: sidebar plus the page. Sends visitors without a session to the demo login. */
export default function AppLayout({ children }: { children: ReactNode }) {
  const { me, ready } = useSession();
  const router = useRouter();
  useEffect(() => {
    if (ready && !me) router.replace("/login");
  }, [ready, me, router]);
  if (!me) return <div className="min-h-screen bg-canvas" />;
  return (
    <div className="flex h-screen bg-canvas">
      <ConnectedSidebar />
      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">{children}</main>
    </div>
  );
}
