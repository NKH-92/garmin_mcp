"""Integration tests for the read-only race calendar tool."""

import json

import pytest
from mcp.server.fastmcp import FastMCP

from garmin_mcp import race_calendar


@pytest.fixture
def app_with_race_calendar(mock_garmin_client):
    race_calendar.configure(mock_garmin_client)
    app = FastMCP("Test Race Calendar")
    return race_calendar.register_tools(app)


def _event(**overrides):
    event = {
        "id": 1001,
        "eventName": "Seoul Marathon",
        "date": "2026-11-01",
        "eventType": "running",
        "location": "Seoul",
        "race": True,
        "courseId": 7001,
        "courseName": "Seoul Marathon Course",
        "shareableEventUuid": "race-uuid",
        "completionTarget": {
            "value": 42195,
            "unit": "meter",
            "unitType": "distance",
        },
        "eventTimeLocal": {
            "startTimeHhMm": "08:00",
            "timeZoneId": "Asia/Seoul",
        },
        "eventCustomization": {
            "customGoal": {
                "value": 12600,
                "unit": "second",
                "unitType": "time",
            },
            "isPrimaryEvent": True,
            "isTrainingEvent": True,
            "trainingPlanId": 9001,
        },
    }
    event.update(overrides)
    return event


@pytest.mark.asyncio
async def test_get_race_calendar_curates_goal_priority_and_course(
    app_with_race_calendar,
    mock_garmin_client,
):
    def connectapi(url, params=None):
        if url == "/calendar-service/events/upcoming":
            assert params == {"numDaysForward": "365", "limit": "100"}
            return [_event(), {"eventName": "Social Run", "race": False}]
        if url == "/course-service/course/7001":
            return {
                "courseName": "Seoul Marathon Course",
                "distanceMeter": 42195,
                "elevationGainMeter": 210,
                "elevationLossMeter": 205,
                "activityType": {"typeKey": "running"},
                "startPoint": {"latitude": 37.5, "longitude": 127.0},
            }
        raise AssertionError(f"unexpected URL: {url}")

    mock_garmin_client.connectapi.side_effect = connectapi
    result = await app_with_race_calendar.call_tool(
        "get_race_calendar",
        {"reference_date": "2026-08-11"},
    )
    payload = json.loads(result[0][0].text)

    assert payload["count"] == 1
    race = payload["races"][0]
    assert race["name"] == "Seoul Marathon"
    assert race["days_until"] == 82
    assert race["distance_km"] == 42.195
    assert race["goal_time"] == "03:30:00"
    assert race["priority"] == "A"
    assert race["priority_garmin"] == "PRIMARY"
    assert race["course"]["elevation_gain_m"] == 210
    assert race["course"]["start_latitude"] == 37.5


@pytest.mark.asyncio
async def test_get_race_calendar_maps_supporting_and_no_priority(
    app_with_race_calendar,
    mock_garmin_client,
):
    supporting = _event(
        id=2,
        eventName="Supporting 10K",
        courseId=None,
        eventCustomization={"isPrimaryEvent": False, "isTrainingEvent": True},
    )
    no_priority = _event(
        id=3,
        eventName="Tune-up 5K",
        courseId=None,
        eventCustomization={"isPrimaryEvent": False, "isTrainingEvent": False},
    )
    mock_garmin_client.connectapi.return_value = [supporting, no_priority]

    result = await app_with_race_calendar.call_tool(
        "get_race_calendar",
        {"reference_date": "2026-08-11", "include_course_details": False},
    )
    races = json.loads(result[0][0].text)["races"]

    assert [(race["priority"], race["priority_garmin"]) for race in races] == [
        ("B", "SUPPORTING"),
        ("C", "NO_PRIORITY"),
    ]


@pytest.mark.asyncio
async def test_get_race_calendar_validates_lookup_window(
    app_with_race_calendar,
    mock_garmin_client,
):
    result = await app_with_race_calendar.call_tool(
        "get_race_calendar", {"days_forward": 366}
    )

    assert "days_forward must be between 1 and 365" in result[0][0].text
    mock_garmin_client.connectapi.assert_not_called()
