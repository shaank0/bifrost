import { useState } from "react";
import { Link } from "react-router-dom";
import { Loader2, Send } from "lucide-react";
import { toast } from "sonner";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { TagsInput } from "@/components/ui/tags-input";
import { SettingsToggleRow } from "@/components/shared/SettingsToggleRow";
import { SettingsLoadError } from "@/components/shared/SettingsLoadError";
import { GLOBAL_TARGET } from "@/lib/authorization";
import {
	type AlertEmailSettings,
	type AlertEmailSettingsRequest,
	useAlertEmailSettings,
	useSendTestAlertEmail,
	useUpdateAlertEmailSettings,
} from "@/services/alerts";
import { useAuthorization } from "@/services/authorization";

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const DEFAULT_PORT = { starttls: 587, ssl: 465, none: 25 } as const;

/** The API's error body (`{ detail }`) or a thrown Error, as text. */
export function errorText(error: unknown, fallback: string): string {
	if (error && typeof error === "object" && "detail" in error && typeof error.detail === "string") {
		return error.detail;
	}
	return error instanceof Error ? error.message : fallback;
}

export function AlertsSettings() {
	const settings = useAlertEmailSettings();
	const { refetch } = settings;
	if (settings.error) {
		return <SettingsLoadError name="alert email settings" onRetry={() => refetch()} />;
	}
	if (!settings.data) {
		return (
			<div className="flex items-center gap-2 text-sm text-muted-foreground">
				<Loader2 className="size-4 animate-spin" aria-hidden />
				Loading alert email settings…
			</div>
		);
	}
	return <AlertEmailForm key={JSON.stringify(settings.data)} saved={settings.data} />;
}

function AlertEmailForm({ saved }: { saved: AlertEmailSettings }) {
	const { canAt } = useAuthorization();
	const canWrite = canAt("settings.readwrite", GLOBAL_TARGET);
	const update = useUpdateAlertEmailSettings();
	const sendTest = useSendTestAlertEmail();
	const [form, setForm] = useState<AlertEmailSettingsRequest>({
		enabled: saved.enabled ?? false,
		host: saved.host ?? "",
		port: saved.port ?? 587,
		security: saved.security ?? "starttls",
		username: saved.username ?? "",
		password: null,
		from_address: saved.from_address ?? "",
		recipients: saved.recipients ?? [],
	});
	const set = <K extends keyof AlertEmailSettingsRequest>(key: K, value: AlertEmailSettingsRequest[K]) =>
		setForm((f) => ({ ...f, [key]: value }));
	const disabled = !canWrite || update.isPending;

	async function save() {
		try {
			await update.mutateAsync({ body: form });
			toast.success("Alert email settings saved");
		} catch (error) {
			toast.error("Couldn't save alert email settings", { description: errorText(error, "Unknown error") });
		}
	}

	async function test() {
		try {
			const result = await sendTest.mutateAsync({});
			toast.success("Test email sent", { description: `Sent to ${result.sent_to.join(", ")}` });
		} catch (error) {
			toast.error("Test email failed", { description: errorText(error, "Unknown error") });
		}
	}

	return (
		<Card>
			<CardHeader>
				<CardTitle>Alert Email</CardTitle>
				<CardDescription>
					Email these people when a new <Link to="/alerts" className="underline">alert</Link> opens: a
					scheduled or event-triggered workflow that failed after its last retry, or an integration that needs
					reconnecting. One email per alert, not per failure. This uses the platform's own mail server, so it
					still works when a client's email integration is what broke.
				</CardDescription>
			</CardHeader>
			<CardContent className="space-y-6">
				<SettingsToggleRow
					id="alert-email-enabled"
					label="Send Alert Email"
					description="Off: alerts still show in Bifrost, but nobody is emailed."
					checked={form.enabled}
					disabled={disabled}
					onChange={(v) => set("enabled", v)}
				/>
				<div className="grid gap-4 sm:grid-cols-[1fr_8rem_10rem]">
					<Field id="smtp-host" label="SMTP Server">
						<Input
							id="smtp-host"
							value={form.host}
							onChange={(e) => set("host", e.target.value)}
							placeholder="smtp.office365.com"
							disabled={disabled}
						/>
					</Field>
					<Field id="smtp-port" label="Port">
						<Input
							id="smtp-port"
							type="number"
							min={1}
							max={65535}
							value={form.port}
							onChange={(e) => set("port", Number(e.target.value))}
							disabled={disabled}
						/>
					</Field>
					<Field id="smtp-security" label="Security">
						<Select
							value={form.security}
							onValueChange={(v) => {
								const security = v as AlertEmailSettingsRequest["security"] & keyof typeof DEFAULT_PORT;
								setForm((f) => ({ ...f, security, port: DEFAULT_PORT[security] }));
							}}
							disabled={disabled}
						>
							<SelectTrigger id="smtp-security" className="w-full">
								<SelectValue />
							</SelectTrigger>
							<SelectContent>
								<SelectItem value="starttls">STARTTLS</SelectItem>
								<SelectItem value="ssl">SSL/TLS</SelectItem>
								<SelectItem value="none">None</SelectItem>
							</SelectContent>
						</Select>
					</Field>
				</div>
				<div className="grid gap-4 sm:grid-cols-2">
					<Field id="smtp-username" label="Username" hint="Leave empty for a relay that doesn't sign in.">
						<Input
							id="smtp-username"
							value={form.username}
							onChange={(e) => set("username", e.target.value)}
							autoComplete="off"
							disabled={disabled}
						/>
					</Field>
					<Field
						id="smtp-password"
						label="Password"
						hint={saved.password_set ? "Saved. Type a new one to replace it." : "Not set."}
					>
						<Input
							id="smtp-password"
							type="password"
							value={form.password ?? ""}
							onChange={(e) => set("password", e.target.value === "" ? null : e.target.value)}
							placeholder={saved.password_set ? "••••••••" : ""}
							autoComplete="new-password"
							disabled={disabled}
						/>
					</Field>
				</div>
				<Field id="smtp-from" label="From Address">
					<Input
						id="smtp-from"
						type="email"
						value={form.from_address}
						onChange={(e) => set("from_address", e.target.value)}
						placeholder="alerts@yourcompany.com"
						disabled={disabled}
					/>
				</Field>
				<Field id="smtp-recipients" label="Recipients" hint="Press Enter after each address.">
					<TagsInput
						id="smtp-recipients"
						aria-label="Recipients"
						value={form.recipients ?? []}
						onChange={(v) => set("recipients", v)}
						validate={(v) => EMAIL.test(v)}
						errorMessage="Enter an email address"
					/>
				</Field>
				{canWrite && (
					<div className="flex flex-wrap gap-2">
						<Button onClick={save} disabled={disabled}>
							{update.isPending && <Loader2 className="size-4 animate-spin" aria-hidden />}
							Save
						</Button>
						<Button
							variant="outline"
							onClick={test}
							disabled={!saved.enabled || sendTest.isPending}
							title={saved.enabled ? undefined : "Turn alert email on and save first"}
						>
							{sendTest.isPending ? (
								<Loader2 className="size-4 animate-spin" aria-hidden />
							) : (
								<Send className="size-4" aria-hidden />
							)}
							Send Test Email
						</Button>
					</div>
				)}
			</CardContent>
		</Card>
	);
}

function Field({
	id,
	label,
	hint,
	children,
}: {
	id: string;
	label: string;
	hint?: string;
	children: React.ReactNode;
}) {
	return (
		<div className="space-y-1.5">
			<Label htmlFor={id}>{label}</Label>
			{children}
			{hint && <p className="text-xs text-muted-foreground">{hint}</p>}
		</div>
	);
}
