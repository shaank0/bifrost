import { expect, test } from "@playwright/test";

test.describe("Failure alerts", () => {
	test("an admin sets up alert email and opens the alerts page", async ({
		page,
	}) => {
		await page.goto("/settings/alerts");
		await expect(page.getByText("Alert Email", { exact: true })).toBeVisible();

		await page.getByLabel("SMTP Server").fill("smtp.example.invalid");
		await page.getByLabel("From Address").fill("alerts@example.com");
		const recipients = page.getByLabel("Recipients");
		await recipients.fill("ops@example.com");
		await recipients.press("Enter");
		await page.getByLabel("Password").fill("app-password");
		await page.getByRole("switch", { name: "Send Alert Email" }).click();
		await page.getByRole("button", { name: "Save" }).click();
		await expect(page.getByText("Alert email settings saved")).toBeVisible();

		await page.reload();
		await expect(
			page.getByText("Saved. Type a new one to replace it."),
		).toBeVisible();
		await expect(page.getByLabel("SMTP Server")).toHaveValue(
			"smtp.example.invalid",
		);

		// Leave alert email off so other specs' failures don't try to send.
		await page.getByRole("switch", { name: "Send Alert Email" }).click();
		await page.getByRole("button", { name: "Save" }).click();
		await expect(page.getByText("Alert email settings saved")).toBeVisible();

		await page.getByRole("link", { name: "alert", exact: true }).click();
		await expect(page).toHaveURL(/\/alerts$/);
		await expect(
			page.getByRole("heading", { name: "Alerts", exact: true }),
		).toBeVisible();
		await expect(page.getByRole("tab", { name: "Unresolved" })).toBeVisible();
	});
});
