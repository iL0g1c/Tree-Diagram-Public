import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import os
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.collation import Collation
from collections import defaultdict
from datetime import datetime
import re
from io import StringIO
import json
from bson.json_util import dumps as bson_dumps
from io import BytesIO

from treeDiagramPublic import TreeDiagramPublic
from tools.paginationEmbed import PaginatedEmbed


load_dotenv()
DATABASE_TOKEN = os.getenv('DATABASE_TOKEN')
DATABASE_NAME = os.getenv('DATABASE_NAME')
DATABASE_IP = os.getenv('DATABASE_IP')
DATABASE_USER = os.getenv('DATABASE_USER')

class EventSummaryModal(discord.ui.Modal):
    def __init__(self, event_type: str, verbose: str, mongo_db_client):
        super().__init__(title=f"Details for {event_type}")
        self.event_type = event_type
        self.verbose = verbose
        self.mongo_db_client = mongo_db_client

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

    async def get_filtered_user_events(
        self,
        collection, 
        acid: int = None, 
        event_type: str = "all", # Defaulted to "all" for convenience
        after_date: datetime = None, 
        before_date: datetime = None
    ):
        """
        Retrieves, filters, and sorts events from the users collection.
        Supports special event types like 'all' and 'on-off'.
        """
        pipeline = []

        # Stage 1: Initial Match
        doc_match = {}
        if acid is not None:
            doc_match["accountID"] = acid
            
        if doc_match:
            pipeline.append({"$match": doc_match})

        # Stage 2: Unwind
        pipeline.append({"$unwind": "$events"})

        # Stage 3: Event-Level Match
        event_match = {}
        
        # --- UPDATED EVENT TYPE LOGIC ---
        if event_type and event_type.lower() != "all":
            if event_type.lower() == "on-off":
                # Match if the event is either online OR offline
                event_match["events.eventType"] = {"$in": ["online", "offline"]}
            else:
                # Exact match for any other specific string (e.g., "banned", "kicked")
                event_match["events.eventType"] = event_type
                
        # Build the date query dynamically
        if after_date or before_date:
            event_match["events.timestamp"] = {}
            if after_date:
                event_match["events.timestamp"]["$gte"] = after_date
            if before_date:
                event_match["events.timestamp"]["$lte"] = before_date
                
        if event_match:
            pipeline.append({"$match": event_match})

        # Stage 4: Sort (Descending: Newest first)
        pipeline.append({"$sort": {"events.timestamp": -1}})

        # Stage 5: Project
        pipeline.append({
            "$project": {
                "_id": 0,
                "accountID": 1,
                "event": "$events" # Keeps the entire event object
            }
        })

        # Execute
        cursor = collection.aggregate(pipeline)
        events = await cursor.to_list(length=None)
        
        return events

    async def on_submit(self, interaction: discord.Interaction):
        try:
            acid_val = int(self.acid.value)
        except ValueError:
            return await interaction.response.send_message(
                "**Error:** Invalid input. Ensure ACID is a number.", 
                ephemeral=True
            )
        
        try:
            if self.before.value != "":
                b_date = datetime.strptime(self.before.value, "%Y-%m-%d %H:%M")
            else:
                b_date = datetime.max
            if self.after.value != "":
                a_date = datetime.strptime(self.after.value, "%Y-%m-%d %H:%M")
            else:
                a_date = datetime.min
        except ValueError:
            return await interaction.response.send_message(
                "**Error:** Invalid input. Ensure dates match the `YYYY-MM-DD HH:MM` format.", 
                ephemeral=True
            )

        await interaction.response.defer(thinking=True)

        collection = self.mongo_db_client[DATABASE_NAME]["users"]

        if self.event_type == "on-off":
            raw_event_type = "on-off"
        elif self.event_type == "tp":
            raw_event_type = "teleporation"
        elif self.event_type == "callsign":
            raw_event_type = "callsignChange"
        elif self.event_type == "aircraft":
            raw_event_type = "aircraftChange"
        elif self.event_type == "all":
            raw_event_type = "All"
            
        results = await self.get_filtered_user_events(
            collection=collection,
            acid=acid_val,
            event_type=raw_event_type,
            after_date=a_date,
            before_date=b_date
        )
        event_list = []
        for event in results:
            if event['event']["eventType"] == "online":
                event_list.append(f"**Online:** {event['event']['timestamp'].strftime('%Y-%m-%d %H:%M')}")
            elif event['event']["eventType"] == "offline":
                event_list.append(f"**Offline:** {event['event']['timestamp'].strftime('%Y-%m-%d %H:%M')}")
            elif event['event']["eventType"] == "teleporation":
                if self.verbose == "No":
                    event_list.append(f"**Teleporation:** {event['event']['timestamp'].strftime('%Y-%m-%d %H:%M')}")
                else:
                    event_list.append(f"**Teleporation |** **Old Position:** ({event['event']['oldLatitude']}, {event['event']['oldLongitude']}) **New Position:** ({event['event']['newLatitude']},{event['event']['newLongitude']}) **Distance:** {event['event']['distance']} Meters **Timestamp:** {event['event']['timestamp'].strftime('%Y-%m-%d %H:%M')}")
            elif event['event']["eventType"] == "aircraftChange":
                if self.verbose == "No":
                    event_list.append(f"**Aircraft Change:** {event['event']['timestamp'].strftime('%Y-%m-%d %H:%M')}")
                else:
                    event_list.append(f"**Aircraft Change |** **Old Aircraft:** {event['event']['oldAircraft']} **New Aircraft:** {event['event']['newAircraft']} **Timestamp:** {event['event']['timestamp'].strftime('%Y-%m-%d %H:%M')}")
            elif event['event']["eventType"] == "callsignChange":
                if self.verbose == "No":
                    event_list.append(f"**Callsign Change:** {event['event']['timestamp'].strftime('%Y-%m-%d %H:%M')}")
                else:
                    event_list.append(f"**Callsign Change |** **Old Callsign:** {event['event']['oldCallsign']} **New Callsign:** {event['event']['newCallsign']} **Timestamp:** {event['event']['timestamp'].strftime('%Y-%m-%d %H:%M')}")

        # create results embed
        embed = PaginatedEmbed(
            event_list,
            title=f"Queried Events",
            description=f"{len(event_list)} event(s)"
        )
        await interaction.followup.send(embed=embed.embed, view=embed)

class EventSummaryView(discord.ui.View):
    def __init__(self, mongo_db_client):
        super().__init__(timeout=180)
        self.event_type = None
        self.verbose = None
        self.mongo_db_client = mongo_db_client

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
        
        modal = EventSummaryModal(self.event_type, self.verbose, self.mongo_db_client)
        await interaction.response.send_modal(modal)

class QueryDatabase(commands.Cog):
    def __init__(self):
        super().__init__()
        mongodbURI = f"mongodb://{DATABASE_USER}:{DATABASE_TOKEN}@{DATABASE_IP}:27017/?directConnection=true&serverSelectionTimeoutMS=2000&authSource={DATABASE_NAME}"
        self.mongo_db_client = AsyncIOMotorClient(mongodbURI)
    
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
                description=(
                    "You must either give the acid or a pattern and not both."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        if pattern is not None and not self.isValidRegex(pattern):
            embed = discord.Embed(
                title="Failed",
                description=(
                    "Your regex is not valid. Could not compile."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        await interaction.response.defer()

        if pattern is not None and not str(pattern).strip():
            await interaction.followup.send(
                embed=discord.Embed(
                    title="Failed",
                    description="Pattern cannot be empty or whitespace.",
                    color=discord.Color.red()
                )
            )
            return
                
        # Fetch seed documents
        collection = self.mongo_db_client[DATABASE_NAME]["users"]

        if pattern:
            # Parse the input for slashes and valid MongoDB flags (i, m, x, s)
            core_pattern, flags = self.parse_regex_input(pattern)
            regex_query = {"$regex": core_pattern}
            
            valid_mongo_flags = set("imxs")
            safe_flags = "".join(f for f in flags if f in valid_mongo_flags)
            
            if safe_flags:
                regex_query["$options"] = safe_flags

            seed_documents = collection.find({
                "pastCallsigns": regex_query
            }).max_time_ms(2000)

        if acid:
            seed_documents = collection.find({
                "accountID": acid
            })

        parsed_seed_documents = await seed_documents.to_list(length=None)

        # Flatten & dedupe all pastCallsigns from the seed docs
        seed_callsigns = {
            cs.strip()
            for doc in parsed_seed_documents
            for cs in doc.get("pastCallsigns", [])
            if isinstance(cs, str) and cs.strip()
        }

        seed_cs_to_acids = defaultdict(set)
        for _doc in parsed_seed_documents:
            _acid = _doc.get("accountID")
            for _cs in _doc.get("pastCallsigns", []):
                if isinstance(_cs, str):
                    _cs2 = _cs.strip()
                    if _cs2:
                        seed_cs_to_acids[_cs2].add(_acid)

        seed_account_ids = {
            d.get("accountID") for d in parsed_seed_documents if d.get("accountID") is not None
        }

        if not seed_callsigns:
            embed = discord.Embed(
                title="No Seed Callsigns",
                description="No non-empty past callsigns were found in the seed documents.",
                color=discord.Color.yellow()
            )
            await interaction.followup.send(embed=embed)
            return
        
        seed_object_ids = {
            doc.get("_id")
            for doc in parsed_seed_documents
            if doc.get("_id") is not None
        }

        query = {
            "pastCallsigns": {"$in": list(seed_callsigns)}
        }

        # Exclude the seed accounts themselves
        if seed_account_ids:
            query["accountID"] = {"$nin": list(seed_account_ids)}
        elif seed_object_ids:
            # fallback if accountID isn't present
            query["_id"] = {"$nin": list(seed_object_ids)}

        
        # find all accounts that have a past callsign of a past callsign of the seed documents.

        second_generation_callsigns = collection.find(query)
        parsed_second_generation_callsigns = await second_generation_callsigns.to_list(length=None)
        
        callsign_list = []
        for doc in parsed_second_generation_callsigns:
            past = [cs for cs in doc.get("pastCallsigns", []) if isinstance(cs, str) and cs.strip()]
            
            # Use seed_callsigns instead of seed_callsigns_lower
            matched = [cs for cs in past if cs in seed_callsigns] 
            
            if matched:
                matched_details = []
                for cs in matched:
                    # Removed .lower() from the .get() method
                    acids = sorted(a for a in seed_cs_to_acids.get(cs, set()) if a is not None)
                    if acids:
                        matched_details.append(f"{cs} (seed ACID(s): {', '.join(map(str, acids))})")
                    else:
                        matched_details.append(cs)
                callsign_list.append(
                    f"**GeoFS ACID:** {doc.get('accountID')}, "
                    f"**Callsign Hit(s):** {', '.join(matched_details)}, "
                    f"**Current Callsign:** {doc.get('currentCallsign')}"
                )
        if not callsign_list:
            embed = discord.Embed(
                title="No Matches",
                description="No accounts were found sharing non-empty past callsigns with the seed set.",
                color=discord.Color.yellow()
            )
            await interaction.followup.send(embed=embed)
            return

        embed = PaginatedEmbed(
            callsign_list,
            title="Callsign Hits",
            description=f"{len(callsign_list)} Hit(s) | Accounts that share non-empty past callsigns with the seed accounts."
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
        # verify parameters
        inputs = [exact_callsign, pattern]
        provided = [x for x in inputs if x is not None]

        if len(provided) != 1:
            embed = discord.Embed(
                title="Failed",
                description=(
                    "You must either give the a callsign or a pattern and not both."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return
        
        if pattern is not None and not self.isValidRegex(pattern):
            embed = discord.Embed(
                title="Failed",
                description=(
                    "Your regex is not valid. Could not compile."
                ),
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed)
            return

        await interaction.response.defer()
        collection = self.mongo_db_client[DATABASE_NAME]["users"]

        if exact_callsign:
            results = collection.find({
                "pastCallsigns": {
                    "$elemMatch": {
                        "$regex": f"^{re.escape(exact_callsign)}$",
                        "$options": "i"
                    }
                }
            })
        
        if pattern:
            # Parse the input for slashes and valid MongoDB flags (i, m, x, s)
            core_pattern, flags = self.parse_regex_input(pattern)
            regex_query = {"$regex": core_pattern}
            
            valid_mongo_flags = set("imxs")
            safe_flags = "".join(f for f in flags if f in valid_mongo_flags)
            
            if safe_flags:
                regex_query["$options"] = safe_flags

            results = collection.find({
                "pastCallsigns": regex_query
            }).max_time_ms(2000)

        parsed_accounts = await results.to_list(length=500)
        account_list = []
        if parsed_accounts:
            for document in parsed_accounts:
                if verbose:
                    account_list.append(f"**ACID**: {document['accountID']} | **Online**: {document['Online']} | **Current Aircraft**: {document['currentAircraft']} | **Current Callsign**: {document['currentCallsign']} | **Last Online**: {document['lastOnline']}")
                else:
                    account_list.append(f"**ACID**: {document['accountID']} | **Online**: {document['Online']}")
        else:
            embed = discord.Embed(
                title="No Matches",
                description="No accounts were found with past callsigns matching the given.",
                color=discord.Color.yellow()
            )
            await interaction.followup.send(embed=embed)
            return
        
        embed = PaginatedEmbed(
            account_list,
            title=f"Queried Acccount IDs",
            description=f"{len(account_list)} accounts(s) for **{exact_callsign if exact_callsign else pattern}**"
        )
        await interaction.followup.send(embed=embed.embed, view=embed)

    @database_query.command(name="account_report", description="Pull a full account report.")
    @app_commands.describe(
        acid="The GeoFS Account ID for the account."
    )
    async def account_report(self, interaction: discord.Interaction, acid: int):
        await interaction.response.defer()
        collection = self.mongo_db_client[DATABASE_NAME]["users"]
        account_doc = await collection.find_one({
            "accountID": acid
        })
        if not account_doc:
            embed = discord.Embed(
                title="Failed",
                description=(
                    "Could not find that account."
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return

        json_text = bson_dumps(account_doc, indent=2)
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
        collection = self.mongo_db_client[DATABASE_NAME]["users"]
        
        results = collection.find({"accountID": acid})
        parsed_results = await results.to_list(length=500)
        if parsed_results == []:
            embed = discord.Embed(
                title="Failed",
                description=(
                    "Could not find that account."
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return
        
        user_doc = parsed_results[0]
        events = user_doc.get("events", [])
        if not events:
            return await interaction.followup.send("No events recorded for this account.")
        earliest_event = events[0]
        for event in parsed_results[0]["events"]:
            if event["timestamp"] < earliest_event["timestamp"]:
                earliest_event = event

        report_embed = discord.Embed(
            title=f"Earliest detection",
            description=f"The earliest event was a {earliest_event['eventType']} at {earliest_event['timestamp']} UTC",
            color=discord.Color.blue()
        )

        await interaction.followup.send(embed=report_embed)

    @database_query.command(name="event_summary", description="Get a summary of an event.")
    async def log_event(self, interaction: discord.Interaction):
        view = EventSummaryView(self.mongo_db_client)
        await interaction.response.send_message(
            "Please configure the event settings below, then click Continue:", 
            view=view,
            ephemeral=True
        )


async def setup(bot: TreeDiagramPublic):
    await bot.add_cog(QueryDatabase())