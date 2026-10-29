import { useState } from "react";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { SettingsLoadError } from "@/components/shared/SettingsLoadError";
import { SettingsToggleRow } from "@/components/shared/SettingsToggleRow";
import { getErrorMessage } from "@/lib/api-error";
import { GLOBAL_TARGET } from "@/lib/authorization";
import { useAuthorization } from "@/services/authorization";
import { usePlatformFeatures, useUpdatePlatformFeatures } from "@/services/platformFeatures";

export function FeaturesSettings() {
	const features = usePlatformFeatures();
	const { refetch } = features;
	const update = useUpdatePlatformFeatures();
	const { canAt } = useAuthorization();
	const canWrite = canAt("settings.readwrite", GLOBAL_TARGET);
	const [saving, setSaving] = useState<string | null>(null);

	async function toggle(key: string, label: string, enabled: boolean) {
		setSaving(key);
		try {
			await update.mutateAsync({ body: { enabled: { [key]: enabled } } });
			toast.success(`${label} turned ${enabled ? "on" : "off"}`);
		} catch (error) {
			toast.error(`Couldn't change ${label}`, { description: getErrorMessage(error, "Unknown error") });
		} finally {
			setSaving(null);
		}
	}

	if (features.error) {
		return <SettingsLoadError name="platform features" onRetry={() => refetch()} />;
	}
	return (
		<Card>
			<CardHeader>
				<CardTitle>Features</CardTitle>
				<CardDescription>
					Optional parts of Bifrost. Each is off until you turn it on here, and a feature that is off does
					nothing and stays out of the way.
				</CardDescription>
			</CardHeader>
			<CardContent className="space-y-6">
				{!features.data ? (
					<div className="flex items-center gap-2 text-sm text-muted-foreground">
						<Loader2 className="size-4 animate-spin" aria-hidden />
						Loading features…
					</div>
				) : (
					features.data.features.map((feature) => (
						<SettingsToggleRow
							key={feature.key}
							id={`feature-${feature.key}`}
							label={feature.label}
							description={feature.description}
							checked={feature.enabled}
							disabled={!canWrite || saving !== null}
							busy={saving === feature.key ? "saving" : undefined}
							onChange={(on) => toggle(feature.key, feature.label, on)}
						/>
					))
				)}
			</CardContent>
		</Card>
	);
}
