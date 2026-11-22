export interface PollOptions {
  intervalMs?: number;
  limitMs?: number;
  isVisible?: () => boolean;
  now?: () => number;
  /** Called once if `limitMs` passes before `isDone`. */
  onGiveUp?: () => void;
}

/**
 * Asks `fetch` every `intervalMs` until `isDone(answer)`, `limitMs` has passed since the
 * start, or `stop()` is called. Skips a tick while the tab is hidden. Answers that arrive
 * after stop() are dropped; failed asks are retried on the next tick. Returns stop().
 */
export function pollUntil<T>(
  fetch: () => Promise<T>,
  onUpdate: (answer: T) => void,
  isDone: (answer: T) => boolean,
  {
    intervalMs = 1500,
    limitMs = 60_000,
    isVisible = () => document.visibilityState === "visible",
    now = () => Date.now(),
    onGiveUp = () => undefined,
  }: PollOptions = {},
): () => void {
  const startedAt = now();
  let stopped = false;
  const stop = () => {
    stopped = true;
    clearInterval(timer);
  };
  const timer = setInterval(() => {
    if (now() - startedAt > limitMs) {
      stop();
      onGiveUp();
      return;
    }
    if (!isVisible()) return;
    fetch()
      .then((answer) => {
        if (stopped) return;
        onUpdate(answer);
        if (isDone(answer)) stop();
      })
      .catch(() => undefined);
  }, intervalMs);
  return stop;
}
