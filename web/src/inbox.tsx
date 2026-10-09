import { createContext, ReactNode, useContext, useEffect } from "react";
import { api, Inbox } from "./api";
import { AsyncState, useAsync } from "./hooks";

const REFRESH_MS = 60_000;
const InboxContext = createContext<AsyncState<Inbox> | null>(null);

/** Shares one inbox fetch between the nav badge and the inbox page; refreshes every minute. */
export function InboxProvider({ children }: { children: ReactNode }) {
  const inbox = useAsync(() => api.inbox(), []);
  const { reload } = inbox;
  useEffect(() => {
    const t = setInterval(reload, REFRESH_MS);
    return () => clearInterval(t);
  }, [reload]);
  return <InboxContext.Provider value={inbox}>{children}</InboxContext.Provider>;
}

export function useInbox(): AsyncState<Inbox> {
  const ctx = useContext(InboxContext);
  if (!ctx) throw new Error("useInbox must be used inside InboxProvider");
  return ctx;
}
