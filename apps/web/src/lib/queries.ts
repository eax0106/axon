import { QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, session, unwrap } from "./api";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      // Retrying a 4xx or a missing provider only delays the message the user needs to see.
      retry: (count, error) =>
        !(error instanceof ApiError && (error.status < 500 || error.provider)) && count < 2,
    },
  },
});

/** Start a session with a fresh cache, so nothing from a previous user is ever shown. */
export function signIn(token: string): void {
  queryClient.clear();
  session.set(token);
}

export type Me = {
  user: { id: string; email: string; role: "owner" | "member"; staff: boolean; support_session: boolean };
  account: { id: string; name: string; owner_phone: string }; // "" until verified
};
export type Wallet = {
  balance: string;
  spend_cap_per_hour: string | null;
  low_balance_threshold: string;
  low: boolean;
};
export type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string;
  created_at: string;
  read: boolean;
};
type Notifications = { unread_count: number; items: Notification[] };
type CallRow = { id: string; status: string };

export const useMe = () =>
  useQuery({ queryKey: ["me"], queryFn: () => unwrap<Me>(api.GET("/accounts/me")) });

export const useWallet = () =>
  useQuery({
    queryKey: ["wallet"],
    queryFn: () => unwrap<Wallet>(api.GET("/wallet")),
    refetchInterval: 60_000,
  });

export const useNotifications = () =>
  useQuery({
    queryKey: ["notifications"],
    queryFn: () => unwrap<Notifications>(api.GET("/notifications", { params: { query: {} } })),
    refetchInterval: 30_000,
  });

const LIVE = new Set(["ringing", "in_progress"]);
// ponytail: no live-count endpoint exists, so count live rows among the newest 100 calls.
// Undercounts only if over 100 newer calls are queued behind a live one; add a status filter
// to GET /calls if that ever happens.
export const useLiveCalls = () =>
  useQuery({
    queryKey: ["calls", "live"],
    queryFn: async () => {
      const page = await unwrap<{ items: CallRow[] }>(
        api.GET("/calls", { params: { query: { limit: 100, include_test: true } } }),
      );
      return page.items.filter((c) => LIVE.has(c.status)).length;
    },
    refetchInterval: 10_000,
  });

/** Mark one notification read (or all, with id null); the bell updates before the API answers. */
export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string | null) =>
      unwrap(
        id
          ? api.POST("/notifications/{notification_id}/read", {
              params: { path: { notification_id: id } },
            })
          : api.POST("/notifications/read-all"),
      ),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ["notifications"] });
      const before = qc.getQueryData<Notifications>(["notifications"]);
      if (before) {
        // The list holds the newest 30 only, so the count is adjusted, not recounted.
        const wasUnread = before.items.some((n) => n.id === id && !n.read);
        qc.setQueryData<Notifications>(["notifications"], {
          items: before.items.map((n) => (id === null || n.id === id ? { ...n, read: true } : n)),
          unread_count: id === null ? 0 : before.unread_count - (wasUnread ? 1 : 0),
        });
      }
      return { before };
    },
    onError: (_e, _id, ctx) => ctx?.before && qc.setQueryData(["notifications"], ctx.before),
    onSettled: () => qc.invalidateQueries({ queryKey: ["notifications"] }),
  });
}
