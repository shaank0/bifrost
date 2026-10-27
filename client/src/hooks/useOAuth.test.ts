import { renderHook } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const { useMutation, invalidate, toastSuccess, toastError, post } = vi.hoisted(() => ({
	useMutation: vi.fn(),
	post: vi.fn(),
	invalidate: vi.fn(),
	toastSuccess: vi.fn(),
	toastError: vi.fn(),
}));
vi.mock("@/lib/api-client", () => ({ $api: { useMutation }, apiClient: { POST: post } }));
vi.mock("@tanstack/react-query", () => ({ useQueryClient: () => ({ invalidateQueries: invalidate }) }));
vi.mock("sonner", () => ({ toast: { success: toastSuccess, error: toastError } }));
import { handleOAuthCallback, useRefreshOAuthToken } from "./useOAuth";

type RefreshOptions = {
	onSuccess: (data: { success: boolean; message: string }, variables: unknown) => void;
};

function refreshOptions(): RefreshOptions {
	renderHook(() => useRefreshOAuthToken());
	return useMutation.mock.calls[0][2] as RefreshOptions;
}

const variables = { params: { path: { connection_name: "printix" } } };

beforeEach(() => vi.clearAllMocks());

it("reports a 200 response with success=false as a refresh failure", () => {
	refreshOptions().onSuccess(
		{ success: false, message: "Token refresh failed: certificate verify failed" },
		variables,
	);
	expect(toastError).toHaveBeenCalledWith("Token refresh failed: certificate verify failed");
	expect(toastSuccess).not.toHaveBeenCalled();
	expect(invalidate).toHaveBeenCalledTimes(2);
});

it("reports success only when the response says the refresh succeeded", () => {
	refreshOptions().onSuccess({ success: true, message: "Token refreshed" }, variables);
	expect(toastSuccess).toHaveBeenCalledWith("OAuth token refreshed successfully");
	expect(toastError).not.toHaveBeenCalled();
	expect(invalidate).toHaveBeenCalledTimes(2);
});

it("sends callback URL params so the API can capture the connected entity", async () => {
	post.mockResolvedValue({ data: { success: true }, error: undefined });
	await handleOAuthCallback("intg-1", "code-1", "state-1", "https://x/cb", { realmId: "123" });
	expect(post.mock.calls[0][1].body).toEqual({
		code: "code-1",
		state: "state-1",
		redirect_uri: "https://x/cb",
		callback_url_params: { realmId: "123" },
	});
});

it("reports the API's error detail instead of [object Object]", async () => {
	post.mockResolvedValue({ data: undefined, error: { detail: "Missing permission: secrets.read" } });
	await expect(handleOAuthCallback("intg-1", "code-1")).rejects.toThrow(
		"Failed to handle OAuth callback: Missing permission: secrets.read",
	);
});
