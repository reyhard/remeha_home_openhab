from api import get_config
from const import *

from click.testing import CliRunner
import click
import asyncio

from functools import wraps
from openhab import OpenHAB
import __main__ as main
from datetime import datetime, timedelta, date, timezone
from dateutil import parser
import sys
import logging
from remeha import set_time_program, return_schedule
from openhab_api import delete_rules_for_day, save_block_as_rule

# Initialize logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return asyncio.get_event_loop().run_until_complete(f(*args, **kwargs))
    return wrapper

def to_string_date(value):
    return value.strftime("%H:%M")

def merge_times(blocks):
    blocks = iter(blocks)
    merged = next(blocks).copy()
    for entry in blocks:
        start, end = entry['start'], entry['end']
        if start <= merged['end']:
            # overlapping, merge
            merged['end'] = max(merged['end'], end)
        else:
            # distinct; yield merged and start a new copy
            yield merged
            merged = entry.copy()
    yield merged

def get_alarm_time(openhab, item_name):
    item_alarm = openhab.get_item(item_name)
    try:
        alarm_timestamp = int(item_alarm.state) / 1000
        logger.debug(f"Alarm timestamp for {item_name}: {alarm_timestamp}")
        return datetime.fromtimestamp(alarm_timestamp)
    except Exception as e:
        logger.debug(f"No alarm or error getting alarm time for {item_name}: {e}")
        return None

def get_day(alarm):
    return alarm.strftime("%A").lower()

def check_alarm(openhab, day, alarm_time, homeoffice_item, vacations_item, heating_duration_default,
                zone_pre_heating, zone_heating_end, zones):
    try:
        alarm_max = alarm_time.replace(hour=12, minute=0)
        if alarm_time < alarm_max:
            alarm_time += timedelta(minutes=3)
            alarm_time -= timedelta(minutes=alarm_time.minute % 10,
                                    seconds=alarm_time.second,
                                    microseconds=alarm_time.microsecond)
            logger.debug(f"Adjusted alarm time: {alarm_time}")
            heating_start = alarm_time
            heating_duration = heating_duration_default
            if vacations_item:
                item_vacations_day = openhab.get_item(vacations_item + day.capitalize())
                if item_vacations_day.state == 'ON':
                    logger.info("Vacations detected - no heating will be scheduled.")
                    return []
            logger.debug(f"Home office item: {homeoffice_item}")
            if homeoffice_item and alarm_time.weekday() < 5:
                item_ho_day = openhab.get_item(homeoffice_item + day.capitalize())
                if item_ho_day.state == 'ON':
                    blocks_zones["bathroom"].append(
                        {"start": alarm_time - timedelta(minutes=zone_pre_heating),
                         "end": alarm_time + timedelta(minutes=heating_duration_default * 4)})
                    logger.info("Home office detected.")
                    for zone in zones:
                        blocks_zones[zone].append(
                            {"start": alarm_time - timedelta(minutes=zone_pre_heating),
                             "end": alarm_time.replace(hour=zone_heating_end, minute=0)})
                    heating_duration = 60 * 10
                else:
                    blocks_zones["bathroom"].append(
                        {"start": alarm_time - timedelta(minutes=zone_pre_heating), "end": alarm_time})
                    logger.debug(f"No home office detected. blocks_zones: {blocks_zones}")
                    alarm_time -= timedelta(minutes=heating_duration)
                    heating_start = alarm_time
            if alarm_time.weekday() >= 5:
                heating_duration = 60 * 3
            heating_end = alarm_time + timedelta(minutes=heating_duration)

            return [
                {
                    "start": heating_start,
                    "end": heating_end,
                }
            ]
        else:
            logger.info(f"Alarm time is late: {alarm_time}")
            return []
    except Exception as e:
        logger.info(f"No alarm or error during alarm check: {alarm_time} - {e}")
        return []

def sort_by_start(e):
    return e['start']

def add_block(block, blocks):
    schedule_zones[blocks].append(
        {
            "time": block['start'],
            "command": "ON"
        })
    if not (block['end'].hour == 23 and block['end'].minute == 59):
        schedule_zones[blocks].append(
            {
                "time": block['end'],
                "command": "OFF"
            })

blocks_zones = {
    "general": [],
    "bathroom": [],
    "bedroom": [],
    "livingroom": [],
    "kitchen": [],
}
schedule_zones = {
    "general": [],
    "bathroom": [],
    "bedroom": [],
    "livingroom": [],
    "kitchen": [],
}

zones_data = {
    "general": {"zoneName": "Zone1", "id": 'general', "name": 'Generalna',
                "itemState": 'Thermostat_HeatingZone_Control'},
    "kitchen": {"zoneName": "Zone2", "id": 'kitchen', "name": 'Kuchnia',
                "itemState": 'Thermostat_HeatingZone_Kitchen_State'},
    "livingroom": {"zoneName": "Zone3", "id": 'living-room', "name": 'Salon',
                   "itemState": 'Thermostat_HeatingZone_LivingRoom_State'},
    "bedroom": {"zoneName": "Zone4", "id": 'bedroom', "name": 'Sypialnia',
                "itemState": 'Thermostat_HeatingZone_Bedroom_State'},
    "bathroom": {"zoneName": "Zone5", "id": 'bathroom', "name": 'Łazienka',
                 "itemState": 'Thermostat_HeatingZone_Bathroom_State'},
}

## Main program
@click.group()
def cli():
    """
    Clock params
    """
    pass

@cli.command()
@coro
@click.option('--date',
              required=True,
              default=None,
              help=(('Primary alarm, '
                     'Alarm used for day calculation')))
async def set_alarm_heating(date):
    logger.info(f"Starting set_alarm_heating with date: {date}")
    settings = get_config(sys.path[0])
    base_url = settings['Openhab'].get('openhab_url', '')
    openhab = OpenHAB(base_url, None, None, None, 1)

    cleaned_datetime_str = date.split('[')[0]
    date_time = datetime.strptime(cleaned_datetime_str, "%Y-%m-%dt%H:%M%z").replace(tzinfo=timezone.utc)
    date_obj = date_time.date()
    day = get_day(date_obj).capitalize()
    logger.info(f"Calculated day: {day}")

    program = await return_schedule()
    program = program["switchPoints"]

    conversion_table = {
        "0": "Sunday",
        "1": "Monday",
        "2": "Tuesday",
        "3": "Wednesday",
        "4": "Thursday",
        "5": "Friday",
        "6": "Saturday"
    }

    program_processed = []

    for block in program:
        block_changed = block
        block_changed["day"] = conversion_table[str(block_changed["day"])]
        if day != block_changed["day"]:
            program_processed.append(
                {
                    "day": block_changed["day"],
                    "time": block_changed["time"],
                    "activity": block_changed["activity"]
                }
            )
    logger.debug(f"Processed program for other days: {program_processed}")

    alarms = [
        {'alarm': 'Phone_01_AlarmClock', 'alarm_time': '', 'homeoffice': 'HO_01_', 'vacations': 'Vacations_01_',
         'heating_duration': 20, "zone_pre_heating": 30, "zone_heating_end": 17, "zones": ["livingroom", "kitchen"]},
        {'alarm': 'Phone_02_AlarmClock', 'alarm_time': '', 'homeoffice': 'HO_02_', 'vacations': 'Vacations_02_',
         'heating_duration': 20, "zone_pre_heating": 0, "zone_heating_end": 17, "zones": ["bedroom", "general"]},
    ]
    schedule = []
    list_to_process = []
    for item in alarms:
        try:
            alarm_time = get_alarm_time(openhab, item['alarm'])
            item['alarm_time'] = alarm_time
            if alarm_time and alarm_time.date() == date_obj:
                logger.info(f"Adding alarm to process: {item['alarm']} with time {alarm_time}")
                list_to_process.append(item)
            else:
                logger.debug(f"Alarm {item['alarm']} not for today or not set.")
        except Exception:
            logger.exception(f"Error getting alarm time for {item['alarm']}")

    constant_heating_start = 17
    if list_to_process:
        blocks = []
        for alarm_process in list_to_process:
            blocks += check_alarm(openhab, day, alarm_process['alarm_time'], alarm_process['homeoffice'],
                                 alarm_process['vacations'], alarm_process['heating_duration'],
                                 alarm_process['zone_pre_heating'], alarm_process['zone_heating_end'],
                                 alarm_process['zones'])

        # add end of day block
        if date_time.weekday() >= 5:
            constant_heating_start = 9
        # add home office factor
        for item in alarms:
            try:
                item_ho_day = openhab.get_item(item['homeoffice'] + day.capitalize())
                logger.debug(f"Checking home office item: {item_ho_day.name} state: {item_ho_day.state}")
                if item_ho_day.state == 'ON':
                    constant_heating_start = 9
                    logger.info(f"Home office detected for {item['homeoffice']}")
                    for zone in item["zones"]:
                        blocks_zones[zone].append(
                            {"start": date_time.replace(hour=constant_heating_start, minute=00, tzinfo=None),
                             "end": date_time.replace(hour=17, minute=00, tzinfo=None)})

            except Exception:
                logger.debug("No HO detected during post-alarm processing.")
        blocks += [
            {
                "start": date_time.replace(hour=constant_heating_start, minute=00, tzinfo=None),
                "end": date_time.replace(hour=21, minute=00, tzinfo=None),
            }
        ]
        logger.debug(f"Initial blocks before merging: {blocks}")

        # A function that returns the 'year' value:
        # https://stackoverflow.com/questions/41931482/sorting-a-list-of-dictionary-values-by-date-and-time-in-python
        blocks.sort(key=sort_by_start)

        blocks = list(merge_times(blocks))
        logger.debug(f"Merged blocks for main heating: {blocks}")

        for block in blocks:
            schedule.append(
                {
                    "time": to_string_date(block['start']),
                    "day": day,
                    "activity": 4
                }
            )
            schedule.append(
                {
                    "time": to_string_date(block['end']),
                    "day": day,
                    "activity": 1
                }
            )
    else:
        # weekend scenario if there are no alarms
        if date_time.weekday() >= 5:
            schedule.append(
                {
                    "time": "9:00",
                    "day": day,
                    "activity": 2
                }
            )
        # turn of heating mark
        schedule.append(
            {
                "time": "21:00",
                "day": day,
                "activity": 1
            }
        )
    schedule += program_processed
    logger.info(f"Final schedule for main heating: {schedule}")
    await set_time_program(schedule)

    # handle zone blocks
    blocks_zones["livingroom"].append(
        {"start": date_time.replace(hour=constant_heating_start, minute=00, tzinfo=None),
         "end": date_time.replace(hour=23, minute=59, tzinfo=None)})
    blocks_zones["kitchen"].append(
        {"start": date_time.replace(hour=constant_heating_start, minute=00, tzinfo=None),
         "end": date_time.replace(hour=23, minute=59, tzinfo=None)})

    # special case so that heating during the weekend is not turned off and on
    # bathroom is also turned on
    if date_time.weekday() >= 5:
        blocks_zones["livingroom"].append(
            {"start": date_time.replace(hour=6, minute=00, tzinfo=None),
             "end": date_time.replace(hour=constant_heating_start, minute=59, tzinfo=None)})
        blocks_zones["kitchen"].append(
            {"start": date_time.replace(hour=6, minute=00, tzinfo=None),
             "end": date_time.replace(hour=constant_heating_start, minute=59, tzinfo=None)})
        blocks_zones["bathroom"].append(
            {"start": date_time.replace(hour=6, minute=00, tzinfo=None),
             "end": date_time.replace(hour=11, minute=00, tzinfo=None)})

    logger.debug(f"Initial blocks for zones: {blocks_zones}")
    for blocks in blocks_zones:
        blocks_proc = blocks_zones[blocks]
        blocks_proc.sort(key=sort_by_start)

        logger.debug(f"Sorted blocks for {blocks}: {blocks_proc}")
        if len(blocks_proc) > 1:
            blocks_zones[blocks] = list(merge_times(blocks_proc))
            for block in blocks_zones[blocks]:
                add_block(block, blocks)
        else:
            # make sure empty zones are disabled
            schedule_zones[blocks].append(
                {
                    "time": date_time.replace(hour=6, minute=00, tzinfo=None),
                    "command": "OFF"
                }
            )
            if len(blocks_proc) == 1:
                add_block(blocks_proc[0], blocks)

    for zone in zones_data:
        await delete_rules_for_day(zones_data[zone]['zoneName'], day)

    logger.debug(f"Final schedule for zones: {schedule_zones}")
    for schedule_zone in schedule_zones:
        index = 1
        for block in schedule_zones[schedule_zone]:
            save_block_as_rule(block, schedule_zone, zones_data, day, index)
            index += 1
    logger.info("Finished processing and setting heating schedule.")

if not hasattr(main, '__file__'):
    """
    Running in interactive mode in the Python shell
    """
    print("Running interactively in Python shell")

elif __name__ == '__main__':
    """
    CLI mode
    """
    cli()