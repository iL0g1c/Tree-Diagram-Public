import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import os
from collections import defaultdict
from datetime import datetime
import re
from io import StringIO
import json
from bson.json_util import dumps as bson_dumps
from io import BytesIO
import aiohttp

from treeDiagramPublic import TreeDiagramPublic
from tools.serverPaginatedEmbed import ServerPaginatedEmbed


load_dotenv()
DATABASE_TOKEN = os.getenv('DATABASE_TOKEN')
DATABASE_NAME = os.getenv('DATABASE_NAME')
DATABASE_IP = os.getenv('DATABASE_IP')
DATABASE_USER = os.getenv('DATABASE_USER')

class EventSummaryModal(discord.ui.Modal):
    def __init__(self, event_type: str, verbose: str):
        super().__init__(title=f"Details for {event_type}")
        self.event_type = event_type
        self.verbose = verbose

        self.acid_val = None
        self.a_date = None
        self.b_date = None
        self.raw_event_type = None

    acid = discord.ui.TextInput(
        label="ACID (Numeric ID)",
        placeholder="e.g., 12345",
        style=discord.TextStyle.short,
        required=True
    )
    
    before = discord.ui.TextInput(
        label="Before (YYYY-MM-DD HH:MM)",
        placeholder="2026-03-19 12:00",
        style=discord.TextStyle.short,
        required=False
    )
    
    after = discord.ui.TextInput(
        label="After (YYYY-MM-DD HH:MM)",
        placeholder="2026-03-19 13:00",
        style=discord.TextStyle.short,
        required=False
    )

    async def fetch_and_format_events(self, page: int, per_page: int) -> tuple[list, int]:
        """Fetches a specific page of events from the Flask API and formats them."""
        params = {
            "page": page,
            "per_page": per_page,
            "acid": self.acid_val,
            "event_type": self.raw_event_type,
        }
        if self.a_date:
            params["after"] = self.a_date.isoformat()
        if self.b_date:
            params["before"] = self.b_date.isoformat()
        api_url = f"http://{DATABASE_IP}:5011/api/v2/events/filter"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params) as resp:
                if resp.status != 200:
                    return [], 0
                data = await resp.json()
        
        results = data.get("results", [])
        total_count = data.get("count", 0)

        event_list = []
        for item in results:
            event = item.get("event", {})
            e_type = event.get("eventType")
            
            ts_raw = event.get("timestamp", {})
            if isinstance(ts_raw, dict) and "$date" in ts_raw:
                date_val = ts_raw["$date"]
                if isinstance(date_val, str):
                    dt = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
                else:
                    dt = datetime.fromtimestamp(date_val / 1000.0)
            else:
                dt = datetime.now()
                
            ts_str = dt.strftime('%Y-%m-%d %H:%M')

            if e_type == "online":
                event_list.append(f"**Online:** {ts_str}")
            elif e_type == "offline":
                event_list.append(f"**Offline:** {ts_str}")
            elif e_type == "teleporation":
                if self.verbose == "No":
                    event_list.append(f"**Teleporation:** {ts_str}")
                else:
                    event_list.append(f"**Teleporation |** **Old Pos:** ({event.get('oldLatitude')}, {event.get('oldLongitude')}) **New Pos:** ({event.get('newLatitude')},{event.get('newLongitude')}) **Dist:** {event.get('distance')}m **Time:** {ts_str}")
            elif e_type == "aircraftChange":
                if self.verbose == "No":
                    event_list.append(f"**Aircraft Change:** {ts_str}")
                else:
                    event_list.append(f"**Aircraft Change |** **Old:** {event.get('oldAircraft')} **New:** {event.get('newAircraft')} **Time:** {ts_str}")
            elif e_type == "callsignChange":
                if self.verbose == "No":
                    event_list.append(f"**Callsign Change:** {ts_str}")
                else:
                    event_list.append(f"**Callsign Change |** **Old:** {event.get('oldCallsign')} **New:** {event.get('newCallsign')} **Time:** {ts_str}")
        
        return event_list, total_count
    
    async def fetch_page_callback(self, page: int, per_page: int) -> list:
        """Wrapper method used exclusively by the ServerPaginatedEmbed to grab the items list."""
        items, _ = await self.fetch_and_format_events(page, per_page)
        return items

    async def on_submit(self, interaction: discord.Interaction):
        try:
            self.acid_val = int(self.acid.value)
        except ValueError:
            return await interaction.response.send_message(
                "**Error:** Invalid input. Ensure ACID is a number.", 
                ephemeral=True
            )
        
        try:
            if self.before.value != "":
                self.b_date = datetime.strptime(self.before.value, "%Y-%m-%d %H:%M")
            else:
                self.b_date = None
            if self.after.value != "":
                self.a_date = datetime.strptime(self.after.value, "%Y-%m-%d %H:%M")
            else:
                self.a_date = None
        except ValueError:
            return await interaction.response.send_message(
                "**Error:** Invalid input. Ensure dates match the `YYYY-MM-DD HH:MM` format.", 
                ephemeral=True
            )

        await interaction.response.defer(thinking=True)

        if self.event_type == "on-off":
            self.raw_event_type = "on-off"
        elif self.event_type == "tp":
            self.raw_event_type = "teleporation"
        elif self.event_type == "callsign":
            self.raw_event_type = "callsignChange"
        elif self.event_type == "aircraft":
            self.raw_event_type = "aircraftChange"
        elif self.event_type == "all":
            self.raw_event_type = "All"
            
        initial_items, total_items = await self.fetch_and_format_events(1, 10)

        if total_items == 0:
            return await interaction.followup.send("No events found matching your criteria.")

        # 3. Initialize the Paginator passing the class method as the callback
        embed = ServerPaginatedEmbed(
            initial_items=initial_items,
            total_items=total_items,
            fetch_callback=self.fetch_page_callback,
            title=f"Queried Events (ACID: {self.acid_val})",
            description=f"{total_items} event(s) found.",
            items_per_page=10
        )
        await interaction.followup.send(embed=embed.embed, view=embed)

class EventSummaryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.event_type = None
        self.verbose = None

    @discord.ui.select(
        placeholder="1. Select Event Type",
        options=[
            discord.SelectOption(label="All Events", value="all"), # <--- ADD THIS LINE
            discord.SelectOption(label="Online or Offline", value="on-off"),
            discord.SelectOption(label="Teleportation", value="tp"),
            discord.SelectOption(label="Callsign Change", value="callsign"),
            discord.SelectOption(label="Aircraft Change", value="aircraft"),
        ],
        custom_id="select_event"
    )
    async def select_event_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.event_type = select.values[0]
        await interaction.response.defer()

    @discord.ui.select(
        placeholder="2. Enable Verbose?",
        options=[
            discord.SelectOption(label="Yes", value="Yes"),
            discord.SelectOption(label="No", value="No"),
        ],
        custom_id="select_verbose"
    )
    async def select_verbose_callback(self, interaction: discord.Interaction, select: discord.ui.Select):
        self.verbose = select.values[0]
        await interaction.response.defer()

    @discord.ui.button(label="Continue to Details", style=discord.ButtonStyle.success, row=2)
    async def continue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.event_type or not self.verbose:
            return await interaction.response.send_message(
                "Please select both an Event Type and Verbose option first!", 
                ephemeral=True
            )
        
        modal = EventSummaryModal(self.event_type, self.verbose)
        await interaction.response.send_modal(modal)

class QueryDatabase(commands.Cog):
    def __init__(self):
        super().__init__()
    
    def isValidRegex(self, pattern):
        try:
            re.compile(pattern)
            return True
        except re.error:
            return False

    def parse_regex_input(self, pattern_str: str):
        """
        Strips forward slashes from a regex string and extracts flags.
        Example: "/^ANONYM$/i" returns ("^ANONYM$", "i")
        Example: "ANONYM" returns ("ANONYM", "")
        """
        match = re.match(r'^/(.+)/([a-z]*)$', pattern_str)
        if match:
            return match.group(1), match.group(2) # Returns (pattern, flags)
        
        # Fallback just in case the user forgets the slashes
        return pattern_str, ""
        
    database_query = app_commands.Group(name="database_query", description="Commands for doing background checks on users from the database.")
    
    @database_query.command(name="callsign-cross-check", description="Does a cross account callsign similarity pairing.")
    @app_commands.describe(acid="The account ID of the source account.", pattern="Search multiple source accounts by a regex expression.")
    async def crossAccountCallsignSearch(self, interaction: discord.Interaction, acid: int = None, pattern: str = None):
        # parameter checks
        if (acid and pattern) or (not acid and not pattern):
            embed = discord.Embed(
                title="Failed",
                description="You must either give the acid or a pattern and not both.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        if pattern is not None and not self.isValidRegex(pattern):
            embed = discord.Embed(
                title="Failed",
                description="Your regex is not valid. Could not compile.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        await interaction.response.defer()

        # Define the pagination callback inside the command closure
        async def fetch_page_callback(page: int, per_page: int) -> list:
            params = {
                "page": page,
                "per_page": per_page
            }
            if acid: params["acid"] = acid
            if pattern: params["pattern"] = pattern

            api_url = f"http://{DATABASE_IP}:5011/api/v2/callsign-cross-check"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, params=params) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()

            results = data.get("results", [])
            formatted_items = []
            for item in results:
                formatted_items.append(
                    f"**GeoFS ACID:** {item.get('accountID')}, "
                    f"**Callsign Hit(s):** {', '.join(item.get('matchedDetails', []))}, "
                    f"**Current Callsign:** {item.get('currentCallsign')}"
                )
            return formatted_items

        # Fetch the very first page to establish total count and initial items
        params = {"page": 1, "per_page": 10}
        if acid: params["acid"] = acid
        if pattern: params["pattern"] = pattern

        api_url = f"http://{DATABASE_IP}:5011/api/v2/callsign-cross-check"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("Failed to contact the database API.")
                data = await resp.json()

        total_items = data.get("count", 0)
        
        if total_items == 0:
            embed = discord.Embed(
                title="No Matches",
                description="No accounts were found sharing non-empty past callsigns with the seed set.",
                color=discord.Color.yellow()
            )
            return await interaction.followup.send(embed=embed)

        initial_items = []
        for item in data.get("results", []):
            initial_items.append(
                f"**GeoFS ACID:** {item.get('accountID')}, "
                f"**Callsign Hit(s):** {', '.join(item.get('matchedDetails', []))}, "
                f"**Current Callsign:** {item.get('currentCallsign')}"
            )

        # Initialize the server paginated embed with our callback
        embed = ServerPaginatedEmbed(
            initial_items=initial_items,
            total_items=total_items,
            fetch_callback=fetch_page_callback,
            title="Callsign Hits",
            description=f"{total_items} Hit(s) | Accounts that share non-empty past callsigns with the seed accounts.",
            items_per_page=10
        )
        
        await interaction.followup.send(embed=embed.embed, view=embed)

    @database_query.command(name="query-acids", description="Search by callsign for accounts from OspreyEyesDB.")
    @app_commands.describe(
        exact_callsign="Finds all accounts with a past callsign matching the query. (Case-insensitive)",
        pattern="Search via a RegEx pattern. (ChatGPT it or somthing)",
        verbose="Retrieves extra information."
    )
    async def query_Acids(
        self,
        interaction: discord.Interaction,
        exact_callsign: str | None = None,
        pattern: str | None = None,
        verbose: bool = False
    ):
        if (exact_callsign and pattern) or (not exact_callsign and not pattern):
            embed = discord.Embed(
                title="Failed",
                description="You must provide either an exact callsign or a pattern, but not both.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed)
        
        if pattern is not None and not self.isValidRegex(pattern):
            embed = discord.Embed(
                title="Failed",
                description="Your regex is not valid. Could not compile.",
                color=discord.Color.red()
            )
            return await interaction.response.send_message(embed=embed)

        await interaction.response.defer()

        # Define the pagination callback
        async def fetch_page_callback(page: int, per_page: int) -> list:
            params = {
                "page": page,
                "per_page": per_page
            }
            if exact_callsign: params["exact_callsign"] = exact_callsign
            if pattern: params["pattern"] = pattern

            api_url = f"http://{DATABASE_IP}:5011/api/v2/users/search"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url, params=params) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()

            results = data.get("results", [])
            formatted_items = []
            for doc in results:
                if verbose:
                    formatted_items.append(f"**ACID**: {doc.get('accountID')} | **Online**: {doc.get('Online')} | **Current Aircraft**: {doc.get('currentAircraft')} | **Current Callsign**: {doc.get('currentCallsign')} | **Last Online**: {doc.get('lastOnline')}")
                else:
                    formatted_items.append(f"**ACID**: {doc.get('accountID')} | **Online**: {doc.get('Online')}")
            return formatted_items

        # Fetch the first page to get the total count
        params = {"page": 1, "per_page": 10}
        if exact_callsign: params["exact_callsign"] = exact_callsign
        if pattern: params["pattern"] = pattern

        api_url = f"http://{DATABASE_IP}:5011/api/v2/users/search"
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("Failed to contact the database API.")
                data = await resp.json()

        total_items = data.get("count", 0)

        if total_items == 0:
            embed = discord.Embed(
                title="No Matches",
                description="No accounts were found with past callsigns matching the given query.",
                color=discord.Color.yellow()
            )
            return await interaction.followup.send(embed=embed)

        # Format initial items
        initial_items = []
        for doc in data.get("results", []):
            if verbose:
                initial_items.append(f"**ACID**: {doc.get('accountID')} | **Online**: {doc.get('Online')} | **Current Aircraft**: {doc.get('currentAircraft')} | **Current Callsign**: {doc.get('currentCallsign')} | **Last Online**: {doc.get('lastOnline')}")
            else:
                initial_items.append(f"**ACID**: {doc.get('accountID')} | **Online**: {doc.get('Online')}")

        search_term = exact_callsign if exact_callsign else pattern
        embed = ServerPaginatedEmbed(
            initial_items=initial_items,
            total_items=total_items,
            fetch_callback=fetch_page_callback,
            title="Queried Account IDs",
            description=f"{total_items} account(s) found for **{search_term}**",
            items_per_page=10
        )
        
        await interaction.followup.send(embed=embed.embed, view=embed)

    @database_query.command(name="account_report", description="Pull a full account report.")
    @app_commands.describe(
        acid="The GeoFS Account ID for the account."
    )
    async def account_report(self, interaction: discord.Interaction, acid: int):
        await interaction.response.defer()
        params = {
            "acid": acid
        }
        api_url = f"http://{DATABASE_IP}:5011/api/v2/users/"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params) as resp:
                if resp.status != 200:
                    return [], 0
                data = await resp.json()
        if not data:
            embed = discord.Embed(
                title="Failed",
                description=(
                    "Could not find that account."
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return

        json_text = bson_dumps(data, indent=2)
        fp = BytesIO(json_text.encode("utf-8"))
        fp.seek(0)

        report_embed = discord.Embed(
            title=f"Account Report for ACID {acid}",
            description="Attached is the full document from the database.",
            color=discord.Color.blue()
        )

        await interaction.followup.send(
            embed=report_embed,
            file=discord.File(fp, filename=f"account_{acid}.json")
        )

    @database_query.command(name="earliest_detection", description="Get the date of the earliest logged event.")
    @app_commands.describe(
        acid="The GeoFS Account ID for the account."
    )
    async def account_creation(self, interaction: discord.Interaction, acid: int):
        await interaction.response.defer()

        api_url = f"http://{DATABASE_IP}:5011/api/v2/events/earliest"
        params = {"acid": acid}

        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, params=params) as resp:
                if resp.status == 404:
                    embed = discord.Embed(
                        title="No Events",
                        description="No events recorded for this account, or the account doesn't exist.",
                        color=discord.Color.yellow()
                    )
                    return await interaction.followup.send(embed=embed)
                elif resp.status != 200:
                    embed = discord.Embed(
                        title="Failed",
                        description="Failed to contact the database API.",
                        color=discord.Color.red()
                    )
                    return await interaction.followup.send(embed=embed)
                
                data = await resp.json()

        event = data.get("event", {})
        if not event:
            return await interaction.followup.send("No events recorded for this account.")

        ts_raw = event.get("timestamp", {})
        if isinstance(ts_raw, dict) and "$date" in ts_raw:
            date_val = ts_raw["$date"]
            if isinstance(date_val, str):
                dt = datetime.fromisoformat(date_val.replace("Z", "+00:00"))
            else:
                dt = datetime.fromtimestamp(date_val / 1000.0)
            ts_str = dt.strftime('%Y-%m-%d %H:%M UTC')
        else:
            ts_str = str(ts_raw)  # Fallback just in case

        report_embed = discord.Embed(
            title="Earliest Detection",
            description=f"The earliest event was a **{event.get('eventType')}** at **{ts_str}**",
            color=discord.Color.blue()
        )

        await interaction.followup.send(embed=report_embed)

    @database_query.command(name="event_summary", description="Get a summary of an event.")
    async def log_event(self, interaction: discord.Interaction):
        view = EventSummaryView()
        await interaction.response.send_message(
            "Please configure the event settings below, then click Continue:", 
            view=view,
            ephemeral=True
        )


async def setup(bot: TreeDiagramPublic):
    await bot.add_cog(QueryDatabase())