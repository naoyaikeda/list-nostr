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

def chunk_list(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

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
    parser.add_argument("-s", "--sleep", type=int, default=2, help="Sleep time between relay checks")
    parser.add_argument("--chunk_size", type=int, default=100, help="Number of authors per chunk")
    parser.add_argument("--max_retries", type=int, default=3, help="Max retries for chunk processing")
    parser.add_argument("--retry_delay", type=int, default=5, help="Delay between retries in seconds")
    args = parser.parse_args()

    profile_name = args.profile
    active_profile = load_config(profile_name)

    console.print(f"Active profile: {profile_name}")
    relays = active_profile['relays']
    console.print(f"Relays: {', '.join(relays)}")

    relay_manager = RelayManager(timeout=2)

    for relay in relays:
        relay_manager.add_relay(relay)
        if relay in relay_manager.relays:
            r = relay_manager.relays[relay]
            r.ping_interval = 60
            r.ping_timeout = 30  # Set timeout less than interval to avoid warning

    relay_manager.run_sync()

    all_events_map = {}

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

        time.sleep(args.sleep)

        follows = []
        while relay_manager.message_pool.has_events():
            event_msg = relay_manager.message_pool.get_event()
            if event_msg.event.kind == EventKind.CONTACTS and event_msg.event.pubkey == pubkey_hex:
                for tag in event_msg.event.tags:
                    if tag[0] == 'p':
                        follows.append(tag[1])

        relay_manager.close_subscription_on_all_relays(contact_sub_id)

        # Clean up notices from contact fetch
        while relay_manager.message_pool.has_notices():
            relay_manager.message_pool.get_notice()

        authors = follows + [pubkey_hex]
        chunk_size = args.chunk_size
        chunks = list(chunk_list(authors, chunk_size))
        
        console.print(f"Fetching timeline for {len(authors)} authors in {len(chunks)} chunks...")

        for i, chunk in enumerate(chunks):
            console.print(f"Processing chunk {i+1}/{len(chunks)} ({len(chunk)} authors)...")
            chunk_sub_id = uuid.uuid1().hex
            chunk_filters = FiltersList([Filters(kinds=[EventKind.TEXT_NOTE], authors=chunk, limit=args.limit)])
            
            for attempt in range(args.max_retries):
                try:
                    relay_manager.add_subscription_on_all_relays(chunk_sub_id, chunk_filters)
                    
                    time.sleep(args.sleep)
                    
                    found_events = False
                    while relay_manager.message_pool.has_events():
                        event_msg = relay_manager.message_pool.get_event()
                        event = event_msg.event
                        all_events_map[event.id] = event
                        found_events = True
                    
                    relay_manager.close_subscription_on_all_relays(chunk_sub_id)
                    
                    # Optional: Break if we found events, or just accept that we tried.
                    # Since empty timeline is possible, we don't strictly retry on empty, 
                    # but we catch exceptions.
                    break 
                except Exception as e:
                    console.print(f"[red]Error processing chunk {i+1}, attempt {attempt+1}: {e}[/red]")
                    relay_manager.close_subscription_on_all_relays(chunk_sub_id)
                    if attempt < args.max_retries - 1:
                        time.sleep(args.retry_delay)
                    else:
                        console.print(f"[red]Failed to process chunk {i+1} after {args.max_retries} attempts.[/red]")

    else:
        filters_list = [Filters(kinds=[EventKind.TEXT_NOTE], limit=args.limit)]
        filters = FiltersList(filters_list)
        subscription_id = uuid.uuid1().hex
        
        for attempt in range(args.max_retries):
            try:
                relay_manager.add_subscription_on_all_relays(subscription_id, filters)
                time.sleep(args.sleep)
                
                while relay_manager.message_pool.has_events():
                    event_msg = relay_manager.message_pool.get_event()
                    event = event_msg.event
                    all_events_map[event.id] = event
                
                relay_manager.close_subscription_on_all_relays(subscription_id)
                break
            except Exception as e:
                console.print(f"[red]Error processing public timeline, attempt {attempt+1}: {e}[/red]")
                relay_manager.close_subscription_on_all_relays(subscription_id)
                if attempt < args.max_retries - 1:
                    time.sleep(args.retry_delay)

    # Process and print all gathered events
    while relay_manager.message_pool.has_notices():
        notice_msg = relay_manager.message_pool.get_notice()
        console.print(notice_msg.content)

    events_list = list(all_events_map.values())
    # Sort by created_at descending
    events_list.sort(key=lambda x: x.created_at, reverse=True)

    # If we chunked, we might have more than limit events total, 
    # but user might want to see them all or limit total. 
    # For now, we show all fetched.

    for event in events_list:
        try:
            console.print(f"[green]{event.date_time().strftime('%Y-%m-%d %H:%M:%S')}[/green] [bold blue]{event.pubkey[:8]}[/bold blue]: {event.content}")
        except Exception:
            # Fallback for when rich fails to render certain characters
            print(f"{event.date_time().strftime('%Y-%m-%d %H:%M:%S')} {event.pubkey[:8]}: {event.content}")
        console.print("-" * 20)

    if len(events_list) == 0:
        console.print("[yellow]No events found. This could be because of relay issues or no new events in the requested scope.[/yellow]")
    else:
        console.print(f"[bold green]Fetched {len(events_list)} events.[/bold green]")

    relay_manager.close_all_relay_connections()

if __name__ == "__main__":
    main()
