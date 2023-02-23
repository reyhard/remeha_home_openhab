"""The Remeha Home integration."""
from __future__ import annotations
from aiohttp import ClientSession

import asyncio
from configparser import ConfigParser
import sys
import os
import time
from typing import Any, cast

from api import RemehaHomeOAuth2Implementation, RemehaHomeAPI, OAuth2Session

def get_config(config_dir):
    # Load configuration file
    config = ConfigParser(delimiters=('=', ))
    config.optionxform = str
    config.read([os.path.join(config_dir, 'config.ini.dist'), os.path.join(config_dir, 'config.ini')])
    return config

settings = get_config(sys.path[0])
base_url = settings['Openhab'].get('openhab_url','')

async def get_token(api_implmentation):
    #
    token = settings['General'].get('token',None)
    if(not await is_refresh_token_valid(token)):
        return await generate_token(api_implmentation)
    print("token is still valid")
    token = eval(token)
    return token


async def generate_token(api_implmentation):
    token = await api_implmentation.async_resolve_external_data()

    settings['General']['token'] = str(token)
    with open('config.ini', 'w') as configfile:
        settings.write(configfile)
    return token

async def is_refresh_token_valid(token):
    print(token == None)
    if(token == None):
        return False
    token = eval(token)
    #print(token["refresh_token_expires_in"])
    return (
        cast(float, token["expires_on"]) + cast(float, token["refresh_token_expires_in"])
            > time.time() + 60
    )

async def get_api():
    print ("start")
    api_implmentation = RemehaHomeOAuth2Implementation(ClientSession() )
    print("get token")
    token = await get_token(api_implmentation)
    print(token)
    oauth_session = OAuth2Session(token,api_implmentation)
    return RemehaHomeAPI( oauth_session)

async def main():
    api = await get_api()
    resp = await api.async_get_dashboard()
    print(resp)
    #await RemehaHomeOAuth2Implementation.async_resolve_external_data()
    
loop = asyncio.get_event_loop()
loop.run_until_complete(main())

