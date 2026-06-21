/* Tiny stale-while-revalidate cache backed by localStorage.
 *
 * Board pages (Students DB, Refunds, …) re-fetch their whole dataset on every
 * visit, so you stare at a spinner even when the data barely changed. These
 * helpers let a page paint the LAST-loaded rows instantly on mount, then
 * refresh in the background and overwrite the cache. The spinner becomes a
 * quiet "refreshing" indicator instead of a blocking wall.
 *
 * Keep payloads modest — localStorage is ~5MB per origin and synchronous.
 * The slim board rows we cache are well within that.
 */
const PREFIX = "ayci.swr.";

export function readCache(key) {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return { data: parsed.data, at: parsed.at };
  } catch {
    return null;
  }
}

export function writeCache(key, data) {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify({ data, at: Date.now() }));
  } catch {
    /* quota exceeded or storage disabled — non-fatal, just skip caching */
  }
}
