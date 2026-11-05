import { BRAND } from "@/brand";
import { cn } from "@/lib/utils";

/**
 * The product's mark and name (D.13): a roof over ledger lines, in the brand
 * colour (or white on the brand colour). The name is a placeholder (brand.ts).
 */
export function BrandMark({
  inverted = false,
  className,
}: {
  inverted?: boolean;
  className?: string;
}) {
  return (
    <span className={cn("flex items-center gap-2 font-semibold", className)}>
      <svg viewBox="0 0 32 32" className="size-7 shrink-0" aria-hidden>
        <rect
          width="32"
          height="32"
          rx="8"
          className={inverted ? "fill-primary-foreground" : "fill-primary"}
        />
        <g
          fill="none"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={inverted ? "stroke-primary" : "stroke-primary-foreground"}
        >
          <path d="M7 14.5 16 7l9 7.5" />
          <path d="M11 18h10M11 22.5h10" />
        </g>
      </svg>
      {BRAND.name}
    </span>
  );
}
