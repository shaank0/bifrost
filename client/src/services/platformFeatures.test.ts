import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
	invalidateQueries: vi.fn(),
	useMutation: vi.fn((_m: unknown, _p: unknown, _o: unknown) => ({ mutateAsync: vi.fn() })),
	data: undefined as unknown,
	useQuery: vi.fn((..._args: unknown[]) => ({ data: mocks.data })),
}));

vi.mock("@tanstack/react-query", () => ({
	useQueryClient: () => ({ invalidateQueries: mocks.invalidateQueries }),
}));
vi.mock("@/lib/api-client", () => ({
	$api: { useMutation: mocks.useMutation, useQuery: mocks.useQuery },
}));

import { useFeatureEnabled, useUpdatePlatformFeatures } from "./platformFeatures";

describe("platform features service", () => {
	beforeEach(() => {
		mocks.useQuery.mockClear();
		mocks.invalidateQueries.mockReset();
	});

	it("reports a feature on only when the server says so", () => {
		mocks.data = { features: [{ key: "alerts", enabled: true }, { key: "other", enabled: false }] };
		expect(useFeatureEnabled("alerts")).toBe(true);
		expect(useFeatureEnabled("other")).toBe(false);
		expect(useFeatureEnabled("missing")).toBe(false);
	});

	it("treats a feature as off while loading, and skips the request for someone who can't read features", () => {
		mocks.data = undefined;
		expect(useFeatureEnabled("alerts", false)).toBe(false);
		expect(mocks.useQuery).toHaveBeenCalledWith("get", "/api/settings/features", {}, { enabled: false });
	});

	it("refreshes the feature list after a change", () => {
		useUpdatePlatformFeatures();
		const options = mocks.useMutation.mock.calls[0]?.[2] as { onSuccess: () => void };
		options.onSuccess();
		expect(mocks.invalidateQueries).toHaveBeenCalledWith({ queryKey: ["get", "/api/settings/features"] });
	});
});
