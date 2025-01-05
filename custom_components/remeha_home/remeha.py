"""The Remeha Home integration."""
from __future__ import annotations
from aiohttp import ClientSession

import click
import asyncio
from functools import wraps
from openhab import OpenHAB
from configparser import ConfigParser
import __main__ as main
import sys
import os
import time
from typing import Any, cast
from datetime import datetime, timedelta, date

from api import RemehaHomeOAuth2Implementation, RemehaHomeAPI, OAuth2Session, get_config

settings = get_config(sys.path[0])
base_url = settings['Openhab'].get('openhab_url','')


def string_to_time(string):
  return time.strptime(string,"%H:%M")

def add_values(amount, val):
    array = []
    for i in range(0, amount):
        array = array + [val]
    return array

def datetime_to_string(timestamp, dt_format='%Y-%m-%d %H:%M:%S'):
    """
    Format datetime object to string
    """
    return timestamp.strftime(dt_format)


def simple_time(value):
    """
    Format a datetime or timedelta object to a string of format HH:MM
    """
    if isinstance(value, timedelta):
        return ':'.join(str(value).split(':')[:2])
    return datetime_to_string(value, '%H:%M')


def statistics_to_openhab(openhab,item_name,value):
    #value = value / 8.7917
    item_daily = openhab.get_item(item_name + '_Daily')
    item_hourly = openhab.get_item(item_name + '_Hourly')
    use_daily_previous = item_daily.state
    if use_daily_previous is None:
        use_daily_previous = 0
    item_daily.update(value)
    use_hourly = value - use_daily_previous
    item_hourly.update(use_hourly)

async def get_token(api_implmentation):
    #
    token = settings['General'].get('token',None)
    if(not await is_refresh_token_valid(token)):
        return await generate_token(api_implmentation)
    #print("token is still valid")
    token = eval(token)
    return token


async def generate_token(api_implmentation):
    token = await api_implmentation.async_resolve_external_data()

    settings['General']['token'] = str(token)
    with open(os.path.join(sys.path[0], 'config.ini'), 'w') as configfile:
        settings.write(configfile)
    return token

async def is_refresh_token_valid(token):
    if(token == None):
        return False
    token = eval(token)
    #print(token["refresh_token_expires_in"])
    return (
        cast(float, token["expires_on"]) + cast(float, token["refresh_token_expires_in"])
            > time.time() + 60
    )

async def get_api():
    #print ("start")
    api_implmentation = RemehaHomeOAuth2Implementation(ClientSession() )
    #print("get token")
    token = await get_token(api_implmentation)
    #print(token)
    oauth_session = OAuth2Session(token,api_implmentation)
    #await api_implmentation.close_session()
    return RemehaHomeAPI( oauth_session)


def coro(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return asyncio.get_event_loop().run_until_complete(f(*args, **kwargs))

    return wrapper

## Main program
@click.group()
def cli():
    """
    BDR Thermea API
    """
    pass

@cli.command()
@coro
async def get_connection():
    print("get status")
    api = await get_api()

@cli.command()
@coro
async def get_status():
    print("get status")
    api = await get_api()
    resp = await api.async_get_dashboard()
    #await api.async_end_session()
    print(resp)
    remehaIds = ['applianceId','climateZoneId','hotWaterZoneId']
    for dataId in remehaIds:
        id = settings['General'].get(dataId,None)
        if(id == None):
            settings['General']['token']
    deviceId = settings['General'].get('deviceId',None)
    heatingId = settings['General'].get('heatingId',None)
    waterId = settings['General'].get('waterId',None)


    # Setup openhab items
    openhab = OpenHAB(base_url,None, None, None, 1)
    item_mode = openhab.get_item('Thermostat_Mode')
    item_program = openhab.get_item('Thermostat_Program')
    item_nextSwitchDate = openhab.get_item('Thermostat_NextSwitch_Time')
    item_nextSwitchTemperature = openhab.get_item('Thermostat_NextSwitch_Temperature')
    item_currentTemperature = openhab.get_item('Thermostat_Temperature')
    item_currentSetpoint = openhab.get_item('Thermostat_TemperatureControl')
    item_flowTemperature = openhab.get_item('Thermostat_FlowTemperature')
    item_waterPressure = openhab.get_item('Thermostat_WaterPressure')
    item_waterMode = openhab.get_item('Thermostat_Water_Mode')
    item_waterTemperature = openhab.get_item('Thermostat_Water_Temperature')
    item_boilerState = openhab.get_item('Thermostat_BoilerState')
    item_isUpdated = openhab.get_item('Thermostat_UpdateActive')

    appliance = resp["appliances"][0]
    #print(appliance)
    heating = appliance["climateZones"][0]
    #print(heating)
    water = appliance["hotWaterZones"][0]
    #print(water)

    # Store Id in config if they are not present
    if( settings['General'].get('applianceId',"") == ""):
        settings['General']['applianceId'] = appliance['applianceId']
        settings['General']['climateZoneId'] = heating['climateZoneId']
        settings['General']['hotWaterZoneId'] = water['hotWaterZoneId']
        with open(os.path.join(sys.path[0], 'config.ini'), 'w') as configfile:
            settings.write(configfile)

    # operatingMode activeThermalMode
    boiler_state = appliance['activeThermalMode']
    item_boilerState.update(str(boiler_state))

    # Get boiler pressure
    pressure_state = appliance['waterPressure']
    item_waterPressure.update(str(pressure_state))

    mode = heating.get("zoneMode","")
    #print(mode)
    item_mode.update(str(mode))

    # Get data for next switch
    if(mode == "Scheduling" or mode == "TemporaryOverride"):
        endtime = heating.get("nextSwitchTime")
        temperature = heating.get("nextSetpoint","")
        item_nextSwitchDate.update(endtime.replace("T"," ").replace("Z",""))
        item_nextSwitchTemperature.update(temperature)

    # Get current temperature
    currentTemperature = heating.get("roomTemperature","")
    item_currentTemperature.update(currentTemperature)

    # Get current setpoint
    if(item_isUpdated.state == "OFF"):
        currentSetpointTemperature = heating.get("setPoint","")
        item_currentSetpoint.update(currentSetpointTemperature)

    # Get current program
    program = heating.get("activeHeatingClimateTimeProgramNumber",1)
    item_program.update(str(program))

    # Get current water mode
    mode = water.get("dhwZoneMode","")
    item_waterMode.update(str(mode))

    waterTemperature = water.get("dhwTemperature","")
    if waterTemperature != None:
        item_flowTemperature.update(str(waterTemperature))

    waterTemperatureTarget = water.get("targetSetpoint","")
    item_waterTemperature.update(str(waterTemperatureTarget))

    # Get current flow temperature
    #resp = await api.get_flow_temperature()
    #item_flowTemperature = openhab.get_item('Thermostat_FlowTemperature')
    #mode = resp.get("systemFlowTemperature","")
    #item_flowTemperature.update(str(mode))
    #print(resp)

    #await api.async_end_session()

@cli.command()
@click.option('--value',
              required=True,
              default=None,
              help=(('Target temperature in degrees, '
                     'Manual override')))
@coro
async def set_temperature(value):
    api = await get_api()
    await api.async_set_temporary_override(settings['General'].get('climateZoneId',""),value)
    print("temperature changed to " + str(value))

@cli.command()
@click.option('--mode',
              required=True,
              default=None,
              help=(('Set operating mode to schedule, '
                     'Number of the program [1-3]')))
@coro
async def set_mode_schedule(mode):
    api = await get_api()
    await api.async_set_mode_schedule(settings['General'].get('climateZoneId',""),mode)


@cli.command()
@coro
async def set_mode_antifrost():
    api = await get_api()
    await api.async_set_off(settings['General'].get('climateZoneId',""))


@cli.command()
@click.option('--mode',
              required=True,
              default=None,
              help=(('Set water mode, '
                     'Can be ContinuousComfort or Off')))
@coro
async def set_water_mode(mode):
    api = await get_api()
    if(mode == "ContinuousComfort"):
        await api.async_set_water_mode_comfort(settings['General'].get('hotWaterZoneId',""))
    else:
        await api.async_set_water_mode_eco(settings['General'].get('hotWaterZoneId',""))

@cli.command()
@click.option('--value',
              required=True,
              default=None,
              help=(('Target temperature in degrees, '
                     'Manual override')))
@coro
async def set_water_temperature(value):
    api = await get_api()
    await api.async_set_water_comfort_setpoint(settings['General'].get('hotWaterZoneId',""),value)
    print("water temperature changed to " + str(value))


@cli.command()
@coro
async def get_schedule():
    api = await get_api()
    resp = await api.async_get_schedule(settings['General'].get('climateZoneId',""),1)
    #program = {'monday': [{'time': '07:30', 'activity': 2}, {'time': '13:00', 'activity': 4}, {'time': '17:20', 'activity': 2}, {'time': '21:00', 'activity': 4}], 'tuesday': [{'time': '07:00', 'activity': 2}, {'time': '07:10', 'activity': 4}, {'time': '17:20', 'activity': 2}, {'time': '21:00', 'activity': 4}], 'wednesday': [{'time': '07:00', 'activity': 2}, {'time': '07:10', 'activity': 4}, {'time': '17:20', 'activity': 2}, {'time': '21:00', 'activity': 4}], 'thursday': [{'time': '07:00', 'activity': 2}, {'time': '07:10', 'activity': 4}, {'time': '17:20', 'activity': 2}, {'time': '21:00', 'activity': 4}], 'friday': [{'time': '07:00', 'activity': 2}, {'time': '07:10', 'activity': 4}, {'time': '17:20', 'activity': 2}, {'time': '21:00', 'activity': 4}], 'saturday': [{'time': '17:20', 'activity': 2}, {'time': '21:00', 'activity': 4}], 'sunday': [{'time': '08:00', 'activity': 2}, {'time': '13:30', 'activity': 4}, {'time': '21:00', 'activity': 4}]}
    #print(resp)
    program = resp["switchPoints"]
    print(program)
    index = 6
    data = {}
    activity = 0
    dayPrevious = 0

    value_array = []
    time_prev = time.gmtime(0)
    round_result = 0

    # Data
    value_array_sunday = []

    for block in program:
        day = block['day']
        if(day != dayPrevious):
            dayPrevious = day
            value_array = value_array + add_values(96-len(value_array),activity)
            #print(len(value_array))

            if(index == 6):
                index = 1
                value_array_sunday = value_array
            else:
                data.update({str(index):
                    {
                        "key":str(index),
                        "value":value_array
                    }
                })
                index += 1
            value_array = []
            time_prev = time.gmtime(0)
            round_result = 0

        time_string = block.get('time')
        time_val = string_to_time(time_string)
        time_val_blocks_pre = (time_val[3] - time_prev[3] + (time_val[4]-time_prev[4])/60)*4
        time_val_blocks = round(round_result + time_val_blocks_pre)
        round_result = time_val_blocks_pre - time_val_blocks
        time_prev = time_val
        value_array = value_array + add_values(time_val_blocks,activity)
        #print(time_val_blocks)
        activity = block.get('activity')
        if(activity == 2):
            activity = 1
        else:
            activity= 0

    value_array = value_array + add_values(96-len(value_array),activity)
    data.update({str(6):
        {
            "key":str(6),
            "value":value_array
        }
    })

    data.update({str(7):
        {
            "key":str(7),
            "value":value_array_sunday
        }
    })
    data.update({
        "99":"noc,dzień","100":{"event":False,"lastItemState":-1,"inactive":False}
    })
    # data in format of timeline picker
    # https://community.openhab.org/t/timeline-picker-to-setup-heating-light-and-so-on/55564
    data_str = str(data).replace("'",'"').replace("False","false").replace(" ","")
    print(data_str)
    #quit()
    openhab = OpenHAB(base_url,None, None, None, 1)
    item_schedule = openhab.get_item('TransferItem1')
    item_schedule.update(data_str)
    #print(data_str)

@cli.command()
@click.option('--datefrom',
              required=True,
              default=None,
              help=(('Get heating history from selected date, '
                     'Data in format YYYY-MM-DD')))
@click.option('--dateto',
              required=False,
              default=None,
              help=(('Get heating history from selected date, '
                     'Data in format YYYY-MM-DD')))
@coro
async def get_history(datefrom,dateto):
    api = await get_api()
    if(dateto is None):
        dateto = datefrom
        datefrom = datetime.strptime(datefrom, '%Y-%m-%d')
        datefrom = datefrom + timedelta(days=-1)
        datefrom = datetime_to_string(datefrom,"%Y-%m-%d")
    #print(datefrom)
    #print(dateto)
    #quit()
    resp = await api.async_get_consumption_history(settings['General'].get('applianceId',""),datefrom,dateto)
    data = resp['data'][1]
    print(data)
    openhab = OpenHAB(base_url,None, None, None, 1)
    statistics_to_openhab(openhab,'Thermostat_HeatingUsage',data['heatingEnergyConsumed'])
    statistics_to_openhab(openhab,'Thermostat_HotWaterUsage',data['hotWaterEnergyConsumed'])



async def set_time_program(schedule):
    api = await get_api()
    print(schedule)
    await api.async_set_schedule(settings['General'].get('climateZoneId',""),"1",schedule)

async def return_schedule():
    api = await get_api()
    resp = await api.async_get_schedule(settings['General'].get('climateZoneId',""),1)
    return resp

@cli.command()
@click.option('--activity',
              required=True,
              default=None,
              help=(('Which activity you want to modify, '
                     'Number of the activity [1-5]')))
@click.option('--temperature',
              required=True,
              default=None,
              help=(('Set temperature for selected activity, '
                     'Number, temperature in degrees')))
@coro
async def set_activity(activity,temperature):
    api = await get_api()
    resp = await api.async_get_activity(settings['General'].get('climateZoneId',""))
    print(resp[0])
    activities_list = [
        {"activityNumber":1,"type":"Heating","temperature":resp[0]['temperature']},
        {"activityNumber":2,"type":"Heating","temperature":resp[1]['temperature']},
        {"activityNumber":3,"type":"Heating","temperature":resp[2]['temperature']},
        {"activityNumber":4,"type":"Heating","temperature":resp[3]['temperature']},
        {"activityNumber":5,"type":"Heating","temperature":resp[4]['temperature']}
    ]
    activities_list[int(activity) - 1]['temperature'] = temperature
    print(activities_list)
    await api.async_set_activities(settings['General'].get('climateZoneId',""),activities_list)


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

