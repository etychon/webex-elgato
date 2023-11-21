#!/usr/bin/python3

import requests
import json
import time
import leglight
import sys
import constants

from datetime import datetime

### Log with date

def t_print(*args, **kwargs):
  print(datetime.now(), *args, **kwargs)

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
  'email': 'etychon@cisco.com'
}

### Elgato Specific

# Initialize Elgato lib and discover all lights
allLights = leglight.discover(2)

# Get Elgato current light status
if allLights and allLights[0].isOn :
  light_on = True;
else:
  light_on = False;


def spinning_cursor():
    while True:
        for cursor in '|/-\\':
            yield cursor

spinner = spinning_cursor()

no_in_meeting_count = 0;

client = requests.session()

while (True) :

  try:
    ## res = requests.get(url, headers=headers, params=params)
    res = client.get(url, headers=headers, params=params)
  except requests.exceptions.RequestException as e:  # This is the correct syntax
    print("Got an error - wait 10 seconds")
    time.sleep(60)
    continue

  try:
    resj = res.json()
  except:
    continue
  
  if ('items' in resj):
    itemsj = resj['items'][0]
  else:
    continue

  try:
    sys.stdout.write('\r')
    t_print(itemsj['status'], end=' ')
    if ((itemsj['status'] == "meeting") or (itemsj['status'] == "presenting") or (itemsj['status'] == "call")):
      # user is in a meeting
      no_in_meeting_count = 0;
      if (light_on == False):
        # user is in a meeting and light is off - turn light on
        allLights = leglight.discover(2)
        t_print ("User is in a meeting -> turn light on [list: {}]".format(allLights))
        for light in allLights:
          light.on()
        light_on = True
    if ((itemsj['status'] == "DoNotDisturb") or (itemsj['status'] == "unknown")):
      # user is in "do not disturb" and this replaces "call", "meeting", so don't know
      # if in a meeting or not. So let's no do anything.
      pass
    else:
      # user not in a meeting
      if (light_on == True):
        # light is on, but user not in a meeting, wait
        no_in_meeting_count = no_in_meeting_count + 1
        if (no_in_meeting_count > 3):
          # user was not in a meeting for the last 3 API calls, turn off light
          allLights = leglight.discover(2)
          t_print ("User is not a meeting ({}) -> turn light off [list: {}]".format(itemsj['status'], allLights))
          for light in allLights:
            light.off()
          light_on = False

  except:
    t_print('Error, skipping, wait some time, then re-discover...')
    time.sleep(60)
    allLights = leglight.discover(2)
    
  sys.stdout.write(next(spinner))
  sys.stdout.write("\033[K")
  sys.stdout.flush()
  sys.stdout.write('\b')

  time.sleep(10)
  