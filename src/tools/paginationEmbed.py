import discord
from discord.ui import View, Button

class PaginatedEmbed(View):
    def __init__(self, items: list, title: str = "Paginated Embed", description: str = ""):
        super().__init__(timeout=None)
        self.items = items
        self.title = title
        self.description = description
        self.page = 0
        self.items_per_page = 10
        self.embed = None
        self.update_embed()
        self.update_buttons()

    def update_embed(self):
        """Updates the embed based on the current page."""
        start_index = self.page * self.items_per_page
        end_index = start_index + self.items_per_page
        items_on_page = self.items[start_index:end_index]

        self.embed = discord.Embed(
            title=self.title,
            description=self.description,
            color=discord.Color.blurple()
        )
        for i, item in enumerate(items_on_page, start=start_index + 1):
            self.embed.add_field(name="", value=item, inline=False)

        total_pages = (len(self.items) - 1) // self.items_per_page + 1
        self.embed.set_footer(text=f"Page {self.page + 1} of {total_pages}")


    def update_buttons(self):
        """Updates the state of the navigation buttons based on the current page."""
        max_pages = (len(self.items) - 1) // self.items_per_page

        # Update Previous button
        self.previous_page.disabled = self.page == 0
        self.previous_page.style = discord.ButtonStyle.danger if self.page == 0 else discord.ButtonStyle.green

        # Update Next button
        self.next_page.disabled = self.page == max_pages
        self.next_page.style = (
            discord.ButtonStyle.danger if self.page == max_pages else discord.ButtonStyle.green
        )

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.danger)
    async def previous_page(self, interaction: discord.Interaction, button: Button):
        """Handles the previous page button click."""
        if self.page > 0:
            self.page -= 1
            self.update_embed()
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embed, view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.green)
    async def next_page(self, interaction: discord.Interaction, button: Button):
        """Handles the next page button click."""
        max_pages = (len(self.items) - 1) // self.items_per_page
        if self.page < max_pages:
            self.page += 1
            self.update_embed()
            self.update_buttons()
            await interaction.response.edit_message(embed=self.embed, view=self)