import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "@/test-utils";
import userEvent from "@testing-library/user-event";

const mock = vi.hoisted(() => ({ update: vi.fn((_body: unknown) => Promise.resolve()) }));

vi.mock("@/services/authorization", () => ({ useAuthorization: () => ({ canAt: () => true }) }));
vi.mock("@/services/platformFeatures", () => ({
	usePlatformFeatures: () => ({
		data: {
			features: [
				{ key: "alerts", label: "Failure Alerts", description: "Open an alert when…", enabled: false },
			],
		},
		error: null,
		refetch: vi.fn(),
	}),
	useUpdatePlatformFeatures: () => ({ mutateAsync: mock.update }),
}));

import { FeaturesSettings } from "./FeaturesSettings";

describe("Features settings", () => {
	it("turns a feature on", async () => {
		renderWithProviders(<FeaturesSettings />);
		const toggle = screen.getByRole("switch", { name: "Failure Alerts" });
		expect(toggle).not.toBeChecked();
		await userEvent.click(toggle);
		expect(mock.update).toHaveBeenCalledWith({ body: { enabled: { alerts: true } } });
	});
});
