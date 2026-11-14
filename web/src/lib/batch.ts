export interface BatchResult {
  done: number;
  failed: number;
  /** Message of the first failure, for the UI. */
  firstError: string | null;
}

/**
 * Run `fn` for each id in turn and keep going past failures (for example a 409 when an earlier approval already
 * closed another fix for the same line). Returns how many worked and how many failed.
 */
export async function approveEach(ids: string[], fn: (id: string) => Promise<unknown>): Promise<BatchResult> {
  const result: BatchResult = { done: 0, failed: 0, firstError: null };
  for (const id of ids) {
    try {
      await fn(id);
      result.done += 1;
    } catch (e) {
      result.failed += 1;
      result.firstError ??= e instanceof Error && e.message ? e.message : "request failed";
    }
  }
  return result;
}
