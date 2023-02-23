# Remeha Home integration for OpenHab
This integration lets you control your Remeha Home thermostats from OpenHab.

**Before using this integration, make sure you have set up your thermostat in the [Remeha Home](https://play.google.com/store/apps/details?id=com.bdrthermea.application.remeha) app.**
If you are unable to use the Remeha Home app for your thermostat, this integration will not work.

## Current features
- All climate zones are exposed as entities with the following modes:
    - Auto mode: the thermostat will follow the clock program.
    If the target temperature is changed, it will temporarily override the clock program until the next target temperature change in the schedule.
    - Heat mode: the thermostat will be set to manual mode and continuously hold the set temperature.
    - Off mode: the thermostat is disabled.
- Each climate zone exposes the following sensors:
    - The next schedule setpoint
    - The time at which the next schedule setpoint gets activated
    - The current schedule setpoint
- Each appliance (CV-ketel) exposes the following sensors:
    - The water pressure

## Installation
