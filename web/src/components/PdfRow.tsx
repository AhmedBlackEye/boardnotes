import type { ReactNode } from "react";

/** A PDF in the course notes list: red PDF tile, title, meta line, status pill and action. */
export function PdfRow({ title, meta, status, action }: { title: string; meta: string; status: ReactNode; action: ReactNode }) {
  return (
    <div className="flex items-center gap-4 border-t border-default px-4 py-3 first:border-t-0">
      <span className="flex size-10 shrink-0 items-center justify-center rounded-md bg-danger-subtle text-[11px] font-bold text-danger">PDF</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-semibold leading-[18px] text-primary">{title}</p>
        <p className="text-[12px] text-tertiary">{meta}</p>
      </div>
      {status}
      <div className="w-[110px] shrink-0 text-right">{action}</div>
    </div>
  );
}
