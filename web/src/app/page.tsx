"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useSession } from "@/lib/session";

export default function Home() {
  const { me, ready } = useSession();
  const router = useRouter();
  useEffect(() => {
    if (ready) router.replace(me ? "/lectures" : "/login");
  }, [ready, me, router]);
  return <div className="min-h-screen bg-canvas" />;
}
