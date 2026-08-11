import asyncio
import json
from unittest.mock import Mock

from garmin_mcp import training


class CaptureApp:
    def __init__(self):
        self.tools = {}

    def tool(self, *args, **kwargs):
        def decorator(fn):
            name = kwargs.get("name") or fn.__name__
            self.tools[name] = fn
            return fn
        return decorator


def _get_hrv_tool(client):
    training.configure(client)
    app = CaptureApp()
    training.register_tools(app)
    return app.tools["get_hrv_data"]


def test_get_hrv_data_handles_null_baseline():
    client = Mock()
    client.get_hrv_data.return_value = {
        "hrvSummary": {
            "calendarDate": "2026-08-11",
            "lastNightAvg": 52,
            "lastNight5MinHigh": 73,
            "weeklyAvg": 58,
            "baseline": None,
            "status": "NONE",
            "feedbackPhrase": "ONBOARDING_1",
        },
        "sleepStartTimestampLocal": "2026-08-11T00:05:25.0",
        "sleepEndTimestampLocal": "2026-08-11T06:40:25.0",
    }

    tool = _get_hrv_tool(client)
    result = json.loads(asyncio.run(tool("2026-08-11")))

    assert result["last_night_avg_hrv_ms"] == 52
    assert result["weekly_avg_hrv_ms"] == 58
    assert result["status"] == "NONE"
    assert "baseline_balanced_low_ms" not in result


def test_get_hrv_data_handles_null_summary():
    client = Mock()
    client.get_hrv_data.return_value = {
        "hrvSummary": None,
        "sleepStartTimestampLocal": None,
        "sleepEndTimestampLocal": None,
    }

    tool = _get_hrv_tool(client)
    result = json.loads(asyncio.run(tool("2026-08-11")))

    assert result == {"date": "2026-08-11"}
