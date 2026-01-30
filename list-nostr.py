import time
import uuid
import argparse
import yaml
import os
from dotenv import load_dotenv
from pynostr.relay_manager import RelayManager
from pynostr.filters import FiltersList, Filters
from pynostr.event import EventKind

def load_config(profile_name: str):
    home_dir = os.path.expanduser("~")
    dotenv_path = os.path.join(home_dir, "post-nostr.env")
    load_dotenv(dotenv_path)

    profiles_path = os.path.join(home_dir, "post-nostr-profiles.yaml")
    with open(profiles_path, 'r') as file:
        profiles = yaml.safe_load(file)
    
    common_relays = profiles['common']['relays']
    selected_profile = profiles['profiles'].get(profile_name)

    relays = set(common_relays)
    for relay in selected_profile.get('relays', []):
        relays.add(relay)
    
    active_profile = {'nsec': selected_profile['nsec'], 'relays': list(relays)}

    return active_profile

def main():
    parser = argparse.ArgumentParser(description="list nostr chats")
    parser.add_argument("-p", "--profile", type=str, default="default", help="Profile name to use")
    args = parser.parse_args()

    profile_name = args.profile
    active_profile = load_config(profile_name)

    print(f"Active profile: {profile_name}")
    print(active_profile)

    relay_manager = RelayManager(timeout=2)

    for relay in active_profile['relays']:
        relay_manager.add_relay(relay)
    
    filters = FiltersList([Filters(kinds=[EventKind.TEXT_NOTE], limit=100)])

    subscription_id = uuid.uuid1().hex
    relay_manager.add_subscription_on_all_relays(subscription_id, filters)
    relay_manager.run_sync()
    while relay_manager.message_pool.has_notices():
        notice_msg = relay_manager.message_pool.get_notice()
        print(notice_msg.content)
    while relay_manager.message_pool.has_events():
        event_msg = relay_manager.message_pool.get_event()
        print(event_msg.event.content)

    relay_manager.close_all_relay_connections()

if __name__ == "__main__":
    main()
