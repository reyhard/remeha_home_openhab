
from api import RemehaHomeOAuth2Implementation, RemehaHomeAPI, OAuth2Session, get_config
from const import *

from click.testing import CliRunner
import click
import asyncio

from functools import wraps
from openhab import OpenHAB
import __main__ as main
import time
from datetime import datetime, timedelta, date
import sys
from remeha import set_time_program, return_schedule

def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        print(args)
        return asyncio.get_event_loop().run_until_complete(f(*args, **kwargs))
    return wrapper

def to_time(string):
  return time.strptime(string,"%H:%M")

def to_string(value):
  print(value)
  return time.strftime("%H:%M",value)

def to_string_date(value):
  print(value)
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

def get_alarm_time(openhab,item_name):
  item_alarm = openhab.get_item(item_name)
  try:
    print(int(item_alarm.state))
    return datetime.fromtimestamp(int(item_alarm.state)/1000)
  except Exception as e:
    #print("no alarm" + str(e))
    return None
  
def get_day(alarm):
  return alarm.strftime("%A").lower()

def check_alarm(openhab,day,alarm_time,homeoffice_item,vacations_item,heating_duration_default):
    try:
      alarm_max = alarm_time.replace(hour=12, minute=0)
      if(alarm_time < alarm_max):
          alarm_time += timedelta(minutes=3)
          alarm_time -= timedelta(minutes=alarm_time.minute % 10,
                                  seconds=alarm_time.second,
                                  microseconds=alarm_time.microsecond)
          print(alarm_time)
          heating_start = alarm_time
          heating_duration = heating_duration_default
          if(not(vacations_item == '')):
            item_vacations_day = openhab.get_item(vacations_item + day.capitalize())
            if(item_vacations_day.state == 'ON'):
              print('vacations detected - no heating')
              return []
          if(not(homeoffice_item == '') and alarm_time.weekday() < 5):
            # If its HO day, then keep heating on for longer time (4 hours)
            item_ho_day = openhab.get_item(homeoffice_item + day.capitalize())
            if(item_ho_day.state == 'ON'):
                heating_duration = 60*10
          if(alarm_time.weekday() >= 5):
            heating_duration = 60*3
          heating_end = alarm_time + timedelta(minutes=heating_duration)

          return [
              {
                  "start": heating_start,
                  "end": heating_end,
              }
          ]
      else:
          print("alarm late " + str(alarm_time))
          return []
    except:
        print("no alarm " + str(alarm_time))
        return []

def sort_by_start(e):
  return e['start']

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
  settings = get_config(sys.path[0])
  base_url = settings['Openhab'].get('openhab_url','')
  openhab = OpenHAB(base_url,None, None, None, 1)
  
  date_time = datetime.strptime(date,"%Y-%m-%dt%H:%M%z")
  date = date_time.date()
  day = (get_day(date)).capitalize()
  print(day)
  
  program = await return_schedule()
  program = program["switchPoints"]
  #print(program)

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
    if(day != block_changed["day"]):
      program_processed = program_processed + [
          {
            "day": block_changed["day"],
            "time": block_changed["time"],
            "activity": block_changed["activity"]
          }
      ]

  print(program_processed)


  alarms = [
    {'alarm':'Phone_01_AlarmClock', 'homeoffice': 'HO_01_','vacations': 'Vacations_01_', 'heating_duration': 10},
    {'alarm':'Phone_02_AlarmClock', 'homeoffice': 'HO_02_','vacations': 'Vacations_02_', 'heating_duration': 20},
  ]
  schedule = []
  list_to_process = []
  for item in alarms:
    try:
      alarm_time = get_alarm_time(openhab,item['alarm'])
      print(alarm_time)
      if(not alarm_time is None and alarm_time.date() == date):
        list_to_process = list_to_process + [{'time':alarm_time,'homeoffice':item['homeoffice'],'vacations':item['vacations'],'heating_duration':item['heating_duration']}]
    except Exception as e:
      #print("no alarm" + str(e))
      pass
    
  print(list_to_process)
  if(not list_to_process == []):
    blocks = []
    for alarm_process in list_to_process:
      blocks = blocks + check_alarm(openhab, day, alarm_process['time'], alarm_process['homeoffice'],alarm_process['vacations'],alarm_process['heating_duration'])
    # add end of day block
    constant_heating_start = 17
    if(date_time.weekday() >= 5):
      constant_heating_start = 9
    blocks = blocks + [
              {
                  "start": date_time.replace(hour=constant_heating_start, minute=00,tzinfo=None),
                  "end": date_time.replace(hour=21, minute=00,tzinfo=None),
              }
          ]
    print(blocks)

    # A function that returns the 'year' value:
    # https://stackoverflow.com/questions/41931482/sorting-a-list-of-dictionary-values-by-date-and-time-in-python
    blocks.sort(key=sort_by_start) 

    blocks = list(merge_times(blocks))
    print(blocks)

    for block in blocks:
      schedule = schedule + [
        {
            "time": to_string_date(block['start']),
            "day": day,
            "activity": 2
        },
        {
            "time": to_string_date(block['end']),
            "day": day,
            "activity": 4
        }
      ]
  else:
    # weekend scenario if there are no alarms
    if(date_time.weekday() >= 5):
      schedule = schedule + [
        {
            "time": "9:00",
            "day": day,
            "activity": 2
        }
      ]
    # turn of heating mark
    schedule = schedule + [
      {
          "time": "21:00",
          "day": day,
          "activity": 4
      }
    ]
  schedule = schedule + program_processed
  print(schedule)
  await set_time_program(schedule)
  
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