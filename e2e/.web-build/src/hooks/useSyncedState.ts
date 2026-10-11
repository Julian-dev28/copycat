"use client";

import { useState } from "react";

/**
 * Local draft state that follows a server value. When `source` changes
 * (a save landed, another tab edited it), the draft resets to it.
 *
 * This is React's documented "adjust state while rendering" pattern
 * (react.dev/learn/you-might-not-need-an-effect). Syncing in a useEffect
 * renders once with the stale draft and then again, and the
 * react-hooks/set-state-in-effect rule rejects it.
 */
export function useSyncedState<T>(source: T): [T, (v: T) => void] {
  const [value, setValue] = useState(source);
  const [prev, setPrev] = useState(source);
  if (!Object.is(prev, source)) {
    setPrev(source);
    setValue(source);
  }
  return [value, setValue];
}
