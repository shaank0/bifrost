/**
 * Failure alerts API service
 *
 * Unattended workflows that failed after their last retry, and integrations
 * that need reconnecting. Platform admin only. The server pushes an
 * `alerts_changed` message on the "alerts" WebSocket channel whenever an
 * alert opens, changes or resolves; `useAlertsLiveUpdates` turns that into a
 * refetch, so nothing polls.
 */

import { useEffect } from "react";
import { type QueryClient, useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api-client";
import type { components } from "@/lib/v1";
import { webSocketService } from "@/services/websocket";

export type Alert = components["schemas"]["AlertPublic"];
export type AlertList = components["schemas"]["AlertListResponse"];
export type AlertCount = components["schemas"]["AlertCountResponse"];
export type AlertEmailSettings = components["schemas"]["AlertEmailSettingsPublic"];
export type AlertEmailSettingsRequest =
	components["schemas"]["AlertEmailSettingsRequest"];
export type AlertView = "unresolved" | "open" | "acknowledged" | "resolved";

const ALERTS_CHANNEL = "alerts";
const LIST_KEY = ["get", "/api/alerts"] as const;
const COUNT_KEY = ["get", "/api/alerts/count"] as const;

function invalidateAlerts(queryClient: QueryClient) {
	queryClient.invalidateQueries({ queryKey: LIST_KEY });
	queryClient.invalidateQueries({ queryKey: COUNT_KEY });
}

export function useAlertCount(enabled = true) {
	return $api.useQuery("get", "/api/alerts/count", {}, { enabled });
}

export function useAlerts(view: AlertView) {
	return $api.useQuery("get", "/api/alerts", {
		params: { query: { view, limit: 200 } },
	});
}

export function useAcknowledgeAlert() {
	const queryClient = useQueryClient();
	return $api.useMutation("post", "/api/alerts/{alert_id}/acknowledge", {
		onSuccess: () => invalidateAlerts(queryClient),
	});
}

export function useResolveAlert() {
	const queryClient = useQueryClient();
	return $api.useMutation("post", "/api/alerts/{alert_id}/resolve", {
		onSuccess: () => invalidateAlerts(queryClient),
	});
}

/** Refetch alert lists and counts whenever the server says an alert changed. */
export function useAlertsLiveUpdates(enabled: boolean) {
	const queryClient = useQueryClient();
	useEffect(() => {
		if (!enabled) return;
		let unsubscribe: (() => void) | null = null;
		let active = true;
		webSocketService
			.connect([ALERTS_CHANNEL])
			.then(() => {
				if (active)
					unsubscribe = webSocketService.onAlertsChanged(() =>
						invalidateAlerts(queryClient),
					);
			})
			.catch((error) => console.error("[alerts] Failed to subscribe:", error));
		return () => {
			active = false;
			unsubscribe?.();
			webSocketService.unsubscribe(ALERTS_CHANNEL);
		};
	}, [enabled, queryClient]);
}

export function useAlertEmailSettings() {
	return $api.useQuery("get", "/api/alerts/email-settings");
}

export function useUpdateAlertEmailSettings() {
	const queryClient = useQueryClient();
	return $api.useMutation("put", "/api/alerts/email-settings", {
		onSuccess: () => {
			queryClient.invalidateQueries({
				queryKey: ["get", "/api/alerts/email-settings"],
			});
		},
	});
}

export function useSendTestAlertEmail() {
	return $api.useMutation("post", "/api/alerts/email-settings/test");
}
