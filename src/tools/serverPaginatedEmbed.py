import discord
from discord.ui import View, Button

class ServerPaginatedEmbed(View):
    def __init__(self, initial_items: list, total_items: int, fetch_callback, title: str = "Paginated Embed", description: str = "", items_per_page: int = 10):
        """
        initial_items: The list of items to display on the first page.
        total_items: The total amount of documents/records matching the query in the database.
        fetch_callback: An async function that accepts (page_number: int, items_per_page: int) 
                        and returns the formatted list of strings for that specific page.
        """
        super().__init__(timeout=None)
        self.fetch_callback = fetch_callback
        self.title = title
        self.description = description
        self.page = 1 # Server-side pagination is often 1-indexed
        self.items_per_page = items_per_page
        self.total_items = total_items
        self.current_items = initial_items
        self.embed = None
        
        self.update_embed()
        self.update_buttons()

    def update_embed(self):
        """Updates the embed based on the current items."""
        self.embed = discord.Embed(
            title=self.title,
            description=self.description,
            color=discord.Color.blurple()
        )
        for item in self.current_items:
            self.embed.add_field(name="", value=item, inline=False)

        # Calculate max pages securely, ensuring it's at least 1 even if total_items is 0
        total_pages = max(1, (self.total_items - 1) // self.items_per_page + 1)
        self.embed.set_footer(text=f"Page {self.page} of {total_pages}")

    def update_buttons(self):
        """Updates the state of the navigation buttons based on the current page."""
        max_pages = max(1, (self.total_items - 1) // self.items_per_page + 1)

        # Update Previous button
        self.previous_page.disabled = self.page <= 1
        self.previous_page.style = discord.ButtonStyle.danger if self.page <= 1 else discord.ButtonStyle.green

        # Update Next button
        self.next_page.disabled = self.page >= max_pages
        self.next_page.style = (
            discord.ButtonStyle.danger if self.page >= max_pages else discord.ButtonStyle.green
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.danger)
    async def previous_page(self, interaction: discord.Interaction, button: Button):
        """Handles the previous page button click."""
        if self.page > 1:
            self.page -= 1
            # Defer interaction to give the bot time to fetch from the database
            await interaction.response.defer()
            
            # Fetch new page data from the database using the callback function
            self.current_items = await self.fetch_callback(self.page, self.items_per_page)
            
            self.update_embed()
            self.update_buttons()
            await interaction.edit_original_response(embed=self.embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.green)
    async def next_page(self, interaction: discord.Interaction, button: Button):
        """Handles the next page button click."""
        max_pages = (self.total_items - 1) // self.items_per_page + 1
        if self.page < max_pages:
            self.page += 1
            # Defer interaction to give the bot time to fetch from the database
            await interaction.response.defer()
            
            # Fetch new page data from the database using the callback function
            self.current_items = await self.fetch_callback(self.page, self.items_per_page)
            
            self.update_embed()
            self.update_buttons()
            await interaction.edit_original_response(embed=self.embed, view=self)