import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "@/test-utils";
import userEvent from "@testing-library/user-event";

const mock = vi.hoisted(() => ({
	items: [] as unknown[],
	canManage: true,
	acknowledge: vi.fn(() => Promise.resolve()),
}));

vi.mock("@/services/authorization", () => ({
	useAuthorization: () => ({
		canAt: (permission: string) => permission !== "platform.readwrite" || mock.canManage,
	}),
}));
vi.mock("@/services/alerts", () => ({
	useAlerts: () => ({ data: { items: mock.items, total: mock.items.length }, isLoading: false, error: null }),
	useAlertsLiveUpdates: () => undefined,
	useAcknowledgeAlert: () => ({ mutateAsync: mock.acknowledge, isPending: false }),
	useResolveAlert: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

import { Alerts } from "./Alerts";

const ALERT = {
	id: "a-1",
	kind: "workflow_failed",
	status: "open",
	title: "receipts_scan_mailbox failed",
	detail: "QboError: QuickBooks GET /query failed (401)",
	organization_id: "o-1",
	organization_name: "KW Corporation",
	workflow_id: "w-1",
	integration_id: null,
	last_execution_id: "e-1",
	occurrences: 3,
	first_seen_at: new Date().toISOString(),
	last_seen_at: new Date().toISOString(),
	acknowledged_at: null,
	acknowledged_by: null,
	resolved_at: null,
	emailed_at: null,
};

describe("Alerts page", () => {
	it("says so when nothing needs attention", () => {
		mock.items = [];
		renderWithProviders(<Alerts />);
		expect(screen.getByText("Nothing Needs Attention")).toBeVisible();
	});

	it("shows what broke, where, and links to the failing run", async () => {
		mock.items = [ALERT];
		renderWithProviders(<Alerts />);
		expect(screen.getByRole("heading", { name: "receipts_scan_mailbox failed" })).toBeVisible();
		expect(screen.getByText("KW Corporation")).toBeVisible();
		expect(screen.getByText(/QuickBooks GET \/query failed/)).toBeVisible();
		expect(screen.getByRole("link", { name: "View Last Run" })).toHaveAttribute("href", "/history/e-1");

		await userEvent.click(screen.getByRole("button", { name: "Acknowledge" }));
		expect(mock.acknowledge).toHaveBeenCalledWith({ params: { path: { alert_id: "a-1" } } });
	});

	it("hides the actions from someone who can only read alerts", () => {
		mock.items = [ALERT];
		mock.canManage = false;
		renderWithProviders(<Alerts />);
		expect(screen.queryByRole("button", { name: "Acknowledge" })).not.toBeInTheDocument();
		mock.canManage = true;
	});
});
