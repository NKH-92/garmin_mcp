"""Read-only Garmin race calendar tools."""

from __future__ import annotations

from datetime import date, timedelta
import json
from typing import Any, Optional


garmin_client = None


def configure(client):
    """Configure the module with the Garmin client instance."""
    global garmin_client
    garmin_client = client


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _target(target: Any) -> Optional[dict[str, Any]]:
    if not isinstance(target, dict):
        return None
    value = _number(target.get("value"))
    if value is None:
        return None
    return {
        "value": value,
        "unit": target.get("unit"),
        "unit_type": target.get("unitType"),
    }


def _distance_meters(target: Optional[dict[str, Any]]) -> Optional[float]:
    if not target:
        return None
    unit = str(target.get("unit") or "").strip().lower()
    unit_type = str(target.get("unit_type") or "").strip().lower()
    distance_units = {"m", "meter", "meters", "metre", "metres"}
    distance_units |= {"km", "kilometer", "kilometers", "kilometre", "kilometres"}
    distance_units |= {"mi", "mile", "miles"}
    if unit_type not in {"distance", ""} and unit not in distance_units:
        return None
    value = target["value"]
    if unit in {"km", "kilometer", "kilometers", "kilometre", "kilometres"}:
        return value * 1000
    if unit in {"mi", "mile", "miles"}:
        return value * 1609.344
    if unit in {"m", "meter", "meters", "metre", "metres"}:
        return value
    return value if unit_type == "distance" else None


def _time_seconds(target: Optional[dict[str, Any]]) -> Optional[int]:
    if not target:
        return None
    unit = str(target.get("unit") or "").strip().lower()
    unit_type = str(target.get("unit_type") or "").strip().lower()
    value = target["value"]
    if unit in {"millisecond", "milliseconds", "ms"}:
        return round(value / 1000)
    if unit in {"minute", "minutes", "min"}:
        return round(value * 60)
    if unit in {"hour", "hours", "h"}:
        return round(value * 3600)
    if unit in {"second", "seconds", "sec", "s"} or unit_type == "time":
        return round(value)
    return None


def _format_duration(seconds: int) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _priority(event: dict[str, Any]) -> tuple[str, str]:
    customization = event.get("eventCustomization") or {}
    if not isinstance(customization, dict):
        customization = {}

    explicit_values = [
        event.get("priority"),
        event.get("eventPriority"),
        event.get("trainingPriority"),
        customization.get("priority"),
        customization.get("eventPriority"),
        event.get("statuses"),
    ]
    explicit = " ".join(str(value).upper() for value in explicit_values if value)
    if "PRIMARY" in explicit or customization.get("isPrimaryEvent") or event.get("primaryEvent"):
        return "A", "PRIMARY"
    if "SUPPORT" in explicit or customization.get("isTrainingEvent"):
        return "B", "SUPPORTING"
    return "C", "NO_PRIORITY"


def _course_summary(event: dict[str, Any]) -> dict[str, Any]:
    course_id = event.get("courseId")
    course = {
        "has_course": course_id is not None,
        "course_id": course_id,
        "name": event.get("courseName"),
    }
    return {key: value for key, value in course.items() if value is not None}


def _enrich_course(course: dict[str, Any], cache: dict[Any, Optional[dict]]) -> dict[str, Any]:
    course_id = course.get("course_id")
    if course_id is None:
        return course
    if course_id not in cache:
        try:
            data = garmin_client.connectapi(f"/course-service/course/{course_id}")
            cache[course_id] = data if isinstance(data, dict) else None
        except Exception:
            cache[course_id] = None

    data = cache[course_id]
    if not data:
        return course

    start = data.get("startPoint") or {}
    details = {
        "name": course.get("name") or data.get("courseName"),
        "distance_m": data.get("distanceMeter") or data.get("distanceInMeters"),
        "elevation_gain_m": data.get("elevationGainMeter") or data.get("elevationGainInMeters"),
        "elevation_loss_m": data.get("elevationLossMeter") or data.get("elevationLossInMeters"),
        "activity": (data.get("activityType") or {}).get("typeKey"),
        "start_latitude": start.get("latitude"),
        "start_longitude": start.get("longitude"),
    }
    course.update({key: value for key, value in details.items() if value is not None})
    return course


def _curate_race(
    event: dict[str, Any],
    reference_date: date,
    include_course_details: bool,
    course_cache: dict[Any, Optional[dict]],
) -> Optional[dict[str, Any]]:
    if not (event.get("race") or event.get("isRace")):
        return None

    date_text = event.get("date") or event.get("eventDate")
    try:
        event_date = date.fromisoformat(str(date_text)[:10])
    except (TypeError, ValueError):
        event_date = None

    distance_target = _target(event.get("completionTarget"))
    customization = event.get("eventCustomization") or {}
    if not isinstance(customization, dict):
        customization = {}
    goal_target = _target(customization.get("customGoal"))
    goal_seconds = _time_seconds(goal_target)
    distance_m = _distance_meters(distance_target)
    priority_abc, priority_garmin = _priority(event)

    course = _course_summary(event)
    if include_course_details:
        course = _enrich_course(course, course_cache)

    event_time = event.get("eventTimeLocal") or {}
    race = {
        "event_id": event.get("id"),
        "event_uuid": event.get("shareableEventUuid"),
        "name": event.get("eventName") or event.get("title"),
        "date": event_date.isoformat() if event_date else date_text,
        "days_until": (event_date - reference_date).days if event_date else None,
        "event_type": event.get("eventType") or event.get("sportTypeKey"),
        "location": event.get("location"),
        "start_time_local": event_time.get("startTimeHhMm") if isinstance(event_time, dict) else None,
        "time_zone": event_time.get("timeZoneId") if isinstance(event_time, dict) else None,
        "distance_m": round(distance_m, 3) if distance_m is not None else None,
        "distance_km": round(distance_m / 1000, 3) if distance_m is not None else None,
        "goal_time_seconds": goal_seconds,
        "goal_time": _format_duration(goal_seconds) if goal_seconds is not None else None,
        "priority": priority_abc,
        "priority_garmin": priority_garmin,
        "course": course,
        "event_url": event.get("url"),
        "registration_url": event.get("registrationUrl"),
        "training_plan_id": customization.get("trainingPlanId"),
    }
    return {key: value for key, value in race.items() if value is not None}


def register_tools(app):
    """Register race-calendar tools."""

    @app.tool()
    async def get_race_calendar(
        days_forward: int = 365,
        reference_date: Optional[str] = None,
        include_course_details: bool = True,
    ) -> str:
        """Get upcoming race events from the Garmin Connect calendar.

        Returns each race's name, date, D-day, sport, distance, target time,
        priority and linked course. Garmin priority is also normalized to A/B/C:
        Primary=A, Supporting=B, and No priority=C. This is a read-only tool.

        Args:
            days_forward: Future lookup window from 1 to 365 days.
            reference_date: Date used for D-day in YYYY-MM-DD. Defaults to today.
            include_course_details: Include distance/elevation/start metadata for linked courses.
        """
        try:
            if not 1 <= days_forward <= 365:
                raise ValueError("days_forward must be between 1 and 365")
            effective_date = date.fromisoformat(reference_date) if reference_date else date.today()
            params = {"numDaysForward": str(days_forward), "limit": "100"}
            events = garmin_client.connectapi(
                "/calendar-service/events/upcoming", params=params
            )
            if not isinstance(events, list):
                raise ValueError("Garmin returned an unexpected race calendar response")

            course_cache: dict[Any, Optional[dict]] = {}
            races = [
                race
                for event in events
                if isinstance(event, dict)
                for race in [
                    _curate_race(
                        event,
                        effective_date,
                        include_course_details,
                        course_cache,
                    )
                ]
                if race is not None
            ]
            races.sort(key=lambda race: str(race.get("date") or ""))
            payload = {
                "reference_date": effective_date.isoformat(),
                "range_end": (effective_date + timedelta(days=days_forward)).isoformat(),
                "count": len(races),
                "races": races,
            }
            return json.dumps(payload, ensure_ascii=False, indent=2)
        except Exception as exc:
            return f"Error retrieving race calendar: {str(exc)}"

    return app
