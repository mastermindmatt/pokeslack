import json
import logging
import os
import sys
import time

from datetime import datetime
from geopy.distance import vincenty
from pgoapi import PGoApi

from pokedata import json_deserializer, json_serializer
from pokesearch import Pokesearch
from pokeslack import Pokeslack
from pokeutil import get_pos_by_name

logger = logging.getLogger(__name__)

def pokemon_orderby(pokemon):
    pokemon_position = (pokemon['latitude'], pokemon['longitude'], 0)
    distance = vincenty(position, pokemon_position).miles
    return (pokemon['rarity'], -distance)

def notify_pokemon(pokeslack, pokemons, debug=False):
    sorted_pokemons = sorted(pokemons.values(), key=pokemon_orderby, reverse=True)
    for pokemon in sorted_pokemons:
        disappear_time = pokemon['disappear_time']
        expires_in = disappear_time - datetime.utcnow()

        pokemon_position = (pokemon['latitude'], pokemon['longitude'], 0)
        distance = vincenty(position, pokemon_position).miles

        logger.debug("have pokemon: %s - %s, rarity: %s, expires in: %s, %s miles away", pokemon['pokemon_id'], pokemon['name'], pokemon['rarity'], expires_in, distance)
        pokeslack.try_send_pokemon(pokemon, position, distance, debug)

if __name__ == '__main__':

    logging.basicConfig(stream=sys.stdout, level=logging.INFO)
    logging.getLogger("requests").setLevel(logging.WARNING)
    logging.getLogger("pgoapi.pgoapi").setLevel(logging.WARNING)
    logging.getLogger("pgoapi.rpc_api").setLevel(logging.WARNING)

    # used for local testing without starting up heroku
    env = {}
    if os.path.exists('.env'):
        with open('.env', 'r') as fp:
            for line in fp:
                parts = line.split('=')
                env[parts[0].strip()] = parts[1].strip()

    auth_service = str(os.environ.get('AUTH_SERVICE', env.get('AUTH_SERVICE')))
    username = str(os.environ.get('USERNAME', env.get('USERNAME')))
    password = str(os.environ.get('PASSWORD', env.get('PASSWORD')))
    location_name = str(os.environ.get('LOCATION_NAME', env.get('LOCATION_NAME')))
    rarity_limit = int(os.environ.get('RARITY_LIMIT', env.get('RARITY_LIMIT')))
    distance_limit = float(os.environ.get('DISTANCE_LIMIT', env.get('DISTANCE_LIMIT')))
    slack_webhook_url = str(os.environ.get('SLACK_WEBHOOK_URL', env.get('SLACK_WEBHOOK_URL')))

    # const vars
    step_size = 0.0025
    step_limit = 5

    # debug vars, used to test slack integration w/o waiting
    use_cache = False
    cached_filename = 'cached_pokedata.json'
    search_timeout = 30

    position, address = get_pos_by_name(location_name)
    logger.info('location_name: %s', address)

    api = PGoApi()
    pokesearch = Pokesearch(api, auth_service, username, password, position)
    pokeslack = Pokeslack(rarity_limit, distance_limit, slack_webhook_url)

    if not use_cache or not os.path.exists(cached_filename):
        logger.info('searching starting at latlng: (%s, %s)', position[0], position[1])
        pokesearch.login()
        while True:
            pokemons = pokesearch.search(position[0], position[1], step_limit, step_size)
            notify_pokemon(pokeslack, pokemons)
            with open(cached_filename, 'w') as fp:
                json.dump(pokemons, fp, default=json_serializer, indent=4)
            logging.info('done searching, waiting %s seconds...', search_timeout)
            time.sleep(search_timeout)
    else:
        with open(cached_filename, 'r') as fp:
            pokemons = json.load(fp, object_hook=json_deserializer)
            notify_pokemon(pokeslack, pokemons, True)
        logger.info('loaded cached pokemon data for %s pokemon', len(pokemons.keys()))
