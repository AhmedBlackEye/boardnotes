import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import { cx } from "@/lib/cx";

type Common = { label?: string; hint?: ReactNode };
type InputProps = Common & { multiline?: false } & InputHTMLAttributes<HTMLInputElement>;
type AreaProps = Common & { multiline: true } & TextareaHTMLAttributes<HTMLTextAreaElement>;

const FIELD =
  "w-full rounded-md border border-default bg-surface px-3 py-2.5 text-[14px] leading-[22px] text-primary placeholder:text-tertiary " +
  "focus:border-accent focus:outline-none focus:shadow-[var(--focus-ring)] read-only:bg-subtle disabled:opacity-60";

/** Labelled text field. Pass `multiline` for a textarea. */
export function TextField(props: InputProps | AreaProps) {
  const control = props.multiline ? (
    <textarea rows={3} {...areaRest(props)} className={cx(FIELD, props.className)} />
  ) : (
    <input {...inputRest(props)} className={cx(FIELD, props.className)} />
  );
  return (
    <label className="flex flex-col gap-1.5">
      {props.label && <span className="text-[12px] font-semibold text-secondary">{props.label}</span>}
      {control}
      {props.hint && <span className="text-[12px] text-tertiary">{props.hint}</span>}
    </label>
  );
}

function inputRest(p: InputProps): InputHTMLAttributes<HTMLInputElement> {
  const { label: _l, hint: _h, multiline: _m, ...rest } = p;
  return rest;
}

function areaRest(p: AreaProps): TextareaHTMLAttributes<HTMLTextAreaElement> {
  const { label: _l, hint: _h, multiline: _m, ...rest } = p;
  return rest;
}
