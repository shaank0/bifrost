/**
 * Optional platform features (Settings → Platform → Features)
 *
 * Every feature is off until a platform admin turns it on. A feature's UI
 * asks `useFeatureEnabled(key)` before showing anything.
 */

import { useQueryClient } from "@tanstack/react-query";
import { $api } from "@/lib/api-client";
import type { components } from "@/lib/v1";

export type PlatformFeature = components["schemas"]["PlatformFeaturePublic"];

export function usePlatformFeatures(enabled = true) {
	return $api.useQuery("get", "/api/settings/features", {}, { enabled });
}

/** Whether a feature is on; false while loading, or for someone who can't read features. */
export function useFeatureEnabled(key: string, canRead = true): boolean {
	const features = usePlatformFeatures(canRead);
	return features.data?.features.some((f) => f.key === key && f.enabled) ?? false;
}

export function useUpdatePlatformFeatures() {
	const queryClient = useQueryClient();
	return $api.useMutation("put", "/api/settings/features", {
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: ["get", "/api/settings/features"] });
		},
	});
}
