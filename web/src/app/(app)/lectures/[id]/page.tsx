"use client";
import { redirect, useParams } from "next/navigation";
import { Suspense } from "react";
import { LectureNotes } from "@/components/notes/LectureNotes";
import { TopBar } from "@/components/TopBar";
import { api } from "@/lib/client";
import { useAsync } from "@/lib/hooks";
import { useSession } from "@/lib/session";

function Notes({ id }: { id: string }) {
  const { me, role, viewAsStudent } = useSession();
  const lecture = useAsync(() => api.getLecture(id), [id]);
  if (lecture.error) {
    return (
      <>
        <TopBar crumb="Lectures" title="Lecture" />
        <p className="p-8 text-[14px] text-danger">{lecture.error}</p>
      </>
    );
  }
  const d = lecture.data;
  if (!d) {
    return (
      <>
        <TopBar crumb="Lectures" title="Loading…" />
        <p className="p-8 text-[14px] text-secondary">Loading notes…</p>
      </>
    );
  }
  if (d.summary.status === "processing" || d.summary.status === "uploading") {
    if (me?.role === "lecturer") redirect(`/lectures/${id}/processing`);
    return (
      <>
        <TopBar crumb="Lectures" title={d.summary.title} />
        <p className="p-8 text-[14px] text-secondary">Notes are still being written. Check back soon.</p>
      </>
    );
  }
  return <LectureNotes lecture={d} mode={role} preview={me?.role === "lecturer" && viewAsStudent} onChanged={lecture.reload} />;
}

export default function LecturePage() {
  const { id } = useParams<{ id: string }>();
  return (
    <Suspense fallback={null}>
      <Notes id={id} />
    </Suspense>
  );
}
