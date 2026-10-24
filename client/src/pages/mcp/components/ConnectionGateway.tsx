/**
 * MCP gateway configuration for one connection.
 *
 *   - ConnectionStaticHeaders — write-only headers (e.g. an API key) for
 *     servers with no OAuth provider. Values are never read back.
 *   - ConnectionGatewayPanel  — serve on /mcp/gateway under a tool prefix,
 *     role grants, and the per-tool access preview.
 *
 * Both read GET /api/mcp-gateway/connections/{id} and save independently of
 * the connection page's Save button.
 */

import { useId, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Copy, Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { TagsInput } from "@/components/ui/tags-input";
import { $api } from "@/lib/api-client";
import { copyToClipboard } from "@/lib/clipboard";
import type { components } from "@/lib/v1";

type GatewayConnection = components["schemas"]["MCPGatewayConnectionPublic"];
type GatewayGrant = components["schemas"]["MCPGatewayGrantPublic"];
type GatewayTool = components["schemas"]["MCPGatewayToolPublic"];
type CategoryRule = components["schemas"]["MCPGatewayCategoryRule"];
type GatewayRule = GatewayGrant["rule"];
type GatewayCategory = "read" | "create" | "modify" | "delete";

const GATEWAY_QUERY_KEY = [
	"get",
	"/api/mcp-gateway/connections/{connection_id}",
];
const CATEGORIES: GatewayCategory[] = ["read", "create", "modify", "delete"];
const CATEGORY_LABELS: Record<GatewayTool["category"], string> = {
	read: "Read",
	create: "Create",
	modify: "Modify",
	delete: "Delete",
	dangerous: "Dangerous",
};
const SLUG_PATTERN = /^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$/;
const HEADER_NAME_PATTERN = /^[A-Za-z0-9!#$%&'*+.^_`|~-]+$/;

function errorDetail(err: unknown, fallback: string): string {
	if (err instanceof Error) return err.message;
	const detail = (err as { detail?: unknown } | null)?.detail;
	return typeof detail === "string" ? detail : fallback;
}

/** One-line description of a grant's rule, e.g. "Read, Create · 2 allowed". */
export function describeRule(rule: GatewayRule): string {
	if (rule === null || rule === undefined) return "All tools";
	if (Array.isArray(rule))
		return rule.length === 1
			? "1 selected tool"
			: `${rule.length} selected tools`;
	const { categories = [], allow = [], deny = [] } = rule;
	const parts = [
		categories.length > 0
			? categories.map((c) => CATEGORY_LABELS[c]).join(", ")
			: "No categories",
	];
	if (allow.length > 0) parts.push(`${allow.length} allowed`);
	if (deny.length > 0) parts.push(`${deny.length} denied`);
	return parts.join(" · ");
}

function useGatewayConnection(connectionId: string) {
	return $api.useQuery(
		"get",
		"/api/mcp-gateway/connections/{connection_id}",
		{
			params: { path: { connection_id: connectionId } },
		},
	);
}

function useInvalidateGateway() {
	const queryClient = useQueryClient();
	return () => queryClient.invalidateQueries({ queryKey: GATEWAY_QUERY_KEY });
}

/* ------------------------------------------------------------------ */
/* Static headers                                                      */
/* ------------------------------------------------------------------ */

type HeaderRow = { key: number; name: string; value: string };

export function ConnectionStaticHeaders({
	connectionId,
}: {
	connectionId: string;
}) {
	const { data: gateway, isLoading } = useGatewayConnection(connectionId);
	const invalidate = useInvalidateGateway();
	const putHeaders = $api.useMutation(
		"put",
		"/api/mcp-gateway/connections/{connection_id}/static-headers",
	);
	const [editing, setEditing] = useState(false);
	const [rows, setRows] = useState<HeaderRow[]>([]);
	const [error, setError] = useState<string | null>(null);

	const configured = gateway?.static_header_names ?? [];

	const startEditing = () => {
		setRows(
			(configured.length > 0 ? configured : [""]).map((name, key) => ({
				key,
				name,
				value: "",
			})),
		);
		setError(null);
		setEditing(true);
	};

	const save = async (headers: Record<string, string> | null) => {
		setError(null);
		try {
			await putHeaders.mutateAsync({
				params: { path: { connection_id: connectionId } },
				body: { headers },
			});
			toast.success(headers ? "Headers saved" : "Headers cleared");
			setEditing(false);
			setRows([]);
			await invalidate();
		} catch (err) {
			setError(errorDetail(err, "Could not save headers. Try again."));
		}
	};

	const handleSave = () => {
		const headers: Record<string, string> = {};
		for (const row of rows) {
			const name = row.name.trim();
			if (!name && !row.value) continue;
			if (!HEADER_NAME_PATTERN.test(name)) {
				setError(`"${name || "(empty)"}" is not a valid header name.`);
				return;
			}
			if (!row.value) {
				setError(`Enter a value for ${name}.`);
				return;
			}
			headers[name] = row.value;
		}
		if (Object.keys(headers).length === 0) {
			setError("Add at least one header, or use Clear Headers.");
			return;
		}
		void save(headers);
	};

	return (
		<Card>
			<CardContent className="py-6 space-y-4">
				<h2 className="text-lg font-semibold">
					Authentication Headers
				</h2>
				<p className="text-xs text-muted-foreground">
					This server has no OAuth provider. Bifrost sends these
					headers, such as an API key, on every call for this
					organization. Values are stored encrypted and never shown
					again.
				</p>
				{isLoading ? (
					<Skeleton className="h-11 w-full" />
				) : editing ? (
					<div className="space-y-3">
						{rows.map((row, index) => (
							<div
								key={row.key}
								className="flex flex-wrap items-end gap-2 sm:flex-nowrap"
							>
								<div className="min-w-0 flex-1 space-y-1">
									<Label htmlFor={`header-name-${row.key}`}>
										Header Name
									</Label>
									<Input
										id={`header-name-${row.key}`}
										value={row.name}
										placeholder="X-API-Key"
										className="min-h-11 font-mono"
										onChange={(e) =>
											setRows((prev) =>
												prev.map((r) =>
													r.key === row.key
														? {
																...r,
																name: e.target
																	.value,
															}
														: r,
												),
											)
										}
									/>
								</div>
								<div className="min-w-0 flex-1 space-y-1">
									<Label htmlFor={`header-value-${row.key}`}>
										Header Value
									</Label>
									<Input
										id={`header-value-${row.key}`}
										type="password"
										autoComplete="new-password"
										value={row.value}
										placeholder="••••••••"
										className="min-h-11"
										onChange={(e) =>
											setRows((prev) =>
												prev.map((r) =>
													r.key === row.key
														? {
																...r,
																value: e.target
																	.value,
															}
														: r,
												),
											)
										}
									/>
								</div>
								<Button
									type="button"
									variant="outline"
									size="icon"
									className="min-h-11 min-w-11 shrink-0"
									aria-label={`Remove header ${index + 1}`}
									disabled={rows.length === 1}
									onClick={() =>
										setRows((prev) =>
											prev.filter(
												(r) => r.key !== row.key,
											),
										)
									}
								>
									<Trash2 className="h-4 w-4" />
								</Button>
							</div>
						))}
						<p className="text-xs text-muted-foreground">
							Saving replaces every configured header, so re-enter
							all values.
						</p>
						<div className="flex flex-wrap gap-2 [&_button]:min-h-11">
							<Button
								type="button"
								variant="outline"
								onClick={() =>
									setRows((prev) => [
										...prev,
										{
											key:
												Math.max(
													-1,
													...prev.map((r) => r.key),
												) + 1,
											name: "",
											value: "",
										},
									])
								}
							>
								<Plus className="h-4 w-4 mr-1" />
								Add Header
							</Button>
							<Button
								type="button"
								onClick={handleSave}
								disabled={putHeaders.isPending}
							>
								{putHeaders.isPending
									? "Saving..."
									: "Save Headers"}
							</Button>
							<Button
								type="button"
								variant="outline"
								disabled={putHeaders.isPending}
								onClick={() => setEditing(false)}
							>
								Cancel
							</Button>
						</div>
					</div>
				) : (
					<div className="flex flex-wrap items-center justify-between gap-3">
						<div className="flex flex-wrap gap-2">
							{configured.length > 0 ? (
								configured.map((name) => (
									<Badge
										key={name}
										variant="secondary"
										className="font-mono"
									>
										{name}
									</Badge>
								))
							) : (
								<p className="text-sm text-muted-foreground">
									No headers configured. Tool calls to this
									server will fail until you add them.
								</p>
							)}
						</div>
						<div className="flex gap-2 [&_button]:min-h-11">
							<Button
								type="button"
								variant="outline"
								onClick={startEditing}
							>
								{configured.length > 0
									? "Replace Headers"
									: "Add Headers"}
							</Button>
							{configured.length > 0 && (
								<Button
									type="button"
									variant="outline"
									className="text-destructive hover:text-destructive hover:bg-destructive/10"
									disabled={putHeaders.isPending}
									onClick={() => void save(null)}
								>
									Clear Headers
								</Button>
							)}
						</div>
					</div>
				)}
				{error && (
					<p
						role="alert"
						className="text-sm text-destructive [overflow-wrap:anywhere]"
					>
						{error}
					</p>
				)}
			</CardContent>
		</Card>
	);
}

/* ------------------------------------------------------------------ */
/* Gateway exposure, grants, and preview                               */
/* ------------------------------------------------------------------ */

export function ConnectionGatewayPanel({
	connectionId,
}: {
	connectionId: string;
}) {
	const {
		data: gateway,
		isLoading,
		isError,
		refetch,
	} = useGatewayConnection(connectionId);

	return (
		<Card>
			<CardContent className="py-6 space-y-6">
				<div className="space-y-1">
					<h2 className="text-lg font-semibold">MCP Gateway</h2>
					<p className="text-xs text-muted-foreground">
						Serve this connection's tools to AI clients such as
						Claude, Copilot, or Cursor. Users see only the tools
						their roles are granted.
					</p>
				</div>
				{isLoading ? (
					<Skeleton className="h-32 w-full" />
				) : isError || !gateway ? (
					<div
						role="alert"
						className="space-y-2 text-sm text-destructive"
					>
						<p>Gateway settings could not be loaded.</p>
						<Button
							type="button"
							variant="outline"
							className="min-h-11"
							onClick={() => void refetch()}
						>
							Retry Gateway Settings
						</Button>
					</div>
				) : (
					<>
						<GatewayExposure
							key={`${gateway.enabled}:${gateway.slug ?? ""}`}
							gateway={gateway}
						/>
						<GatewayGrants gateway={gateway} />
						<GatewayToolAccess gateway={gateway} />
					</>
				)}
			</CardContent>
		</Card>
	);
}

function GatewayExposure({ gateway }: { gateway: GatewayConnection }) {
	const invalidate = useInvalidateGateway();
	const update = $api.useMutation(
		"patch",
		"/api/mcp-gateway/connections/{connection_id}",
	);
	const [enabled, setEnabled] = useState(gateway.enabled);
	const [slug, setSlug] = useState(gateway.slug ?? "");
	const [error, setError] = useState<string | null>(null);
	const endpoint = `${window.location.origin}/mcp/gateway`;
	const dirty = enabled !== gateway.enabled || slug !== (gateway.slug ?? "");

	const handleSave = async () => {
		setError(null);
		if (slug && !SLUG_PATTERN.test(slug)) {
			setError(
				"Use lowercase letters, numbers, and hyphens (up to 40 characters).",
			);
			return;
		}
		if (enabled && !slug) {
			setError("Set a tool prefix before serving on the gateway.");
			return;
		}
		try {
			await update.mutateAsync({
				params: { path: { connection_id: gateway.connection_id } },
				body: {
					enabled,
					...(slug && slug !== gateway.slug ? { slug } : {}),
				},
			});
			toast.success("Gateway settings saved");
			await invalidate();
		} catch (err) {
			setError(errorDetail(err, "Could not save gateway settings."));
		}
	};

	return (
		<section className="space-y-4" aria-labelledby="gateway-exposure">
			<h3 id="gateway-exposure" className="text-sm font-semibold">
				Exposure
			</h3>
			<div className="flex items-start gap-3">
				<Switch
					id="gateway_enabled"
					checked={enabled}
					onCheckedChange={(v) => setEnabled(v === true)}
					className="mt-0.5"
				/>
				<div>
					<Label
						htmlFor="gateway_enabled"
						className="flex min-h-11 cursor-pointer items-center font-semibold"
					>
						Serve on MCP Gateway
					</Label>
					<p className="text-xs text-muted-foreground mt-1">
						Granted users of this organization see these tools at
						the gateway endpoint.
					</p>
				</div>
			</div>
			<div className="space-y-2">
				<Label htmlFor="gateway_slug">Tool Prefix</Label>
				<Input
					id="gateway_slug"
					value={slug}
					onChange={(e) => setSlug(e.target.value.toLowerCase())}
					placeholder="autotask"
					className="min-h-11 max-w-sm font-mono"
					aria-describedby="gateway_slug_help"
				/>
				<p
					id="gateway_slug_help"
					className="text-xs text-muted-foreground"
				>
					Tools are served as{" "}
					<code className="font-mono">
						{slug || "prefix"}__tool_name
					</code>
					. Unique within the organization.
				</p>
			</div>
			<div className="space-y-1">
				<p className="text-xs font-medium">Gateway Endpoint</p>
				<div className="flex min-w-0 items-center gap-2">
					<code className="min-w-0 rounded-md bg-muted px-2 py-1 font-mono text-xs [overflow-wrap:anywhere]">
						{endpoint}
					</code>
					<Button
						type="button"
						variant="ghost"
						size="icon"
						className="min-h-11 min-w-11 shrink-0"
						aria-label="Copy gateway endpoint"
						onClick={async () => {
							if (await copyToClipboard(endpoint))
								toast.success("Copied to clipboard");
							else toast.error("Failed to copy to clipboard");
						}}
					>
						<Copy className="h-4 w-4" />
					</Button>
				</div>
			</div>
			{error && (
				<p
					role="alert"
					className="text-sm text-destructive [overflow-wrap:anywhere]"
				>
					{error}
				</p>
			)}
			<Button
				type="button"
				className="min-h-11"
				disabled={!dirty || update.isPending}
				onClick={() => void handleSave()}
			>
				{update.isPending ? (
					<>
						<Loader2 className="h-4 w-4 mr-2 animate-spin motion-reduce:animate-none" />
						Saving...
					</>
				) : (
					"Save Gateway Settings"
				)}
			</Button>
		</section>
	);
}

function GatewayGrants({ gateway }: { gateway: GatewayConnection }) {
	const invalidate = useInvalidateGateway();
	const removeGrant = $api.useMutation(
		"delete",
		"/api/mcp-gateway/connections/{connection_id}/grants/{role_id}",
	);
	const [editing, setEditing] = useState<GatewayGrant | "new" | null>(null);
	const [removing, setRemoving] = useState<string | null>(null);

	const handleRemove = async (grant: GatewayGrant) => {
		setRemoving(grant.role_id);
		try {
			await removeGrant.mutateAsync({
				params: {
					path: {
						connection_id: gateway.connection_id,
						role_id: grant.role_id,
					},
				},
			});
			toast.success(`Removed access for ${grant.role_name}`);
			await invalidate();
		} catch (err) {
			toast.error(errorDetail(err, "Could not remove access."));
		} finally {
			setRemoving(null);
		}
	};

	return (
		<section className="space-y-3" aria-labelledby="gateway-grants">
			<div className="flex flex-wrap items-center justify-between gap-3">
				<h3 id="gateway-grants" className="text-sm font-semibold">
					Role Access
				</h3>
				<Button
					type="button"
					variant="outline"
					className="min-h-11"
					onClick={() => setEditing("new")}
				>
					<Plus className="h-4 w-4 mr-1" />
					Grant Role
				</Button>
			</div>
			{gateway.grants.length === 0 ? (
				<p className="text-sm text-muted-foreground">
					No roles have access. Nobody, including admins, sees these
					tools until a role is granted.
				</p>
			) : (
				<ul aria-label="Role access" className="min-w-0">
					{gateway.grants.map((grant) => (
						<li
							key={grant.role_id}
							className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0"
						>
							<div className="min-w-0">
								<p className="font-medium [overflow-wrap:anywhere]">
									{grant.role_name}
								</p>
								<p className="text-xs text-muted-foreground">
									{describeRule(grant.rule)}
								</p>
							</div>
							<div className="flex gap-2 [&_button]:min-h-11">
								<Button
									type="button"
									variant="outline"
									onClick={() => setEditing(grant)}
									aria-label={`Edit access for ${grant.role_name}`}
								>
									Edit
								</Button>
								<Button
									type="button"
									variant="outline"
									className="text-destructive hover:text-destructive hover:bg-destructive/10"
									disabled={removing === grant.role_id}
									onClick={() => void handleRemove(grant)}
									aria-label={`Remove access for ${grant.role_name}`}
								>
									Remove
								</Button>
							</div>
						</li>
					))}
				</ul>
			)}
			{editing !== null && (
				<GrantDialog
					gateway={gateway}
					grant={editing === "new" ? null : editing}
					onClose={() => setEditing(null)}
				/>
			)}
		</section>
	);
}

type RuleMode = "all" | "categories" | "tools";

function initialMode(rule: GatewayRule | undefined): RuleMode {
	if (rule === null || rule === undefined) return "all";
	return Array.isArray(rule) ? "tools" : "categories";
}

function GrantDialog({
	gateway,
	grant,
	onClose,
}: {
	gateway: GatewayConnection;
	grant: GatewayGrant | null;
	onClose: () => void;
}) {
	const formId = useId();
	const invalidate = useInvalidateGateway();
	const putGrant = $api.useMutation(
		"put",
		"/api/mcp-gateway/connections/{connection_id}/grants/{role_id}",
	);
	// Built-in roles included: granting the base User role is the common case.
	const { data: roles = [], isLoading: rolesLoading } = $api.useQuery(
		"get",
		"/api/roles",
		{ params: { query: { include_builtin: true } } },
	);
	const grantedIds = useMemo(
		() => new Set(gateway.grants.map((g) => g.role_id)),
		[gateway.grants],
	);
	const toolNames = useMemo(
		() => gateway.tools.map((t) => t.tool_name),
		[gateway.tools],
	);
	const existingRule = grant?.rule;
	const categoryRule: CategoryRule | null =
		existingRule && !Array.isArray(existingRule) ? existingRule : null;

	const [roleId, setRoleId] = useState(grant?.role_id ?? "");
	const [mode, setMode] = useState<RuleMode>(
		grant ? initialMode(existingRule) : "categories",
	);
	const [categories, setCategories] = useState<GatewayCategory[]>(
		categoryRule?.categories ?? ["read"],
	);
	const [allow, setAllow] = useState<string[]>(categoryRule?.allow ?? []);
	const [deny, setDeny] = useState<string[]>(categoryRule?.deny ?? []);
	const [selected, setSelected] = useState<string[]>(
		Array.isArray(existingRule) ? existingRule : [],
	);
	const [error, setError] = useState<string | null>(null);

	const roleOptions = roles.filter(
		(role) => !grantedIds.has(role.id) || role.id === grant?.role_id,
	);
	const isKnownTool = (name: string) => toolNames.includes(name);

	const handleSave = async () => {
		setError(null);
		if (!roleId) {
			setError("Select a role.");
			return;
		}
		const rule: GatewayRule =
			mode === "all"
				? null
				: mode === "tools"
					? selected
					: { categories, allow, deny };
		try {
			await putGrant.mutateAsync({
				params: {
					path: {
						connection_id: gateway.connection_id,
						role_id: roleId,
					},
				},
				body: { rule },
			});
			toast.success("Role access saved");
			await invalidate();
			onClose();
		} catch (err) {
			setError(errorDetail(err, "Could not save role access."));
		}
	};

	return (
		<Dialog
			open
			onOpenChange={(open) => {
				if (!open && !putGrant.isPending) onClose();
			}}
		>
			<DialogContent className="flex max-h-[90dvh] flex-col overflow-hidden">
				<DialogHeader className="shrink-0">
					<DialogTitle>
						{grant
							? `Access for ${grant.role_name}`
							: "Grant Role Access"}
					</DialogTitle>
					<DialogDescription>
						Choose which of this connection's tools the role can use
						through the gateway.
					</DialogDescription>
				</DialogHeader>
				<fieldset
					disabled={putGrant.isPending}
					className="min-h-0 min-w-0 space-y-5 overflow-y-auto"
				>
					{!grant && (
						<div className="space-y-2">
							<Label htmlFor={`${formId}-role`}>Role</Label>
							<Select
								value={roleId}
								onValueChange={setRoleId}
								disabled={rolesLoading}
							>
								<SelectTrigger
									id={`${formId}-role`}
									className="min-h-11 w-full"
								>
									<SelectValue
										placeholder={
											rolesLoading
												? "Loading roles..."
												: "Select role..."
										}
									/>
								</SelectTrigger>
								<SelectContent>
									{roleOptions.map((role) => (
										<SelectItem
											key={role.id}
											value={role.id}
											className="min-h-11"
										>
											{role.name}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</div>
					)}

					<div className="space-y-2">
						<p
							className="text-sm font-medium"
							id={`${formId}-mode`}
						>
							Tools
						</p>
						<RadioGroup
							aria-labelledby={`${formId}-mode`}
							value={mode}
							onValueChange={(v) => setMode(v as RuleMode)}
						>
							{(
								[
									["categories", "By Category"],
									["tools", "Selected Tools"],
									["all", "All Tools"],
								] as const
							).map(([value, label]) => (
								<div
									key={value}
									className="flex items-center gap-2"
								>
									<RadioGroupItem
										value={value}
										id={`${formId}-mode-${value}`}
									/>
									<Label
										htmlFor={`${formId}-mode-${value}`}
										className="flex min-h-11 cursor-pointer items-center"
									>
										{label}
									</Label>
								</div>
							))}
						</RadioGroup>
						{mode === "all" && (
							<p className="text-xs text-muted-foreground">
								Every tool, including dangerous ones such as raw
								requests, and any tool the server adds later.
							</p>
						)}
					</div>

					{mode === "categories" && (
						<div className="space-y-4">
							<div className="grid grid-cols-2 gap-x-4">
								{CATEGORIES.map((category) => (
									<div
										key={category}
										className="flex items-center gap-2"
									>
										<Checkbox
											id={`${formId}-cat-${category}`}
											checked={categories.includes(
												category,
											)}
											onCheckedChange={(checked) =>
												setCategories((prev) =>
													checked === true
														? [...prev, category]
														: prev.filter(
																(c) =>
																	c !==
																	category,
															),
												)
											}
										/>
										<Label
											htmlFor={`${formId}-cat-${category}`}
											className="flex min-h-11 cursor-pointer items-center"
										>
											{CATEGORY_LABELS[category]}
										</Label>
									</div>
								))}
							</div>
							<p className="text-xs text-muted-foreground">
								Dangerous tools belong to no category. Add them
								to Always Allow to grant them.
							</p>
							<div className="space-y-2">
								<Label htmlFor={`${formId}-allow`}>
									Always Allow
								</Label>
								<TagsInput
									id={`${formId}-allow`}
									aria-label="Always allow tool"
									value={allow}
									onChange={setAllow}
									validate={isKnownTool}
									errorMessage="Not a tool on this connection"
									placeholder="Tool name..."
								/>
							</div>
							<div className="space-y-2">
								<Label htmlFor={`${formId}-deny`}>
									Always Deny
								</Label>
								<TagsInput
									id={`${formId}-deny`}
									aria-label="Always deny tool"
									value={deny}
									onChange={setDeny}
									validate={isKnownTool}
									errorMessage="Not a tool on this connection"
									placeholder="Tool name..."
								/>
							</div>
						</div>
					)}

					{mode === "tools" &&
						(gateway.tools.length === 0 ? (
							<p className="text-sm text-muted-foreground">
								No tools cached. Refresh the catalog first.
							</p>
						) : (
							<ul
								aria-label="Selectable tools"
								className="min-w-0"
							>
								{gateway.tools.map((tool) => (
									<li
										key={tool.tool_name}
										className="flex items-center gap-2"
									>
										<Checkbox
											id={`${formId}-tool-${tool.tool_name}`}
											checked={selected.includes(
												tool.tool_name,
											)}
											onCheckedChange={(checked) =>
												setSelected((prev) =>
													checked === true
														? [
																...prev,
																tool.tool_name,
															]
														: prev.filter(
																(n) =>
																	n !==
																	tool.tool_name,
															),
												)
											}
										/>
										<Label
											htmlFor={`${formId}-tool-${tool.tool_name}`}
											className="flex min-h-11 min-w-0 flex-1 cursor-pointer items-center justify-between gap-2 font-mono text-sm [overflow-wrap:anywhere]"
										>
											{tool.tool_name}
											<CategoryBadge
												category={tool.category}
											/>
										</Label>
									</li>
								))}
							</ul>
						))}
				</fieldset>
				{error && (
					<p
						role="alert"
						className="shrink-0 text-sm text-destructive [overflow-wrap:anywhere]"
					>
						{error}
					</p>
				)}
				<DialogFooter className="shrink-0 [&_button]:min-h-11">
					<Button
						type="button"
						variant="outline"
						disabled={putGrant.isPending}
						onClick={onClose}
					>
						Cancel
					</Button>
					<Button
						type="button"
						disabled={putGrant.isPending}
						onClick={() => void handleSave()}
					>
						{putGrant.isPending ? "Saving..." : "Save Access"}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

function CategoryBadge({ category }: { category: GatewayTool["category"] }) {
	return (
		<Badge
			variant={category === "dangerous" ? "destructive" : "secondary"}
			className="shrink-0 font-sans"
		>
			{CATEGORY_LABELS[category]}
		</Badge>
	);
}

function GatewayToolAccess({ gateway }: { gateway: GatewayConnection }) {
	const roleNames = useMemo(
		() => new Map(gateway.grants.map((g) => [g.role_id, g.role_name])),
		[gateway.grants],
	);
	return (
		<section className="space-y-3" aria-labelledby="gateway-tool-access">
			<h3 id="gateway-tool-access" className="text-sm font-semibold">
				Tool Access
			</h3>
			{gateway.tools.length === 0 ? (
				<p className="text-sm text-muted-foreground">
					Access appears here once the tool catalog is refreshed.
				</p>
			) : (
				<ul aria-label="Gateway tool access" className="min-w-0">
					{gateway.tools.map((tool) => (
						<li
							key={tool.tool_name}
							className="flex flex-wrap items-center justify-between gap-2 border-b py-2 last:border-b-0"
						>
							<div className="min-w-0">
								<p className="font-mono text-sm [overflow-wrap:anywhere]">
									{tool.gateway_name ?? tool.tool_name}
								</p>
								<p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
									{!tool.enabled
										? "Disabled in the tool catalog"
										: tool.granted_role_ids.length > 0
											? tool.granted_role_ids
													.map(
														(id) =>
															roleNames.get(id) ??
															id,
													)
													.join(", ")
											: "No role has access"}
								</p>
							</div>
							<CategoryBadge category={tool.category} />
						</li>
					))}
				</ul>
			)}
		</section>
	);
}
