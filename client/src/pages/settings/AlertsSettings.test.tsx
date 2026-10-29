import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "@/test-utils";
import userEvent from "@testing-library/user-event";

const mock = vi.hoisted(() => ({
	save: vi.fn((_body: unknown) => Promise.resolve()),
	saved: {
		enabled: false,
		host: "smtp.office365.com",
		port: 587,
		security: "starttls",
		username: "alerts@kw-corp.com",
		password_set: true,
		from_address: "alerts@kw-corp.com",
		recipients: ["will@kw-corp.com"],
	},
}));

vi.mock("@/services/authorization", () => ({
	useAuthorization: () => ({ canAt: () => true }),
}));
vi.mock("@/services/alerts", () => ({
	useAlertEmailSettings: () => ({ data: mock.saved, error: null, refetch: vi.fn() }),
	useUpdateAlertEmailSettings: () => ({ mutateAsync: mock.save, isPending: false }),
	useSendTestAlertEmail: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

import { AlertsSettings, errorText } from "./AlertsSettings";

describe("Alert email settings", () => {
	it("keeps the saved password unless a new one is typed", async () => {
		renderWithProviders(<AlertsSettings />);
		expect(screen.getByText("Saved. Type a new one to replace it.")).toBeVisible();

		await userEvent.click(screen.getByRole("switch", { name: "Send Alert Email" }));
		await userEvent.click(screen.getByRole("button", { name: "Save" }));

		expect(mock.save).toHaveBeenCalledWith({
			body: expect.objectContaining({ enabled: true, host: "smtp.office365.com", password: null }),
		});
	});

	it("can't send a test until email is on and saved", () => {
		renderWithProviders(<AlertsSettings />);
		expect(screen.getByRole("button", { name: "Send Test Email" })).toBeDisabled();
	});

	it("shows the API's reason for a failure", () => {
		expect(errorText({ detail: "To turn alert email on, set an SMTP server" }, "x")).toBe(
			"To turn alert email on, set an SMTP server",
		);
		expect(errorText(new Error("network"), "x")).toBe("network");
		expect(errorText(42, "fallback")).toBe("fallback");
	});
});
