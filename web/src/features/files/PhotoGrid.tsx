import { formatDate } from "@/lib/dates";

export interface GridPhoto {
  id: string;
  caption: string | null;
  entry_date: string;
  url: string;
}

/** Site photos with their day and caption; each opens full size. */
export function PhotoGrid({ photos, label }: { photos: GridPhoto[]; label: string }) {
  return (
    <ul aria-label={label} className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {photos.map((p) => (
        <li key={p.id} className="grid gap-1">
          <a href={p.url} target="_blank" rel="noreferrer">
            <img
              src={p.url}
              alt={p.caption || `Site photo, ${formatDate(p.entry_date)}`}
              loading="lazy"
              className="bg-muted aspect-[4/3] w-full rounded-md object-cover"
            />
          </a>
          <span className="text-help text-muted-foreground">
            {formatDate(p.entry_date)}
            {p.caption ? ` · ${p.caption}` : ""}
          </span>
        </li>
      ))}
    </ul>
  );
}
