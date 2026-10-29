import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "@/test-utils";

const mock = vi.hoisted(() => ({ count: { open: 0, unresolved: 0 } }));

vi.mock("@/services/alerts", () => ({
	useAlertCount: () => ({ data: mock.count }),
	useAlertsLiveUpdates: () => undefined,
}));

import { AlertsIndicator } from "./AlertsIndicator";

describe("AlertsIndicator", () => {
	it("is hidden while nothing is broken", () => {
		mock.count = { open: 0, unresolved: 0 };
		renderWithProviders(<AlertsIndicator />);
		expect(screen.queryByRole("link")).not.toBeInTheDocument();
	});

	it("links to the alerts with the open count", () => {
		mock.count = { open: 3, unresolved: 4 };
		renderWithProviders(<AlertsIndicator />);
		const link = screen.getByRole("link", { name: "3 open alerts" });
		expect(link).toHaveAttribute("href", "/alerts");
		expect(link).toHaveTextContent("3");
	});

	it("stays visible but quiet once every alert is acknowledged", () => {
		mock.count = { open: 0, unresolved: 2 };
		renderWithProviders(<AlertsIndicator />);
		expect(screen.getByRole("link", { name: "2 acknowledged alerts" })).toBeVisible();
	});
});
