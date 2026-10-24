import { beforeEach, expect, it, vi } from "vitest";
import { renderWithProviders, screen } from "@/test-utils";
import { NewConnectionDialog } from "./NewConnectionDialog";

const mocks = vi.hoisted(() => ({
	reload: vi.fn(),
	mutate: vi.fn(),
	orgError: true,
	organizations: [] as { id: string; name: string }[],
}));
vi.mock("@/hooks/useOrganizations", () => ({
	useOrganizations: () => ({
		data: mocks.organizations,
		isError: mocks.orgError,
		isLoading: false,
		isFetching: false,
		refetch: mocks.reload,
	}),
}));
vi.mock("@/lib/api-client", () => ({
	$api: {
		useMutation: () => ({ mutateAsync: mocks.mutate, isPending: false }),
	},
}));
beforeEach(() => {
	vi.clearAllMocks();
	mocks.orgError = true;
	mocks.organizations = [];
});

it("offers lookup recovery without allowing a connection with unavailable organizations", async () => {
	const { user } = renderWithProviders(
		<NewConnectionDialog
			open
			onOpenChange={vi.fn()}
			serverId="server"
			usesOAuth
		/>,
	);
	expect(screen.getByRole("alert")).toHaveTextContent(
		"Could not load organizations.",
	);
	expect(
		screen.getByRole("combobox", { name: "Organization" }),
	).toBeDisabled();
	expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
	await user.type(screen.getByLabelText("Client ID"), "retained-client");
	await user.click(
		screen.getByRole("button", { name: "Retry organizations" }),
	);
	expect(mocks.reload).toHaveBeenCalledOnce();
	expect(screen.getByLabelText("Client ID")).toHaveValue("retained-client");
	expect(mocks.mutate).not.toHaveBeenCalled();
});

it("distinguishes a successful empty lookup from a failed lookup", () => {
	mocks.orgError = false;
	renderWithProviders(
		<NewConnectionDialog
			open
			onOpenChange={vi.fn()}
			serverId="server"
			usesOAuth
		/>,
	);
	expect(
		screen.getByText("No organizations are available for this connection."),
	).toBeVisible();
	expect(screen.queryByRole("alert")).not.toBeInTheDocument();
	expect(screen.getByRole("button", { name: "Create" })).toBeDisabled();
});

it("creates a connection without client credentials for a server with no OAuth", async () => {
	mocks.orgError = false;
	mocks.organizations = [{ id: "org-1", name: "Acme" }];
	mocks.mutate.mockResolvedValue({ id: "conn-1" });
	const { user } = renderWithProviders(
		<NewConnectionDialog
			open
			onOpenChange={vi.fn()}
			serverId="server"
			usesOAuth={false}
		/>,
	);
	expect(screen.queryByLabelText("Client ID")).not.toBeInTheDocument();
	await user.click(screen.getByRole("combobox", { name: "Organization" }));
	await user.click(screen.getByRole("option", { name: "Acme" }));
	await user.click(screen.getByRole("button", { name: "Create" }));
	expect(mocks.mutate).toHaveBeenCalledWith({
		body: {
			server_id: "server",
			organization_id: "org-1",
			available_in_chat: false,
			available_to_autonomous: false,
		},
	});
});
