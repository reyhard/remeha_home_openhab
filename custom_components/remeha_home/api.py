"""API for Remeha Home bound to Home Assistant OAuth."""
import base64
import hashlib
import json
import logging
import secrets
import urllib
import sys
from configparser import ConfigParser
import os

import async_timeout
from aiohttp import client, web, ClientSession
import asyncio
import time
from typing import Any, cast

#from requests_oauthlib import OAuth2Session


def get_config(config_dir):
    # Load configuration file
    #print(config_dir)
    config = ConfigParser(delimiters=('=', ))
    config.optionxform = str
    config.read([os.path.join(config_dir, 'config.ini.dist'), os.path.join(config_dir, 'config.ini')])
    return config

settings = get_config(sys.path[0])

class OAuth2Session:
    """Session to make requests authenticated with OAuth2."""

    def __init__(
        self,
        token_data,
        implementation,
    ) -> None:
        """Initialize an OAuth2 session."""
        #self.config_entry = config_entry
        #print(token_data)
        self.token = token_data
        self.implementation = implementation
        #print(token_data['expires_on'])
        
    #@property
    #def token(self) -> dict:
    #    """Return the token."""
    #    return cast(dict, self.token)

    @property
    def valid_token(self) -> bool:
        """Return if token is still valid."""
        #print(time.time())
        return (
            cast(float, self.token["expires_on"])
            > time.time() + 60
        )

    async def async_ensure_token_valid(self) -> None:
        """Ensure that the current token is valid."""
        if self.valid_token:
            return
        print("token need to be refreshed: " + str(self.valid_token))
        new_token = await self.implementation.async_refresh_token(self.token)

        # store refreshed token in config
        settings['General']['token'] = str(new_token)
        with open(os.path.join(sys.path[0], 'config.ini'), 'w') as configfile:
            settings.write(configfile)

        self.token = new_token
        #self.hass.config_entries.async_update_entry(
        #    self.config_entry, data={**self.config_entry.data, "token": new_token}
        #)

    async def async_request(
        self, method: str, url: str, **kwargs: Any
    ) -> client.ClientResponse:
        """Make a request."""
        #print(self.token["expires_on"])
        await self.async_ensure_token_valid()
        return await async_oauth2_request(
            self.token, method, url, **kwargs
        )


async def async_oauth2_request(
    token: dict, method: str, url: str, **kwargs: Any
) -> client.ClientResponse:
    """Make an OAuth2 authenticated request.
    This method will not refresh tokens. Use OAuth2 session for that.
    """
    #session = async_get_clientsession(hass)
    session = ClientSession()
    headers = kwargs.pop("headers", {})
    return await session.request(
        method,
        url,
        **kwargs,
        headers={
            **headers,
            "authorization": f"Bearer {token['access_token']}",
        },
    )


#from homeassistant.helpers.config_entry_oauth2_flow import (
#    AbstractOAuth2Implementation,
#    OAuth2Session,
#)
#
from const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class RemehaHomeAPI:
    """Provide Remeha Home authentication tied to an OAuth2 based config entry."""

    def __init__(
        self,
        oauth_session: OAuth2Session = None,
    ) -> None:
        """Initialize Remeha Home auth."""
        self._oauth_session = oauth_session

    async def async_get_access_token(self) -> str:
        """Return a valid access token."""
        _LOGGER.warning("GOT HERE")
        if not self._oauth_session.valid_token:
            await self._oauth_session.async_ensure_token_valid()

        return self._oauth_session.token["access_token"]

    async def _async_api_request(self, method: str, path: str, **kwargs):
        headers = kwargs.pop("headers", {})
        return await self._oauth_session.async_request(
            method,
            "https://api.bdrthermea.net/Mobile/api" + path,
            **kwargs,
            headers={
                **headers,
                "Ocp-Apim-Subscription-Key": "df605c5470d846fc91e848b1cc653ddf",
            },
        )

    async def async_get_dashboard(self) -> dict:
        """Return the Remeha Home dashboard JSON."""
        response = await self._async_api_request("GET", "/homes/dashboard")
        response.raise_for_status()
        #print(response)
        return await response.json()

    async def async_set_manual(self, climate_zone_id: str, setpoint: float):
        """Set a climate zone to manual mode with a specific temperature setpoint."""
        response = await self._async_api_request(
            "POST",
            f"/climate-zones/{climate_zone_id}/modes/manual",
            json={
                "roomTemperatureSetPoint": setpoint,
            },
        )
        response.raise_for_status()

    async def async_set_mode_schedule(self, climate_zone_id: str, heating_program_id: int):
        """Set a climate zone to schedule mode with a specific heating program."""
        response = await self._async_api_request(
            "POST",
            f"/climate-zones/{climate_zone_id}/modes/schedule",
            json={
                "heatingProgramId": heating_program_id,
            },
        )
        response.raise_for_status()

    async def async_set_temporary_override(self, climate_zone_id: str, setpoint: float):
        """Set a temporary temperature override for the current schedule in a climate zone."""
        response = await self._async_api_request(
            "POST",
            f"/climate-zones/{climate_zone_id}/modes/temporary-override",
            json={
                "roomTemperatureSetPoint": setpoint,
            },
        )
        response.raise_for_status()

    async def async_set_off(self, climate_zone_id: str):
        """Set a climate zone to off (antifrost mode)."""
        response = await self._async_api_request(
            "POST",
            f"/climate-zones/{climate_zone_id}/modes/anti-frost",
        )
        response.raise_for_status()

    async def async_get_schedule(self, climate_zone_id: str,program) -> dict:
        """Return heating schedule."""
        response = await self._async_api_request("GET", f"/climate-zones/{climate_zone_id}/time-programs/heating/{program}" )
        response.raise_for_status()
        #print(response)
        return await response.json()

    async def async_set_schedule(self, climate_zone_id: str, program, schedule):
        """Set schedule for selected time program."""
        response = await self._async_api_request(
            "PUT",
            f"/climate-zones/{climate_zone_id}/time-programs/heating/{program}",
            json={
                "switchPoints": schedule
            },
        )
        response.raise_for_status()

    async def async_set_water_mode_comfort(self, climate_zone_id: str):
        """Set hot water to comfort mode."""
        response = await self._async_api_request(
            "POST",
            f"/hot-water-zones/{climate_zone_id}/modes/continuous-comfort",
        )
        response.raise_for_status()

    async def async_set_water_mode_eco(self, climate_zone_id: str):
        """Set hot water to eco mode."""
        response = await self._async_api_request(
            "POST",
            f"/hot-water-zones/{climate_zone_id}/modes/anti-frost",
        )
        response.raise_for_status()

    async def async_end_session(self):
        """Generate a url for the user to authorize."""
        self._oauth_session.close()
        print("Close")

    async def async_get_consumption_history(self,appliance_id,dateFrom,dateTo):
        """Return heating schedule."""
        response = await self._async_api_request("GET", f"/appliances/{appliance_id}/energyconsumption/daily?startDate={dateFrom}%2000%3A00%3A00.000Z&endDate={dateTo}%2000%3A00%3A00.000Z" )
        response.raise_for_status()
        return await response.json()



class RemehaHomeAuthFailed(Exception):
    """Error to indicate that authentication failed."""

#AbstractOAuth2Implementation
class RemehaHomeOAuth2Implementation():
    """Custom OAuth2 implementation for the Remeha Home integration."""
    #, session: ClientSession #
    def __init__(self, session: ClientSession) -> None:
        self._session = session
        #print(session)
        #something = await self.async_resolve_external_data()
        return None

    @property
    def name(self) -> str:
        """Name of the implementation."""
        return "Remeha Home"

    @property
    def domain(self) -> str:
        """Domain that is providing the implementation."""
        return DOMAIN

    async def async_resolve_external_data(self) -> dict:
        """Resolve external data to tokens."""
        #, external_data
        print("start retriving token")
        email = settings['General'].get('email','')
        password = settings['General'].get('password','')

        # Generate a random state and code challenge
        random_state = secrets.token_urlsafe()
        code_challenge = secrets.token_urlsafe(64)
        code_challenge_sha256 = (
            base64.urlsafe_b64encode(
                hashlib.sha256(code_challenge.encode("ascii")).digest()
            )
            .decode("ascii")
            .rstrip("=")
        )

        with async_timeout.timeout(60):
            # Request the login page starting a new login transaction
            response = await self._session.get(
                "https://remehalogin.bdrthermea.net/bdrb2cprod.onmicrosoft.com/oauth2/v2.0/authorize",
                params={
                    "response_type": "code",
                    "client_id": "6ce007c6-0628-419e-88f4-bee2e6418eec",
                    "redirect_uri": "com.b2c.remehaapp://login-callback",
                    "scope": "openid https://bdrb2cprod.onmicrosoft.com/iotdevice/user_impersonation offline_access",
                    "state": random_state,
                    "code_challenge": code_challenge_sha256,
                    "code_challenge_method": "S256",
                    "p": "B2C_1A_RPSignUpSignInNewRoomV3.1",
                    "brand": "remeha",
                    "lang": "en",
                    "nonce": "defaultNonce",
                    "prompt": "login",
                    "signUp": "False",
                },
            )
            response.raise_for_status()
            print(response)

            # Find the request id from the headers and package it up in base64 encoded json
            request_id = response.headers["x-request-id"]
            state_properties_json = f'{{"TID":"{request_id}"}}'.encode("ascii")
            state_properties = (
                base64.urlsafe_b64encode(state_properties_json)
                .decode("ascii")
                .rstrip("=")
            )

            # Find the CSRF token in the "x-ms-cpim-csrf" header
            csrf_token = next(
                cookie.value
                for cookie in self._session.cookie_jar
                if (
                    cookie.key == "x-ms-cpim-csrf"
                    and cookie["domain"] == "remehalogin.bdrthermea.net"
                )
            )

            # Post the user credentials to authenticate
            response = await self._session.post(
                "https://remehalogin.bdrthermea.net/bdrb2cprod.onmicrosoft.com/B2C_1A_RPSignUpSignInNewRoomv3.1/SelfAsserted",
                params={
                    "tx": "StateProperties=" + state_properties,
                    "p": "B2C_1A_RPSignUpSignInNewRoomv3.1",
                },
                headers={
                    "x-csrf-token": csrf_token,
                },
                data={
                    "request_type": "RESPONSE",
                    "signInName": email,
                    "password": password,
                },
            )
            response.raise_for_status()
            response_json = json.loads(await response.text())
            #print(response)
            if response_json["status"] != "200":
                raise RemehaHomeAuthFailed

            #print(response)
            # Request the authentication complete callback
            response = await self._session.get(
                "https://remehalogin.bdrthermea.net/bdrb2cprod.onmicrosoft.com/B2C_1A_RPSignUpSignInNewRoomv3.1/api/CombinedSigninAndSignup/confirmed",
                params={
                    "rememberMe": "false",
                    "csrf_token": csrf_token,
                    "tx": "StateProperties=" + state_properties,
                    "p": "B2C_1A_RPSignUpSignInNewRoomv3.1",
                },
                allow_redirects=False,
            )
            response.raise_for_status()

            #print(response)
            # Parse the callback url for the authorization code
            parsed_callback_url = urllib.parse.urlparse(response.headers["location"])
            query_string_dict = urllib.parse.parse_qs(parsed_callback_url.query)
            authorization_code = query_string_dict["code"]

            # Request a new token with the authorization code
            grant_params = {
                "grant_type": "authorization_code",
                "code": authorization_code,
                "redirect_uri": "com.b2c.remehaapp://login-callback",
                "code_verifier": code_challenge,
                "client_id": "6ce007c6-0628-419e-88f4-bee2e6418eec",
            }
            return await self._async_request_new_token(grant_params)

    async def async_refresh_token(self, token: dict) -> dict:
        """Refresh a token."""
        grant_params = {
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "client_id": "6ce007c6-0628-419e-88f4-bee2e6418eec",
        }
        return await self._async_request_new_token(grant_params)

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        """Generate a url for the user to authorize."""
        return ""

    async def _async_request_new_token(self, grant_params):
        """Call the OAuth2 token endpoint with specific grant paramters."""
        with async_timeout.timeout(30):
            async with self._session.post(
                "https://remehalogin.bdrthermea.net/bdrb2cprod.onmicrosoft.com/oauth2/v2.0/token?p=B2C_1A_RPSignUpSignInNewRoomV3.1",
                data=grant_params,
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                response_json = await response.json()

        return response_json
    