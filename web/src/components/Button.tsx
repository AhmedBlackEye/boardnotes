import type { ButtonHTMLAttributes } from "react";
import { cx } from "@/lib/cx";

export type ButtonStyle = "primary" | "secondary" | "success" | "danger" | "ghost";

const STYLES: Record<ButtonStyle, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-hover",
  secondary: "bg-surface text-primary border border-default hover:bg-subtle",
  success: "bg-success text-on-accent hover:opacity-90",
  danger: "bg-danger text-on-accent hover:opacity-90",
  ghost: "bg-transparent text-secondary hover:bg-muted",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonStyle;
  /** Stretch to fill the row (panel actions). */
  block?: boolean;
}

/** Medium button from the Figma set. One primary action per view. */
export function Button({ variant = "primary", block, className, type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-md px-4 py-2 text-[13px] font-semibold leading-[18px] transition-colors",
        "focus-visible:outline-none focus-visible:shadow-[var(--focus-ring)] disabled:cursor-not-allowed disabled:opacity-50",
        STYLES[variant],
        block && "w-full",
        className,
      )}
      {...rest}
    />
  );
}
