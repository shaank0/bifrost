"""Optional platform features are off until a platform admin turns them on."""

import pytest

pytestmark = pytest.mark.e2e


class TestPlatformFeaturesApi:
    def test_features_start_off_and_an_admin_switches_them(self, e2e_client, platform_admin):
        headers = platform_admin.headers
        listed = e2e_client.get("/api/settings/features", headers=headers)
        assert listed.status_code == 200, listed.text
        alerts = {f["key"]: f for f in listed.json()["features"]}["alerts"]
        assert (alerts["enabled"], alerts["label"]) == (False, "Failure Alerts")

        on = e2e_client.put("/api/settings/features", headers=headers, json={"enabled": {"alerts": True}})
        assert on.status_code == 200, on.text
        assert {f["key"]: f["enabled"] for f in on.json()["features"]}["alerts"] is True

        off = e2e_client.put("/api/settings/features", headers=headers, json={"enabled": {"alerts": False}})
        assert {f["key"]: f["enabled"] for f in off.json()["features"]}["alerts"] is False

    def test_an_unknown_feature_is_refused(self, e2e_client, platform_admin):
        response = e2e_client.put(
            "/api/settings/features", headers=platform_admin.headers, json={"enabled": {"time_travel": True}}
        )
        assert response.status_code == 422
        assert "time_travel" in response.text

    def test_an_organization_user_cannot_switch_features(self, e2e_client, org1_user):
        response = e2e_client.put("/api/settings/features", headers=org1_user.headers, json={"enabled": {"alerts": True}})
        assert response.status_code == 403
