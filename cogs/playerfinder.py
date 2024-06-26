import discord
from discord.ext import commands, tasks
from collections import defaultdict
from requests_futures.sessions import FuturesSession

import asyncio
import re
import json
import os

GUILD_DDNET       = 252358080522747904
ROLE_MODERATOR    = 252523225810993153
ROLE_ADMIN        = 293495272892399616
CHAN_PLAYERFINDER = 1078979471761211462


def is_staff(member: discord.Member) -> bool:
    return any(r.id in (ROLE_ADMIN, ROLE_MODERATOR) for r in member.roles)


def check_conditions(ctx) -> bool:
    return ctx.guild is None or ctx.guild.id != GUILD_DDNET or ctx.channel.id != CHAN_PLAYERFINDER \
           or not is_staff(ctx.author)


class PlayerFinder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.servers_url = "https://master1.ddnet.tw/ddnet/15/servers.json"
        self.servers_info_url = 'https://info.ddnet.org/info'
        self.player_file = "data/find_players.json"
        self.players_online_filtered = {}
        self.sent_messages = []

    def cog_unload(self) -> None:
        self.find_players.cancel()

    def cog_load(self) -> None:
        self.find_players.start()

    @staticmethod
    async def get(url, **kwargs):
        with FuturesSession() as s:
            return await asyncio.wrap_future(s.get(url, timeout=1, **kwargs))

    def load_players(self):
        with open(self.player_file, 'r', encoding='utf-8') as f:
            players = json.load(f)
        return players

    async def server_filter(self):
        gamemodes = ['DDNet', 'Test', 'Tutorial', 'Block', 'Infection',
                     'iCTF', 'gCTF', 'Vanilla', 'zCatch', 'TeeWare',
                     'TeeSmash', 'Foot', 'xPanic', 'Monster']
        resp = await self.get(self.servers_info_url)
        servers = resp.json()
        data = servers.get('servers')
        ddnet_ips = []
        for i in data:
            sv_list = i.get('servers')
            for mode in gamemodes:
                server_lists = sv_list.get(mode)
                if server_lists is not None:
                    ddnet_ips += server_lists
        return ddnet_ips

    @staticmethod
    def format_address(address):
        address_match = re.match(r"tw-0.6\+udp://([\d\.]+):(\d+)", address)
        if address_match:
            ip, port = address_match.groups()
            return f"{ip}:{port}"
        return None

    async def players(self):
        resp = await self.get(self.servers_url)
        servers = resp.json()
        players = defaultdict(list)

        for server in servers["servers"]:
            server_addresses = []
            for address in server["addresses"]:
                formatted = self.format_address(address)
                if formatted is not None:
                    server_addresses.append(formatted)
            if "clients" in server["info"]:
                for player in server["info"]["clients"]:
                    for address in server_addresses:
                        players[player["name"]].append((server["info"]["name"], address))
        return players

    async def send_message(self, embed):
        try:
            if not self.sent_messages:
                self.sent_messages.append(await self.bot.get_channel(CHAN_PLAYERFINDER).send(embed=embed))

                channel = self.bot.get_channel(CHAN_PLAYERFINDER)
                async for message in channel.history(limit=20):
                    if message.embeds and message != self.sent_messages[0]:
                        await message.delete()
                        await asyncio.sleep(1)
            else:
                channel = self.bot.get_channel(CHAN_PLAYERFINDER)
                async for message in channel.history(limit=1):
                    if message != self.sent_messages[-1]:
                        await self.sent_messages[-1].delete()
                        self.sent_messages[-1] = await channel.send(embed=embed)
                        return

                last_message = self.sent_messages[-1]
                await last_message.edit(embed=embed)
                """Send a new embed if someone deletes the embed for some reason"""
        except discord.NotFound:
            self.sent_messages.append(await self.bot.get_channel(CHAN_PLAYERFINDER).send(embed=embed))

    @commands.command(name='list', hidden=True)
    async def send_player_list(self, ctx: commands.Context):
        """
        Uploads a text file containing all players currently in the search list.
        """
        if check_conditions(ctx):
            return

        with open(self.player_file, 'r', encoding='utf-8') as f:
            players = json.load(f)

        if not players:
            await ctx.send('No players found.')
        else:
            response = "Current List:\n"
            for i, (player, reason) in enumerate(players.items(), start=1):
                response += f"{i}. \"{player}\" for reason: {reason}\n"

            with open('data/player_list.txt', 'w', encoding='utf-8') as f:
                f.write(response)

            with open('data/player_list.txt', 'rb') as f:
                await ctx.send(file=discord.File(f, 'player_list.txt'))

            os.remove('data/player_list.txt')

    @commands.command(name='add', hidden=True)
    async def add_player_to_list(self, ctx: commands.Context, *, players: str):
        """
        Adds a player to the search list. Example:
        $add
        nameless tee
        blocker
        """
        if check_conditions(ctx):
            return

        new_players = {}
        with open(self.player_file, 'r', encoding='utf-8') as f:
            player_list = json.load(f)

        player_info = players.split("\n")
        for i in range(0, len(player_info), 2):
            player_name = player_info[i].strip()
            reason = player_info[i + 1].strip() if i + 1 < len(player_info) else "No reason provided"
            if player_name in player_list:
                await ctx.send(f'Player {player_name} is already in the search list')
            else:
                new_players[player_name] = reason
                player_list[player_name] = reason

        with open(self.player_file, 'w', encoding='utf-8') as f:
            json.dump(player_list, f)

        if new_players:
            message = "Added players:"
            for player, reason in new_players.items():
                message += f"\n{player}: {reason}"
            await ctx.send(message)

    @commands.command(name='rm', hidden=True)
    async def remove_player_from_list(self, ctx: commands.Context, *, player_names: str):
        """
        Removes a player from the watch list. Example:
        $rm
        player1
        player2
        player3
        """
        if check_conditions(ctx):
            return

        removed_players = []
        with open(self.player_file, 'r', encoding='utf-8') as f:
            players = json.load(f)
        with open(self.player_file, 'w', encoding='utf-8') as f:
            for player_name in player_names.split("\n"):
                player_name = player_name.strip()
                if player_name in players:
                    removed_players.append(player_name)
                    del players[player_name]
                else:
                    await ctx.send(f'Player {player_name} not found.')
            json.dump(players, f)
        if removed_players:
            await ctx.send(f'Removed players:\n{", ".join(removed_players)}.')
            self.players_online_filtered.clear()

    @commands.command(name='info', hidden=True)
    async def send_info(self, ctx: commands.Context, *, player_name: str):
        """
        Sends the info field of the provided player. Example:
        $info
        player1
        """
        if check_conditions(ctx):
            return

        with open(self.player_file, 'r', encoding='utf-8') as f:
            players = json.load(f)

        matched_players = [name for name in players.keys() if name.strip() == player_name.strip()]

        if not matched_players:
            await ctx.send(f'Player not in watchlist.')
        else:
            player_name = matched_players[0]
            reason = players.get(player_name, "No reason provided")
            await ctx.send(f"{player_name} was added with Reason: {reason}")

    @commands.command(hidden=True)
    async def edit_info(self, ctx: commands.Context, *, player_reason: str):
        """
        Edits the info field of the given player. Example:
        $edit_info
        player1
        <new reason>
        """
        if check_conditions(ctx):
            return
        lines = player_reason.strip().split('\n')
        player_name = lines[0].strip()
        reason = '\n'.join(lines[1:]).strip()

        with open(self.player_file, 'r', encoding='utf-8') as f:
            player_list = json.load(f)

        if player_name not in player_list:
            await ctx.send(f'Player {player_name} not found.')
        else:
            player_list[player_name] = reason

            with open(self.player_file, 'w', encoding='utf-8') as f:
                json.dump(player_list, f)

            await ctx.send(f'Reason for {player_name} updated to:\n{reason}')

    @commands.command(name='clear', hidden=True)
    async def clear_entire_players_list(self, ctx: commands.Context):
        """
        This command will clear the entire watch list. Careful!
        """
        if check_conditions(ctx):
            return

        with open(self.player_file, 'w', encoding='utf-8') as f:
            json.dump({}, f)
        await ctx.send('Player list cleared.')

    @commands.command(name='find')
    async def search_player(self, ctx, player_name):
        players_dict = await self.players()
        if player_name in players_dict:
            player_info = players_dict[player_name]
            message = f"Found {len(player_info)} server(s) with \"{player_name}\" currently playing:\n"
            for i, server in enumerate(player_info, 1):
                server_name, server_address = server
                message += f"{i}. Server: {server_name} — Link: <https://ddnet.org/connect-to/?addr={server_address}/>\n"
            await ctx.send(message)
        else:
            await ctx.send(f"There is currently no player online with the name \"{player_name}\"")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author == self.bot.user:
            if len(message.embeds) > 0 and message.id in self.sent_messages:
                try:
                    await message.delete()
                    self.sent_messages.remove(message.id)
                except Exception as error:
                    print(f"Error deleting message: {error}")

    @tasks.loop(seconds=30)
    async def find_players(self):
        players = self.load_players()
        server_filter_list = await self.server_filter()
        players_online = await self.players()

        self.players_online_filtered = {
            player_name: [
                server for i, server in enumerate(players_online[player_name])
                if server[1] in server_filter_list and i < 3
            ]
            for player_name in players
            if players_online[player_name] and any(
                server[1] in server_filter_list for server in players_online[player_name]
            )
        }

        player_embed = discord.Embed(color=0x00ff00)
        if self.players_online_filtered:
            player_embed.title = 'Found players'
            for i, player_name in enumerate(self.players_online_filtered.keys(), start=1):
                servers = self.players_online_filtered[player_name]
                server_field_value = ""
                reason = players.get(player_name, 'No reason provided')
                server_field_value += f'Reason: {reason}\n'

                for server in servers:
                    server_name, address = server
                    server_field_value += (
                        f"* Server: {server_name}"
                        f"\n * <https://ddnet.org/connect-to/?addr={address}/>\n"
                    )

                player_embed.add_field(
                    name=f"{i}. Player: {player_name}",
                    value=server_field_value,
                    inline=False
                )
        else:
            player_embed.title = 'No players found in the current iteration.'

        await self.send_message(player_embed)

    @find_players.before_loop
    async def before_find_players(self):
        await self.bot.wait_until_ready()

    @commands.command(name="stop_search", hidden=True)
    async def stop_player_search(self, ctx: commands.Context):
        """
        This command stops the player finder task.
        """
        if check_conditions(ctx):
            return

        if not self.find_players.is_running():
            await ctx.send("The player search process is not currently running.")
        else:
            if self.sent_messages:
                last_message = self.sent_messages[-1]
                await last_message.delete()
                self.sent_messages.clear()
            self.find_players.cancel()
            self.players_online_filtered.clear()
            await ctx.send("Process stopped.")

    @commands.command(name='start_search', hidden=True)
    async def start_player_search(self, ctx: commands.Context):
        """
        This command starts the player finder task.
        """
        if check_conditions(ctx):
            return

        if self.find_players.is_running():
            await ctx.send("The player search process is already running.")
        else:
            self.find_players.start()
            await ctx.send("Initializing search...")


async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerFinder(bot))
