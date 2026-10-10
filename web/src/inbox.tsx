import { createContext, ReactNode, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, Inbox, InboxItem } from "./api";
import { AsyncState, useAsync } from "./hooks";

const REFRESH_MS = 60_000;
const NOTIFY_KEY = "gitshield-desktop-notify";
const NOTIFY_KINDS = new Set(["approve", "failed"]);

interface InboxContextValue extends AsyncState<Inbox> {
  desktopNotify: boolean;
  setDesktopNotify: (on: boolean) => Promise<void>;
}

const InboxContext = createContext<InboxContextValue | null>(null);

const keyOf = (i: InboxItem) => `${i.kind}:${i.repo}#${i.pr_number}:${i.review_id ?? ""}`;

function readPref(): boolean {
  try {
    return localStorage.getItem(NOTIFY_KEY) === "1" && "Notification" in window && Notification.permission === "granted";
  } catch {
    return false;
  }
}

/** Shares one inbox fetch between the nav badge and the inbox page; refreshes every minute
 *  and raises a desktop notification for newly ready / failed reviews when enabled. */
export function InboxProvider({ children }: { children: ReactNode }) {
  const inbox = useAsync(() => api.inbox(), []);
  const { reload, data } = inbox;
  const [desktopNotify, setPref] = useState(readPref);
  const seen = useRef<Set<string> | null>(null);

  // Each refresh queries GitHub for every active repo, so skip it while the tab is hidden
  // (saves API rate limit) and catch up as soon as the user comes back.
  const lastFetch = useRef(Date.now());
  useEffect(() => {
    const refresh = () => {
      lastFetch.current = Date.now();
      reload();
    };
    const t = setInterval(() => {
      if (!document.hidden) refresh();
    }, REFRESH_MS);
    const onVisible = () => {
      if (!document.hidden && Date.now() - lastFetch.current >= REFRESH_MS) refresh();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(t);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [reload]);

  useEffect(() => {
    if (!data) return;
    const relevant = data.items.filter((i) => NOTIFY_KINDS.has(i.kind));
    const keys = new Set(relevant.map(keyOf));
    // The first load only establishes the baseline; notify about what appears afterwards.
    if (seen.current && desktopNotify) {
      for (const item of relevant.filter((i) => !seen.current!.has(keyOf(i)))) {
        const n = new Notification(item.kind === "failed" ? "İnceleme başarısız" : "Review onayını bekliyor", {
          body: `${item.repo} #${item.pr_number} — ${item.title}`,
          tag: keyOf(item),
        });
        n.onclick = () => {
          window.focus();
          window.location.assign(`/r/${item.repo}/pull/${item.pr_number}`);
        };
      }
    }
    seen.current = keys;
  }, [data, desktopNotify]);

  const setDesktopNotify = useCallback(async (on: boolean) => {
    if (on) {
      if (!("Notification" in window)) throw new Error("Bu tarayıcı masaüstü bildirimlerini desteklemiyor.");
      const permission = Notification.permission === "granted" ? "granted" : await Notification.requestPermission();
      if (permission !== "granted") throw new Error("Bildirim izni verilmedi; tarayıcı ayarlarından açabilirsin.");
    }
    try {
      localStorage.setItem(NOTIFY_KEY, on ? "1" : "0");
    } catch {
      /* storage unavailable: preference lasts for this session only */
    }
    setPref(on);
  }, []);

  return (
    <InboxContext.Provider value={{ ...inbox, desktopNotify, setDesktopNotify }}>
      {children}
    </InboxContext.Provider>
  );
}

export function useInbox(): InboxContextValue {
  const ctx = useContext(InboxContext);
  if (!ctx) throw new Error("useInbox must be used inside InboxProvider");
  return ctx;
}
