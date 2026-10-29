import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
	invalidateQueries: vi.fn(),
	useMutation: vi.fn((_m: unknown, _p: unknown, _o: unknown) => ({ mutateAsync: vi.fn() })),
	useQuery: vi.fn(),
	connect: vi.fn(() => Promise.resolve()),
	unsubscribe: vi.fn(),
	alertsChanged: [] as Array<() => void>,
	effects: [] as Array<() => void | (() => void)>,
}));

vi.mock("react", () => ({
	useEffect: (effect: () => void | (() => void)) => {
		mocks.effects.push(effect);
	},
}));
vi.mock("@tanstack/react-query", () => ({
	useQueryClient: () => ({ invalidateQueries: mocks.invalidateQueries }),
}));
vi.mock("@/lib/api-client", () => ({
	$api: { useMutation: mocks.useMutation, useQuery: mocks.useQuery },
}));
vi.mock("@/services/websocket", () => ({
	webSocketService: {
		connect: mocks.connect,
		unsubscribe: mocks.unsubscribe,
		onAlertsChanged: (cb: () => void) => {
			mocks.alertsChanged.push(cb);
			return () => {
				mocks.alertsChanged = mocks.alertsChanged.filter((c) => c !== cb);
			};
		},
	},
}));

import { useAcknowledgeAlert, useAlerts, useAlertsLiveUpdates } from "./alerts";

const listAndCount = [
	{ queryKey: ["get", "/api/alerts"] },
	{ queryKey: ["get", "/api/alerts/count"] },
];

describe("alerts service", () => {
	beforeEach(() => {
		mocks.invalidateQueries.mockReset();
		mocks.useMutation.mockClear();
		mocks.useQuery.mockClear();
		mocks.connect.mockClear();
		mocks.unsubscribe.mockClear();
		mocks.alertsChanged = [];
		mocks.effects = [];
	});

	it("asks for one view of the alerts", () => {
		useAlerts("resolved");
		expect(mocks.useQuery).toHaveBeenCalledWith("get", "/api/alerts", {
			params: { query: { view: "resolved", limit: 200 } },
		});
	});

	it("acknowledging refreshes the list and the header count", () => {
		useAcknowledgeAlert();
		const options = mocks.useMutation.mock.calls[0]?.[2] as { onSuccess: () => void };
		options.onSuccess();
		for (const key of listAndCount) expect(mocks.invalidateQueries).toHaveBeenCalledWith(key);
	});

	it("refreshes alerts when the server says they changed, and stops listening on unmount", async () => {
		useAlertsLiveUpdates(true);
		const cleanup = mocks.effects[0]?.() as () => void;
		await Promise.resolve();
		expect(mocks.connect).toHaveBeenCalledWith(["alerts"]);

		mocks.alertsChanged.forEach((cb) => cb());
		for (const key of listAndCount) expect(mocks.invalidateQueries).toHaveBeenCalledWith(key);

		cleanup();
		expect(mocks.alertsChanged).toHaveLength(0);
		expect(mocks.unsubscribe).toHaveBeenCalledWith("alerts");
	});

	it("does not subscribe when the viewer can't see alerts", () => {
		useAlertsLiveUpdates(false);
		expect(mocks.effects[0]?.()).toBeUndefined();
		expect(mocks.connect).not.toHaveBeenCalled();
	});
});
