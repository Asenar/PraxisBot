#!/usr/bin/python3

"""

Copyright (C) 2018 MonaIzquierda (mona.izquierda@gmail.com)
Copyright (C) 2020 Powi (powi@powi.fr)

This file is part of PraxisBot.

PraxisBot is free software: you can redistribute it and/or  modify
it under the terms of the GNU Affero General Public License, version 3,
as published by the Free Software Foundation.

PraxisBot is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with PraxisBot.  If not, see <http://www.gnu.org/licenses/>.

"""

import discord
import sys
import io
import re
import traceback
import time
import asyncio
import inspect
import datetime
from pytz import timezone
import sqlite3
import praxisbot
from plugins.core import CorePlugin
from plugins.trigger import TriggerPlugin
from plugins.moderation import ModerationPlugin
from plugins.board import BoardPlugin
from plugins.activity import ActivityPlugin
from plugins.archive import ArchivePlugin
from plugins.rolelist import RoleListPlugin
from plugins.poll import PollPlugin
from plugins.conversational_form import ConversationalFormPlugin
from plugins.emoji import EmojiPlugin
from plugins.http import HTTPPlugin
#from plugins.comic import ComicPlugin

########################################################################
# Init

if len(sys.argv) < 2:
	print("Usage: "+sys.argv[0]+" <BOT_TOKEN>")
	exit(0)

botToken = sys.argv[1]

########################################################################
# Human

class PraxisHuman(discord.Client):
	"""
	The main class of PraxisHuman
	"""

	async def on_ready(self):
		print("Human logged on as {0}".format(self.user))


########################################################################
# Bot

class PraxisBot(discord.Client):
	"""
	The main class of PraxisBot
	"""

	def __init__(self):
		super().__init__()

		self.mode = "testing"
		self.dbprefix = "pb_"
		self.dbfile = "databases/praxisbot-{}.db".format(self.mode)
		self.dbcon = sqlite3.connect(self.dbfile, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
		self.banned_members = {}

		with self.dbcon:
			#Server list
			self.dbcon.execute("CREATE TABLE IF NOT EXISTS "+self.dbprefix+"servers(discord_sid INTEGER PRIMARY KEY, command_prefix TEXT)");

		self.shell = praxisbot.Shell(self, self.dbprefix, self.dbcon, self.dbfile)

		self.loopstarted = False

	def load_all_plugins(self):
		self.shell.load_plugin(CorePlugin)
		self.shell.load_plugin(TriggerPlugin)
		self.shell.load_plugin(ModerationPlugin)
		self.shell.load_plugin(BoardPlugin)
		self.shell.load_plugin(ActivityPlugin)
		self.shell.load_plugin(ArchivePlugin)
		self.shell.load_plugin(RoleListPlugin)
		self.shell.load_plugin(PollPlugin)
		self.shell.load_plugin(ConversationalFormPlugin)
		self.shell.load_plugin(EmojiPlugin)
		self.shell.load_plugin(HTTPPlugin)
		#self.shell.load_plugin(MathPlugin)
		#self.shell.load_plugin(ComicPlugin)

	async def on_ready(self):
		print("Bot logged on as {0}".format(self.user))

		self.load_all_plugins()
		if self.mode == "testing":
			await self.get_channel(461819232884097054).send("Je suis prêt")

		if not self.loopstarted:
			self.loopstarted = True
			prevTime = time.time()
			for p in self.shell.plugins:
				for g in self.guilds:
					scope = self.shell.create_scope(g, [""])
					scope.channel = self.shell.get_default_channel(g)
					scope.user = g.me
					scope.permission = praxisbot.UserPermission.Script
					
					try:
						await p.on_ready(scope)
					except:
						pass

			while True:
				currTime = time.time()
				sleepDuration = 5 - (currTime - prevTime)
				prevTime = currTime
				if sleepDuration > 0:
					await asyncio.sleep(sleepDuration)

				for p in self.shell.plugins:
					for s in self.guilds:
						scope = self.shell.create_scope(s, [""])
						scope.channel = self.shell.get_default_channel(s)
						scope.user = s.me
						scope.permission = praxisbot.UserPermission.Script

						try:
							await p.on_loop(scope)
						except:
							print(traceback.format_exc())
							pass
	
	async def on_raw_reaction_add(self, payload):
		try:
			chan = self.get_channel(payload.channel_id)
			message = await chan.fetch_message(payload.message_id)
			for r in message.reactions:
				async for u in r.users():
					await self.on_reaction_add(r,u)
		except AttributeError:
			pass
		
	async def on_reaction_add(self, reaction, user):
		if type(reaction.message.channel) == discord.DMChannel:
			return
		if user.__class__ != discord.Member:
			return
		if user.bot:
			return

		scope = self.shell.create_scope(reaction.message.guild, [""])
		scope.channel = reaction.message.channel
		scope.user = user
		scope.permission = praxisbot.UserPermission.Script

		for p in self.shell.plugins:
			try:
				await p.on_reaction(scope, reaction)
			except:
				pass

	async def on_message(self, message):
		if type(message.channel) == discord.DMChannel:
			return
		if message.author.__class__ != discord.Member:
			return
		if message.author.bot:
			return

		prefixes = ["-"]

		customCommandPrefix = self.shell.get_sql_data("servers", ["command_prefix"], {"discord_sid": int(message.guild.id)})
		if customCommandPrefix:
			prefixes.append(customCommandPrefix[0])

		scope = self.shell.create_scope(message.guild, prefixes)
		scope.channel = message.channel
		scope.user = message.author
		if message.author.id == message.guild.owner.id:
			scope.permission = praxisbot.UserPermission.Owner
		elif message.author.guild_permissions.administrator:
			scope.permission = praxisbot.UserPermission.Admin

		command_found = await self.shell.execute_command(scope, message.content)

		for p in self.shell.plugins:
			await p.on_message(scope, message, command_found)

		if command_found and scope.deletecmd:
			try:
				await message.delete()
			except:
				print("Attempt to delete command message failed")
				raise discord.DiscordException()
				pass


	async def on_member_join(self, member):
		try:
			scope = self.shell.create_scope(member.guild, [""])
			scope.channel = self.shell.get_default_channel(member.guild)
			scope.user = member.guild.me
			scope.permission = praxisbot.UserPermission.Script
			scope.vars["target"] = member.name+"#"+member.discriminator

			for p in self.shell.plugins:
				await p.on_member_join(scope) #Ask for each script to do its command on_member_join -> Trigger

		except:
			print(traceback.format_exc())
			pass

	async def on_member_remove(self, member):
		reason = "leave"

		if member.id in self.banned_members:
			accepted_time = datetime.datetime.now() - datetime.timedelta(minutes=1)
			if self.banned_members[member.id] > accepted_time:
				reason = "ban"

		try:
			scope = self.shell.create_scope(member.guild, [""])
			scope.channel = self.shell.get_default_channel(member.guild)
			scope.user = member.guild.me
			scope.permission = praxisbot.UserPermission.Script
			scope.vars["target"] = member.name+"#"+member.discriminator
			scope.vars["reason"] = reason

			for p in self.shell.plugins:
				await p.on_member_leave(scope)

		except:
			print(traceback.format_exc())
			pass

	async def on_member_ban(self, guild, member):
		self.banned_members[member.id] = datetime.datetime.now()
		ban_user = ""
		ban_target = ""
		ban_reason = ""
		ban_found_in_logs = False

		try:
			startTime = time.time()
			while not ban_found_in_logs:
				currTime = time.time()
				duration = (currTime - startTime)
				if duration > 60:
					break

				async for b in guild.audit_logs(action=discord.AuditLogAction.ban, limit=10):
					if b.target.id == member.id:
						user = b.user
						reason = b.reason

						if b.user.id == self.shell.client.user.id:
							#Try to find the true author (user) in the reason
							res = re.search("(.+#[0-9][0-9][0-9][0-9]) using (pre)?ban command", b.reason)
							if res:
								u = self.shell.find_member(res.group(1), guild) or await self.shell.fetch_user(res.group(1))
								if u:
									user = u
							res = re.search("using (pre)?ban command:(.+)", b.reason)
							if res:
								reason = res.group(2).strip()
								if res.group(1):
									reason += " (using preban command)."
								else:
									reason += " (using ban command)."

						ban_user = "{}#{}".format(user.name,user.discriminator)
						ban_reason = reason
						ban_target = b.target.name+"#"+b.target.discriminator
						ban_found_in_logs = True
						break
		except:
			print(traceback.format_exc())
			pass

		try:
			scope = self.shell.create_scope(guild, [""])
			scope.channel = self.shell.get_default_channel(guild)
			scope.user = guild.me
			scope.permission = praxisbot.UserPermission.Script
			scope.vars["reason"] = ban_reason
			scope.vars["user"] = ban_user
			scope.vars["target"] = member.name+"#"+member.discriminator

			for p in self.shell.plugins:
				await p.on_ban(scope)

		except:
			print(traceback.format_exc())
			pass

	async def on_member_unban(self, server, user):
		try:
			scope = self.shell.create_scope(server, [""])
			scope.channel = self.shell.get_default_channel(server)
			scope.user = server.me
			scope.permission = praxisbot.UserPermission.Script
			scope.vars["target"] = user.name+"#"+user.discriminator

			for p in self.shell.plugins:
				await p.on_unban(scope)

		except:
			print(traceback.format_exc())
			pass

########################################################################
# Execute

try:
	bot = PraxisBot()
	bot.run(botToken)

except KeyboardInterrupt:
	human.loop.run_until_complete(human.logout())
	bot.loop.run_until_complete(bot.logout())
