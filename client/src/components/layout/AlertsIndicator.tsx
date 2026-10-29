import { Link } from "react-router-dom";
import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useAlertCount, useAlertsLiveUpdates } from "@/services/alerts";

/** Shown only while something is broken: red with a count while alerts are open, muted once all are acknowledged. */
export function AlertsIndicator() {
	const count = useAlertCount();
	useAlertsLiveUpdates(true);

	const open = count.data?.open ?? 0;
	const unresolved = count.data?.unresolved ?? 0;
	if (unresolved === 0) return null;

	const label =
		open > 0
			? `${open} open ${open === 1 ? "alert" : "alerts"}`
			: `${unresolved} acknowledged ${unresolved === 1 ? "alert" : "alerts"}`;

	return (
		<Button asChild variant="ghost" size="icon-lg" className="relative" title={label}>
			<Link to="/alerts" aria-label={label}>
				<TriangleAlert className={cn("size-5", open > 0 ? "text-destructive" : "text-muted-foreground")} aria-hidden />
				{open > 0 && (
					<span className="absolute right-1 top-1 flex min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold leading-4 text-destructive-foreground">
						{open > 99 ? "99+" : open}
					</span>
				)}
			</Link>
		</Button>
	);
}
