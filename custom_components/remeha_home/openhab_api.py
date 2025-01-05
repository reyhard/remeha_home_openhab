import requests
import json
from datetime import datetime, timedelta, date, timezone
from typing import List, Dict, Any
from api import get_config
import sys

# Helper function for API requests
def fetch_api(endpoint, method='GET', headers=None, data=None):
    settings = get_config(sys.path[0])
    api_url = settings['Openhab'].get('openhab_url','')
    token = settings['Openhab'].get('openhab_token','')
    default_headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {token}',
    }
    merged_headers = {**default_headers, **(headers or {})}

    try:
        response = requests.request(method, f"{api_url}{endpoint}", headers=merged_headers, data=data)
        response.raise_for_status()  # Raise an exception for bad status codes

        if response.status_code == 204:  # No Content
            return None

        content_type = response.headers.get('Content-Type', '')
        if 'application/json' in content_type:
            return response.json()
        elif 'text/plain' in content_type:
            return response.text
        else:
            pass
            #raise Exception(f"Unsupported content type: {content_type}")
    except requests.exceptions.RequestException as e:
        print(f"API error: {e}")
        raise

# API functions
def save_rule(rule_data):
    return fetch_api("/rules", method='POST', data=json.dumps(rule_data))

def delete_rule(rule_id):
    return fetch_api(f"/rules/{rule_id}", method='DELETE')

def get_rules():
    return fetch_api("/rules")


def convert_datetime_to_cron(time: datetime.time, day: str) -> str:
    """
    Converts a datetime.time object and day of the week to a cron expression
    for triggering once per day every week.

    Args:
        time: A datetime.time object representing the time of day.
        day: A string representing the day of the week (e.g., "Monday", "Tuesday").

    Returns:
        A cron expression string suitable for OpenHAB's timer.GenericCronTrigger,
        or None if the day is invalid.
    """
    day_mapping = {
        "Monday": "MON",
        "Tuesday": "TUE",
        "Wednesday": "WED",
        "Thursday": "THU",
        "Friday": "FRI",
        "Saturday": "SAT",
        "Sunday": "SUN",
    }

    cron_day = day_mapping.get(day)
    if not cron_day:
        print(f"Error: Invalid day of the week: {day}")
        return None

    minutes = time.minute
    hours = time.hour

    cron_expression = f"0 {minutes} {hours} ? * {cron_day}"
    return cron_expression

def convert_cron_to_time(cron_expression: str) -> str:
    """Extracts and formats time (HH MM) from a cron expression."""
    parts = cron_expression.split()
    if len(parts) >= 3:
        minutes = parts[1]
        hours = parts[2]
        return f"{hours.zfill(2)} {minutes.zfill(2)}"  # Ensure leading zeros
    return ""

async def get_rules_for_day(zone: str, day: str, cached_rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Filters and sorts cached rules for a specific zone and day.

    Args:
        zone: The zone to filter for.
        day: The day to filter for.
        cached_rules: A list of cached rule dictionaries.

    Returns:
        A sorted list of rules for the specified zone and day.
    """
    try:
        day_rules = [
            rule for rule in cached_rules
            if isinstance(rule, dict) and rule.get('uid', '').startswith(f"schedule_{zone}_{day}")
        ]
        sorted_day_rules = sorted(day_rules, key=lambda rule: convert_cron_to_time(
            rule.get('triggers', [{}])[0].get('configuration', {}).get('cronExpression', "")
        ))
        return sorted_day_rules
    except Exception as error:
        print(f"Failed to fetch rules: {error}")
        return []

def save_block_as_rule(block, zone, zones_data, day, index):
    zone_data = zones_data.get(zone)

    cron_expression = convert_datetime_to_cron(block.get('time'), day)
    script_data = f"if(Thermostat_HeatingZone_Schedule.state == OFF) {{ return }}\n{zone_data['itemState']}.sendCommand({block['command']})"

    rule_data = {
        'uid': f"schedule_{zone_data['zoneName']}_{day}_{index}",
        'name': f"Heating Schedule for {zone_data.get('name')}, {day} - {block['command'].title()}",
        'description': block.get('command'),
        'tags': ["Schedule", "Heating"],
        'triggers': [{
            'id': "cron_trigger", 'label': "Cron Trigger", 'type': "timer.GenericCronTrigger", 'configuration': {'cronExpression': cron_expression}
        }],
        'actions': [{
            'id': "set_temperature", 'type': "script.ScriptAction", 'configuration': {'type': "application/vnd.openhab.dsl.rule", 'script': script_data}
        }]
    }
    try:
        save_rule(rule_data)
    except Exception as error:
        print(f"Failed to create rule: {error}")

async def delete_rules_for_day(zone_name, day):
    rules = await get_rules_for_day(zone_name, day, get_rules())
    for rule in rules:
      delete_rule(rule['uid'])

