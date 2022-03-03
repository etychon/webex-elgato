#!/usr/bin/python3

import requests
import json
import time
import leglight
import sys
import logging
import warnings
import constants

### Cisco WebEx Specific

access_token = constants.access_token
user_id = constants.user_id

# Build the URL to get user status
url = 'https://webexapis.com/v1/people/'.format(user_id)

headers = {
  'Authorization': 'Bearer {}'.format(access_token),
  'Content-Type': 'application/json'
}

params = {
  'email': constants.email
}

### Remove Zeroconf annoying "FutureWarning" and Set log level to info
warnings.simplefilter(action='ignore', category=FutureWarning)
logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

### Discover and prepare all Elgato lights with library

allLights = []
logging.warning('Discovering lights on local network...') 
while True:
  # Initialize Elgato lib and discover all lights
  allLights = leglight.discover(2)
  if len(allLights)<=0:
    # None found
    logging.warning('No light found, will try again later') 
    time.sleep(10)
  else:
    logging.info('Found {} light(s): {}'.format(len(allLights), str(allLights)))
    break

# Get Elgato current light status
if (allLights[0].isOn):
  light_on = True;
else:
  light_on = False;


def spinning_cursor():
    while True:
        for cursor in '|/-\\':
            yield cursor

spinner = spinning_cursor()

no_in_meeting_count = 0;

while (True) :

  try:
    res = requests.get(url, headers=headers, params=params)
  except requests.exceptions.RequestException as e:  # This is the correct syntax
    logging.info("Got an error - wait 10 seconds")
    time.sleep(10)
    continue

  resj = res.json()
  
  if ('items' in resj):
    itemsj = resj['items'][0]
  else:
    continue

  try:
    if ((itemsj['status'] == "meeting") or (itemsj['status'] == "presenting") or (itemsj['status'] == "call")):
      # user is in a meeting
      no_in_meeting_count = 0;
      if (light_on == False):
        # user is in a meeting and light is off - turn light on
        logging.info("User is in a meeting -> turn light on")
        for light in allLights:
          light.on()
        light_on = True
    else:
      # user not in a meeting
      if (light_on == True):
        # light is on, but user not in a meeting, wait
        no_in_meeting_count = no_in_meeting_count + 1
        if (no_in_meeting_count > 10):
          # user was not in a meeting for the last "x" API calls, turn off light
          logging.info("User is not a meeting -> turn light off")
          for light in allLights:
            light.off()
          light_on = False

  except:
    logging.info('Error, skipping...')
    
  sys.stdout.write(next(spinner))
  sys.stdout.flush()
  sys.stdout.write('\b')  

  time.sleep(2)
  