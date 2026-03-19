import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import os
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.collation import Collation
from collections import defaultdict
from datetime import datetime, timezone, timedelta
import re
from io import StringIO
import json
from bson.json_util import dumps as bson_dumps
from io import BytesIO

from treeDiagramPublic import TreeDiagramPublic
from tools.paginationEmbed import PaginatedEmbed
from tools.configManager import ConfigManager

class QueryDatabase(commands.Cog):
    def __init__(self):
        load_dotenv()
        DATABASE_TOKEN = os.getenv('DATABASE_TOKEN')
        self.DATABASE_NAME = os.getenv('DATABASE_NAME')
        DATABASE_IP = os.getenv('DATABASE_IP')
        DATABASE_USER = os.getenv('DATABASE_USER')
        mongodbURI = f"mongodb://{DATABASE_USER}:{DATABASE_TOKEN}@{DATABASE_IP}:27017/?directConnection=true&serverSelectionTimeoutMS=2000&authSource={self.DATABASE_NAME}"
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
        
    account_checks_group = app_commands.Group(name="account_checks", description="Commands for doing background checks on users from the database.")
    
    @account_checks_group.command(name="callsign-cross-check", description="Does a cross account callsign similarity pairing.")
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
        collection = self.mongo_db_client[self.DATABASE_NAME]["users"]

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
            })

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
        
        seed_account_ids = {
            doc.get("accountID")
            for doc in parsed_seed_documents
            if doc.get("accountID") is not None
        }
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

    @account_checks_group.command(name="query-callsigns", description="Pull a accounts past callsigns from OspreyEyesDB.")
    @app_commands.describe(acid="GeoFS Account ID")
    async def query(self, interaction: discord.Interaction, acid: int):
        await interaction.response.defer()
        collection = self.mongo_db_client[self.DATABASE_NAME]["users"]
        
        results = collection.find({"accountID": acid})
        parsed_results = await results.to_list(length=None)

        if len(parsed_results) > 1:
            embed = discord.Embed(
                title="Database Error 1",
                description=(
                    "Contact the Development Lead."
                ),
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return
        
        parsed_results = parsed_results[0]
        callsign_entries = []
        for callsign in parsed_results['pastCallsigns']:
            callsign_last_set = datetime(1970, 1, 1, tzinfo=timezone.utc)
            found_log = False
            for event in parsed_results['events']:
                if event['eventType'] == 'callsignChange' and event['newCallsign'] == callsign:
                    found_log = True
                    event_time = event['timestamp'].replace(tzinfo=timezone.utc)
                    if event_time > callsign_last_set:
                        callsign_last_set = event_time
            if not found_log:
                callsign_last_set = parsed_results['events'][0]['timestamp'].replace(tzinfo=timezone.utc)

            callsign_entries.append({"callsign": callsign, "last_set": callsign_last_set})

        callsign_entries.sort(key=lambda x: x["last_set"], reverse=True)
        callsign_list = [
            f"**Callsign**: {entry['callsign']} | **Last set**: {entry['last_set']}\n"
            for entry in callsign_entries
        ]

        # create results embed
        embed = PaginatedEmbed(
            callsign_list,
            title=f"Queried Callsigns",
            description=f"{len(callsign_list)} callsign(s)"
        )
        await interaction.followup.send(embed=embed.embed, view=embed)

    @account_checks_group.command(name="query-acids", description="Search by callsign for accounts from OspreyEyesDB.")
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
        collection = self.mongo_db_client[self.DATABASE_NAME]["users"]

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
            })

        parsed_accounts = await results.to_list(length=None)
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

    @account_checks_group.command(name="account_report", description="Pull a full account report.")
    @app_commands.describe(
        acid="The GeoFS Account ID for the account."
    )
    async def account_report(self, interaction: discord.Interaction, acid: int):
        await interaction.response.defer()
        collection = self.mongo_db_client[self.DATABASE_NAME]["users"]
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

async def setup(bot: TreeDiagramPublic):
    await bot.add_cog(QueryDatabase())