import time
import uuid
import argparse
import yaml
import os
import rich
from rich.console import Console
from dotenv import load_dotenv
from pynostr.relay_manager import RelayManager
from pynostr.filters import FiltersList, Filters
from pynostr.event import EventKind
from pynostr.key import PrivateKey

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
    console = Console()

    parser = argparse.ArgumentParser(description="list nostr chats")
    parser.add_argument("-p", "--profile", type=str, default="default", help="Profile name to use")
    parser.add_argument("-f", "--from", dest="source_scope", choices=["public", "follow"], default="public", help="Source of events: public (default) or follow")
    parser.add_argument("-l", "--limit", type=int, default=100, help="Number of events to fetch")
    args = parser.parse_args()

    profile_name = args.profile
    active_profile = load_config(profile_name)

    console.print(f"Active profile: {profile_name}")

    relay_manager = RelayManager(timeout=2)

    for relay in active_profile['relays']:
        relay_manager.add_relay(relay)

    filters_list = []

    if args.source_scope == "follow":
        nsec = active_profile['nsec']
        if nsec.startswith("nsec"):
            private_key = PrivateKey.from_nsec(nsec)
        else:
            private_key = PrivateKey.from_hex(nsec)

        pubkey_hex = private_key.public_key.hex()
        console.print(f"Fetching contacts for {pubkey_hex}...")

        # Fetch contacts
        contact_sub_id = uuid.uuid1().hex
        contact_filters = FiltersList([Filters(kinds=[EventKind.CONTACTS], authors=[pubkey_hex], limit=1)])
        relay_manager.add_subscription_on_all_relays(contact_sub_id, contact_filters)
        relay_manager.run_sync()

        follows = []
        while relay_manager.message_pool.has_events():
            event_msg = relay_manager.message_pool.get_event()
            if event_msg.event.kind == EventKind.CONTACTS and event_msg.event.pubkey == pubkey_hex:
                for tag in event_msg.event.tags:
                    if tag[0] == 'p':
                        follows.append(tag[1])

        relay_manager.close_subscription_on_all_relays(contact_sub_id)

        # Clean up notices from contact fetch if any?
        while relay_manager.message_pool.has_notices():
            relay_manager.message_pool.get_notice()

        authors = follows + [pubkey_hex]
        filters_list = [Filters(kinds=[EventKind.TEXT_NOTE], authors=authors, limit=args.limit)]
        console.print(f"Fetching timeline for {len(follows)} follows...")
    else:
        filters_list = [Filters(kinds=[EventKind.TEXT_NOTE], limit=args.limit)]

    filters = FiltersList(filters_list)

    subscription_id = uuid.uuid1().hex
    relay_manager.add_subscription_on_all_relays(subscription_id, filters)
    relay_manager.run_sync()
    while relay_manager.message_pool.has_notices():
        notice_msg = relay_manager.message_pool.get_notice()
        console.print(notice_msg.content)
    while relay_manager.message_pool.has_events():
        event_msg = relay_manager.message_pool.get_event()
        console.print(event_msg.event.content)

    relay_manager.close_all_relay_connections()

if __name__ == "__main__":
    main()
