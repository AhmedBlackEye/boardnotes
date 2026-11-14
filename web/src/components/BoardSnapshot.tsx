import { assetUrl } from "@/lib/api";
import { cx } from "@/lib/cx";

/** A crop of the board from the clearest frame where this content appeared. Shows the image when there is one, else the read text. */
export function BoardSnapshot({
  caption,
  text,
  imageUrl,
  size = "large",
  className,
}: {
  caption?: string;
  text?: string;
  imageUrl?: string | null;
  size?: "small" | "large";
  className?: string;
}) {
  const img = assetUrl(imageUrl);
  return (
    <div className={cx("flex flex-col gap-1.5 rounded-md bg-board", size === "large" ? "p-4" : "p-2", className)}>
      {caption && <p className="text-[11px] font-bold uppercase leading-4 tracking-[0.08em] text-chalk-dim">{caption}</p>}
      {img ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={img} alt={caption ?? "Board snapshot"} className="w-full rounded-sm" />
      ) : (
        <p className={cx("font-chalk text-chalk", size === "large" ? "text-[22px] leading-[30px]" : "text-[11px] leading-4")}>{text}</p>
      )}
    </div>
  );
}
