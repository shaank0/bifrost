import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, within } from "@/test-utils";
import {
	ConnectionGatewayPanel,
	ConnectionStaticHeaders,
	describeRule,
} from "./ConnectionGateway";

const mocks = vi.hoisted(() => ({
	gateway: null as unknown,
	mutations: {} as Record<string, ReturnType<typeof vi.fn>>,
}));

vi.mock("@/lib/api-client", () => ({
	$api: {
		useQuery: (_method: string, path: string) =>
			path === "/api/roles"
				? {
						data: [
							{ id: "role-user", name: "User" },
							{ id: "role-tech", name: "Technicians" },
						],
						isLoading: false,
					}
				: {
						data: mocks.gateway,
						isLoading: false,
						isError: false,
						refetch: vi.fn(),
					},
		useMutation: (method: string, path: string) => {
			const key = `${method} ${path}`;
			mocks.mutations[key] ??= vi.fn().mockResolvedValue({});
			return { mutateAsync: mocks.mutations[key], isPending: false };
		},
	},
}));

const GRANTS_PATH =
	"/api/mcp-gateway/connections/{connection_id}/grants/{role_id}";

function gateway(overrides: Record<string, unknown> = {}) {
	return {
		connection_id: "conn-1",
		organization_id: "org-1",
		enabled: false,
		slug: null,
		static_header_names: [],
		grants: [
			{
				role_id: "role-tech",
				role_name: "Technicians",
				rule: { categories: ["read"], allow: [], deny: [] },
			},
		],
		tools: [
			{
				tool_name: "get_ticket",
				gateway_name: null,
				category: "read",
				enabled: true,
				granted_role_ids: ["role-tech"],
			},
			{
				tool_name: "raw_request",
				gateway_name: null,
				category: "dangerous",
				enabled: true,
				granted_role_ids: [],
			},
		],
		...overrides,
	};
}

beforeEach(() => {
	mocks.gateway = gateway();
	mocks.mutations = {};
});

describe("describeRule", () => {
	it("summarizes each rule shape", () => {
		expect(describeRule(null)).toBe("All tools");
		expect(describeRule(["a"])).toBe("1 selected tool");
		expect(describeRule(["a", "b"])).toBe("2 selected tools");
		expect(
			describeRule({
				categories: ["read", "create"],
				allow: ["raw_request"],
				deny: [],
			}),
		).toBe("Read, Create · 1 allowed");
		expect(describeRule({ categories: [], deny: ["x"] })).toBe(
			"No categories · 1 denied",
		);
	});
});

describe("ConnectionGatewayPanel", () => {
	it("previews which roles each tool is served to", () => {
		renderWithProviders(<ConnectionGatewayPanel connectionId="conn-1" />);
		const access = screen.getByRole("list", {
			name: "Gateway tool access",
		});
		const [getTicket, rawRequest] = within(access).getAllByRole("listitem");
		expect(getTicket).toHaveTextContent("get_ticket");
		expect(getTicket).toHaveTextContent("Technicians");
		expect(rawRequest).toHaveTextContent("No role has access");
		expect(rawRequest).toHaveTextContent("Dangerous");
		expect(
			screen.getByRole("list", { name: "Role access" }),
		).toHaveTextContent("Read");
	});

	it("requires a tool prefix before serving on the gateway", async () => {
		const { user } = renderWithProviders(
			<ConnectionGatewayPanel connectionId="conn-1" />,
		);
		await user.click(
			screen.getByRole("switch", { name: "Serve on MCP Gateway" }),
		);
		await user.click(
			screen.getByRole("button", { name: "Save Gateway Settings" }),
		);
		expect(screen.getByRole("alert")).toHaveTextContent(
			"Set a tool prefix",
		);

		await user.type(screen.getByLabelText("Tool Prefix"), "PSA");
		await user.click(
			screen.getByRole("button", { name: "Save Gateway Settings" }),
		);
		expect(
			mocks.mutations[
				"patch /api/mcp-gateway/connections/{connection_id}"
			],
		).toHaveBeenCalledWith({
			params: { path: { connection_id: "conn-1" } },
			body: { enabled: true, slug: "psa" },
		});
	});

	it("saves an edited grant as every tool", async () => {
		const { user } = renderWithProviders(
			<ConnectionGatewayPanel connectionId="conn-1" />,
		);
		await user.click(
			screen.getByRole("button", { name: "Edit access for Technicians" }),
		);
		const dialog = screen.getByRole("dialog");
		await user.click(
			within(dialog).getByRole("radio", { name: "All Tools" }),
		);
		await user.click(
			within(dialog).getByRole("button", { name: "Save Access" }),
		);
		expect(mocks.mutations[`put ${GRANTS_PATH}`]).toHaveBeenCalledWith({
			params: { path: { connection_id: "conn-1", role_id: "role-tech" } },
			body: { rule: null },
		});
	});

	it("saves a selected-tools grant", async () => {
		const { user } = renderWithProviders(
			<ConnectionGatewayPanel connectionId="conn-1" />,
		);
		await user.click(
			screen.getByRole("button", { name: "Edit access for Technicians" }),
		);
		const dialog = screen.getByRole("dialog");
		await user.click(
			within(dialog).getByRole("radio", { name: "Selected Tools" }),
		);
		await user.click(
			within(dialog).getByRole("checkbox", { name: /raw_request/ }),
		);
		await user.click(
			within(dialog).getByRole("button", { name: "Save Access" }),
		);
		expect(mocks.mutations[`put ${GRANTS_PATH}`]).toHaveBeenCalledWith(
			expect.objectContaining({ body: { rule: ["raw_request"] } }),
		);
	});

	it("removes a grant", async () => {
		const { user } = renderWithProviders(
			<ConnectionGatewayPanel connectionId="conn-1" />,
		);
		await user.click(
			screen.getByRole("button", {
				name: "Remove access for Technicians",
			}),
		);
		expect(mocks.mutations[`delete ${GRANTS_PATH}`]).toHaveBeenCalledWith({
			params: { path: { connection_id: "conn-1", role_id: "role-tech" } },
		});
	});
});

describe("ConnectionStaticHeaders", () => {
	const HEADERS_PATH =
		"put /api/mcp-gateway/connections/{connection_id}/static-headers";

	it("saves headers without ever displaying values", async () => {
		const { user } = renderWithProviders(
			<ConnectionStaticHeaders connectionId="conn-1" />,
		);
		await user.click(screen.getByRole("button", { name: "Add Headers" }));
		await user.type(screen.getByLabelText("Header Name"), "X-API-Key");
		await user.type(screen.getByLabelText("Header Value"), "s3cret");
		expect(screen.getByLabelText("Header Value")).toHaveAttribute(
			"type",
			"password",
		);
		await user.click(screen.getByRole("button", { name: "Save Headers" }));
		expect(mocks.mutations[HEADERS_PATH]).toHaveBeenCalledWith({
			params: { path: { connection_id: "conn-1" } },
			body: { headers: { "X-API-Key": "s3cret" } },
		});
	});

	it("rejects invalid header names", async () => {
		const { user } = renderWithProviders(
			<ConnectionStaticHeaders connectionId="conn-1" />,
		);
		await user.click(screen.getByRole("button", { name: "Add Headers" }));
		await user.type(screen.getByLabelText("Header Name"), "Bad Header");
		await user.type(screen.getByLabelText("Header Value"), "x");
		await user.click(screen.getByRole("button", { name: "Save Headers" }));
		expect(screen.getByRole("alert")).toHaveTextContent("not a valid");
		expect(mocks.mutations[HEADERS_PATH]).not.toHaveBeenCalled();
	});

	it("lists configured header names and clears them", async () => {
		mocks.gateway = gateway({ static_header_names: ["X-API-Key"] });
		const { user } = renderWithProviders(
			<ConnectionStaticHeaders connectionId="conn-1" />,
		);
		expect(screen.getByText("X-API-Key")).toBeVisible();
		await user.click(screen.getByRole("button", { name: "Clear Headers" }));
		expect(mocks.mutations[HEADERS_PATH]).toHaveBeenCalledWith({
			params: { path: { connection_id: "conn-1" } },
			body: { headers: null },
		});
	});
});
