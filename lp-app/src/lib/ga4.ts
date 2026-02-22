/* eslint-disable @typescript-eslint/no-explicit-any */
export const GA_TRACKING_ID = process.env.NEXT_PUBLIC_GA_TRACKING_ID || "";

export function pageview(url: string) {
  if (typeof window === "undefined" || !GA_TRACKING_ID) return;
  (window as any).gtag?.("config", GA_TRACKING_ID, { page_path: url });
}

export function event(action: string, params: Record<string, string> = {}) {
  if (typeof window === "undefined" || !GA_TRACKING_ID) return;
  (window as any).gtag?.("event", action, params);
}
