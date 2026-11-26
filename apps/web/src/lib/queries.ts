import { QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, api, session, unwrap } from "./api";
import type { CallRow } from "./data";

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
  // second_factor: this session was signed in with the staff second factor (the console needs it).
  // two_factor: sign-in asks this user for an authenticator code.
  user: { id: string; email: string; role: "owner" | "member"; staff: boolean; second_factor: boolean; two_factor: boolean; support_session: boolean };
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

/** Calls ringing or in progress right now, newest first. */
export const useLiveCalls = () =>
  useQuery({
    queryKey: ["calls", "live"],
    queryFn: async () => {
      const page = await unwrap<{ total: number; items: CallRow[] }>(
        api.GET("/calls", { params: { query: { live: true, include_test: true, limit: 20 } } }),
      );
      return page;
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
