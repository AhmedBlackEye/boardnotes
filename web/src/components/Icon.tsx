import type { SVGProps } from "react";

const PATHS = {
  lectures: "M4 5.5C4 4.7 4.7 4 5.5 4H11v14H5.5A1.5 1.5 0 0 0 4 19.5v-14ZM20 5.5c0-.8-.7-1.5-1.5-1.5H13v14h5.5a1.5 1.5 0 0 1 1.5 1.5v-14Z",
  notes: "M7 3h7l5 5v12a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Zm6 1v5h5M9 13h6M9 17h6",
  review: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm-3.5-9 2.5 2.5L16 9.5",
  upload: "M12 16V4m0 0L7 9m5-5 5 5M5 15v4h14v-4",
  close: "M6 6l12 12M18 6 6 18",
  check: "M5 12.5 10 17.5 19 7",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm9 3-4.5-4.5",
  eye: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Zm10 3a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z",
  up: "M12 7l6 9H6l6-9Z",
} as const;

export type IconName = keyof typeof PATHS;

/** Stroke icons on a 24px grid, drawn at 20px by default. They take their colour from the text colour. */
export function Icon({ name, size = 20, ...rest }: { name: IconName; size?: number } & Omit<SVGProps<SVGSVGElement>, "name">) {
  const filled = name === "up";
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke={filled ? "none" : "currentColor"}
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}

export function PlayIcon({ size = 10 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 10 10" fill="currentColor" aria-hidden="true">
      <path d="M1.5 0.8v8.4L8.8 5 1.5 0.8Z" />
    </svg>
  );
}
