import time
from pathlib import Path

import httpx
import yaml


def test_validate_all_sites():
    config_path = Path("config/sites.yaml")
    assert config_path.exists(), "config/sites.yaml missing"
    
    with open(config_path) as f:
        data = yaml.safe_load(f)
    
    sites = data.get("sites", [])
    print(f"Loaded {len(sites)} sites from config/sites.yaml")
    assert len(sites) == 20, f"Expected 20 sites, got {len(sites)}"
    
    url = "https://api.open-meteo.com/v1/forecast"
    passed = 0
    with httpx.Client(timeout=20.0) as client:
        for s in sites:
            params = {
                "latitude": s["latitude"],
                "longitude": s["longitude"],
                "hourly": "temperature_2m,relative_humidity_2m,precipitation",
                "past_days": 1,
                "forecast_days": 1
            }
            # Retry loop for resilient validation
            for attempt in range(3):
                try:
                    resp = client.get(url, params=params)
                    if resp.status_code == 200:
                        payload = resp.json()
                        assert "hourly" in payload
                        elevation = payload.get("elevation", "N/A")
                        print(f"[VERIFIED] {s['site_id']}: {s['name']} -> 200 OK ({elevation}m)")
                        passed += 1
                        break
                    time.sleep(0.5)
                except httpx.RequestError as exc:
                    if attempt == 2:
                        raise exc
                    time.sleep(1.0)
            time.sleep(0.2)  # Avoid burst quota limits

    print(f"\nAll {passed}/20 sites successfully verified against live Open-Meteo API!")
    assert passed == 20

if __name__ == "__main__":
    test_validate_all_sites()
