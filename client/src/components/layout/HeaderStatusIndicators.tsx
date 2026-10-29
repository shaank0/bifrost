import { GLOBAL_TARGET } from "@/lib/authorization";
import { useAuthorization } from "@/services/authorization";
import { useFeatureEnabled } from "@/services/platformFeatures";
import { VersionUpdateBanner } from "./VersionUpdateBanner";
import { FileActivityIndicator } from "./FileActivityIndicator";
import { AlertsIndicator } from "./AlertsIndicator";

export function HeaderStatusIndicators() {
	const authorization = useAuthorization();
	const canReadActivity = authorization.canAt("platform.read", GLOBAL_TARGET);
	const alertsOn = useFeatureEnabled("alerts", canReadActivity);

	return (
		<>
			<VersionUpdateBanner />
			{canReadActivity && <FileActivityIndicator />}
			{canReadActivity && alertsOn && <AlertsIndicator />}
		</>
	);
}
