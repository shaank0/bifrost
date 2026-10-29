import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { AlertCircle, BellOff, Check, CheckCheck, CircleCheck, Settings, TriangleAlert } from "lucide-react";
import { ListPageHeader } from "@/components/layout/ListPageHeader";
import { PageScrollArea, PageWorkspace } from "@/components/layout/PageWorkspace";
import { Alert as Callout, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { GLOBAL_TARGET } from "@/lib/authorization";
import { formatDate, formatRelativeTime } from "@/lib/utils";
import {
	type Alert,
	type AlertView,
	useAcknowledgeAlert,
	useAlerts,
	useAlertsLiveUpdates,
	useResolveAlert,
} from "@/services/alerts";
import { useAuthorization } from "@/services/authorization";
import { useFeatureEnabled, usePlatformFeatures } from "@/services/platformFeatures";

const VIEWS: { value: AlertView; label: string }[] = [
	{ value: "unresolved", label: "Unresolved" },
	{ value: "resolved", label: "Resolved" },
];

export function Alerts() {
	const [view, setView] = useState<AlertView>("unresolved");
	const alerts = useAlerts(view);
	const { canAt } = useAuthorization();
	const canManage = canAt("platform.readwrite", GLOBAL_TARGET);
	const canConfigure = canAt("settings.read", GLOBAL_TARGET);
	const features = usePlatformFeatures();
	const featureOn = useFeatureEnabled("alerts");
	useAlertsLiveUpdates(featureOn);

	const items = alerts.data?.items ?? [];

	if (features.data && !featureOn) {
		return (
			<PageWorkspace className="mx-auto flex min-w-0 max-w-[1100px] flex-col gap-6">
				<ListPageHeader title="Alerts" />
				<EmptyState
					icon={BellOff}
					title="Failure Alerts Is Off"
					description="Turn it on under Settings → Features to be told when a scheduled or event-triggered workflow fails, or an integration needs reconnecting."
					action={
						canConfigure && (
							<Button asChild>
								<Link to="/settings/features">Open Features</Link>
							</Button>
						)
					}
				/>
			</PageWorkspace>
		);
	}

	return (
		<PageWorkspace className="mx-auto flex min-w-0 max-w-[1100px] flex-col gap-6">
			<div className="shrink-0 space-y-4">
				<ListPageHeader
					title="Alerts"
					description="Scheduled and event-triggered workflows that failed after their last retry, and integrations that need reconnecting. An alert clears itself the next time its workflow or integration succeeds."
					actions={
						canConfigure && (
							<Button asChild variant="outline">
								<Link to="/settings/alerts">
									<Settings className="size-4" aria-hidden />
									Alert Email
								</Link>
							</Button>
						)
					}
				/>
				<Tabs value={view} onValueChange={(v) => setView(v as AlertView)}>
					<TabsList>
						{VIEWS.map((v) => (
							<TabsTrigger key={v.value} value={v.value}>
								{v.label}
							</TabsTrigger>
						))}
					</TabsList>
				</Tabs>
			</div>
			<PageScrollArea>
				{alerts.error ? (
					<Callout variant="destructive">
						<AlertCircle className="size-4" aria-hidden />
						<AlertDescription>Couldn't load alerts. Try refreshing the page.</AlertDescription>
					</Callout>
				) : alerts.isLoading ? (
					<div className="space-y-3" aria-label="Loading alerts">
						<Skeleton className="h-24 w-full" />
						<Skeleton className="h-24 w-full" />
					</div>
				) : items.length === 0 ? (
					<EmptyState
						icon={CircleCheck}
						title={view === "unresolved" ? "Nothing Needs Attention" : "No Resolved Alerts"}
						description={
							view === "unresolved"
								? "Every scheduled and event-triggered workflow's last run succeeded, and no integration needs reconnecting."
								: "Alerts move here once their workflow or integration succeeds again, or someone resolves them."
						}
					/>
				) : (
					<ul className="space-y-3" aria-label="Alerts">
						{items.map((alert) => (
							<AlertRow key={alert.id} alert={alert} canManage={canManage} />
						))}
					</ul>
				)}
			</PageScrollArea>
		</PageWorkspace>
	);
}

function AlertRow({ alert, canManage }: { alert: Alert; canManage: boolean }) {
	const acknowledge = useAcknowledgeAlert();
	const resolve = useResolveAlert();
	const busy = acknowledge.isPending || resolve.isPending;
	const params = { params: { path: { alert_id: alert.id } } };

	async function run(action: "acknowledge" | "resolve") {
		try {
			await (action === "acknowledge" ? acknowledge : resolve).mutateAsync(params);
		} catch {
			toast.error(`Couldn't ${action} the alert`);
		}
	}

	const link =
		alert.kind === "workflow_failed" && alert.last_execution_id
			? { to: `/history/${alert.last_execution_id}`, label: "View Last Run" }
			: alert.kind === "integration_refresh_failed" && alert.integration_id
				? { to: `/integrations/${alert.integration_id}`, label: "Open Integration" }
				: null;

	return (
		<li className="rounded-lg border border-border bg-card p-4">
			<div className="flex flex-wrap items-start justify-between gap-3">
				<div className="min-w-0 flex-1 space-y-1">
					<div className="flex flex-wrap items-center gap-2">
						{alert.status !== "resolved" && (
							<TriangleAlert
								className={alert.status === "open" ? "size-4 text-destructive" : "size-4 text-muted-foreground"}
								aria-hidden
							/>
						)}
						<h2 className="font-medium">{alert.title}</h2>
						<StatusBadge alert={alert} />
						{alert.organization_name && <Badge variant="outline">{alert.organization_name}</Badge>}
					</div>
					<p className="break-words text-sm text-muted-foreground">{alert.detail}</p>
					<p className="text-xs text-muted-foreground">
						{alert.occurrences > 1 ? `${alert.occurrences} times since ` : "First seen "}
						<time dateTime={alert.first_seen_at} title={formatDate(alert.first_seen_at)}>
							{formatRelativeTime(alert.first_seen_at)}
						</time>
						{alert.occurrences > 1 && (
							<>
								{" · last "}
								<time dateTime={alert.last_seen_at} title={formatDate(alert.last_seen_at)}>
									{formatRelativeTime(alert.last_seen_at)}
								</time>
							</>
						)}
						{alert.acknowledged_by && ` · acknowledged by ${alert.acknowledged_by}`}
						{alert.emailed_at && " · emailed"}
					</p>
				</div>
				<div className="flex flex-wrap items-center gap-2">
					{link && (
						<Button asChild variant="ghost" size="sm">
							<Link to={link.to}>{link.label}</Link>
						</Button>
					)}
					{canManage && alert.status === "open" && (
						<Button variant="outline" size="sm" onClick={() => run("acknowledge")} disabled={busy}>
							<Check className="size-4" aria-hidden />
							Acknowledge
						</Button>
					)}
					{canManage && alert.status !== "resolved" && (
						<Button
							variant="ghost"
							size="sm"
							onClick={() => run("resolve")}
							disabled={busy}
							title="For a workflow or integration that won't run again"
						>
							<CheckCheck className="size-4" aria-hidden />
							Resolve
						</Button>
					)}
				</div>
			</div>
		</li>
	);
}

function StatusBadge({ alert }: { alert: Alert }) {
	if (alert.status === "open") return <Badge variant="destructive">Open</Badge>;
	if (alert.status === "acknowledged") return <Badge variant="secondary">Acknowledged</Badge>;
	return <Badge variant="outline">Resolved</Badge>;
}
