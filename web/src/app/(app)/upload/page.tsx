"use client";
import { redirect } from "next/navigation";
import { TopBar } from "@/components/TopBar";
import { UploadPanel } from "@/components/UploadPanel";
import { useSession } from "@/lib/session";

export default function UploadPage() {
  const { me } = useSession();
  if (me && me.role !== "lecturer") redirect("/lectures");
  return (
    <>
      <TopBar crumb="Linear Algebra" title="Upload lecture" />
      <div className="flex flex-col gap-4 p-8">
        <UploadPanel />
        <p className="text-[13px] text-secondary">
          Uploads are sent in chunks. If your connection drops, choose the same file again and it carries on where it stopped.
        </p>
      </div>
    </>
  );
}
