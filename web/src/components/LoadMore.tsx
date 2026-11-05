import { Button } from "@/components/ui/button";

/** "Load more" under a list that comes in pages (an infinite query). */
export function LoadMore({
  query,
}: {
  query: { hasNextPage: boolean; isFetchingNextPage: boolean; fetchNextPage: () => unknown };
}) {
  if (!query.hasNextPage) return null;
  return (
    <div className="mt-4 flex justify-center">
      <Button
        variant="outline"
        disabled={query.isFetchingNextPage}
        onClick={() => void query.fetchNextPage()}
      >
        {query.isFetchingNextPage ? "Loading…" : "Load more"}
      </Button>
    </div>
  );
}
