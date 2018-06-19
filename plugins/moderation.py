"""

Copyright (C) 2018 MonaIzquierda (mona.izquierda@gmail.com)

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

import shlex
import argparse
import re
import discord
import traceback
import datetime
import io
import sqlite3
from io import StringIO
from plugin import Plugin
from scope import UserPermission
from scope import ExecutionScope
from scope import ExecutionBlock

class ModLevelType:
	User=0
	Role=1
	Channel=2

class ModerationPlugin(Plugin):
	"""
	Moderation commands
	"""

	name = "Moderation"

	def __init__(self, ctx, shell):
		super().__init__(ctx)

		try:
			with self.ctx.dbcon:
				self.ctx.dbcon.execute("CREATE TABLE IF NOT EXISTS "+self.ctx.dbprefix+"mod_levels(id INTEGER PRIMARY KEY, discord_sid INTEGER, name TEXT, priority INTEGER, type INTEGER, value TEXT, ban_timelimit INTEGER, ban_prioritylimit INTEGER, purge INTEGER)");

				try:
					self.ctx.dbcon.execute("ALTER TABLE "+self.ctx.dbprefix+"mod_levels ADD COLUMN purge INTEGER")
				except sqlite3.OperationalError:
					pass

				self.ctx.dbcon.execute("CREATE TABLE IF NOT EXISTS "+self.ctx.dbprefix+"ban_time(id INTEGER PRIMARY KEY, discord_sid INTEGER, discord_uid INTEGER, last_time DATETIME)");
		except:
			print(traceback.format_exc())


	def get_mod_level(self, member):
		if not member:
			return {
				"name":"",
				"priority":-1,
				"ban_timelimit":0,
				"ban_prioritylimit":-1,
				"purge":False
			}

		with self.ctx.dbcon:
			c = self.ctx.dbcon.cursor()
			for row in c.execute("SELECT type, value, name, priority, ban_timelimit, ban_prioritylimit, purge FROM "+self.ctx.dbprefix+"mod_levels WHERE discord_sid = ? ORDER BY priority DESC", [int(member.server.id)]):
				res = {
					"name":row[2],
					"priority":row[3],
					"ban_timelimit":row[4],
					"ban_prioritylimit":row[5],
					"purge":row[6]
				}

				if not row[4] or row[4] < 0:
					res["ban_timelimit"] = 0
				if not row[5] or row[5] < 0:
					res["ban_prioritylimit"] = 0
				if row[5] > res["priority"]:
					res["ban_prioritylimit"] = res["priority"]
				if row[6] and row[6] != 0:
					res["purge"] = 1
				else:
					res["purge"] = 0

				if row[0] == ModLevelType.User:
					if row[1] == member.id:
						return res
				if row[0] == ModLevelType.Role:
					for r in member.roles:
						if r.id == row[1]:
							return res
				if row[0] == ModLevelType.Channel:
					chan = self.ctx.find_channel("<#"+row[1]+">", member.server)
					if chan and chan.permissions_for(member).send_messages:
						return res

		return {
			"name":"",
			"priority": 0,
			"ban_timelimit": 0,
			"ban_prioritylimit": -1,
			"purge": False
		}

	async def execute_list_channels(self, command, options, scope):
		parser = argparse.ArgumentParser(description='List all channels of the server.', prog=command)
		parser.add_argument('--user', help='List channels from the point of view of this user.')

		args = await self.parse_options(scope.channel, parser, options)

		if not args:
			return scope

		if not args.user:
			user = scope.user
		else:
			user = self.ctx.find_member(args.user, scope.server)
			if not user:
				user = scopre.user

		clist = []
		for c in scope.server.channels:
			if c.permissions_for(scope.user).read_messages and c.permissions_for(user).read_messages:
				if c.type == discord.ChannelType.text:
					pos = (c.position+1)*10
					cat = c.server.get_channel(c.parent_id)
					if cat:
						pos = pos+1000*(cat.position+1)

					if c.permissions_for(user).send_messages:
						clist.append((pos, " :pencil2: "+c.name))
					else:
						clist.append((pos, " :eye: "+c.name))
				elif c.type == discord.ChannelType.voice:
					pos = (c.position+1)*10
					cat = c.server.get_channel(c.parent_id)
					if cat:
						pos = pos+1000*(cat.position+1)

					clist.append((pos, " :microphone2: "+c.name))
				elif c.type == discord.ChannelType.category:
					pos = (c.position+1)*1000
					clist.append((pos, "\n**"+c.name+"**"))

		clist = sorted(clist, key=lambda x: x[0])

		text = ""
		for c in clist:
			text = text+c[1]+"\n"

		await self.ctx.send_message(scope.channel, text)

		return scope

	async def execute_create_mod_level(self, command, options, scope):
		if scope.permission < UserPermission.Admin:
			await self.ctx.send_message(scope.channel, "Only admins can use this command.")
			return scope

		parser = argparse.ArgumentParser(description='Create a moderator level.', prog=command)
		parser.add_argument('name', help='Name of the moderator level.')
		parser.add_argument('priority', help='Priority of the moderator level.')
		parser.add_argument('--channel', help='All members that can write in this channel.')
		parser.add_argument('--role', help='All members of this role.')
		parser.add_argument('--user', help='A specific user.')

		args = await self.parse_options(scope.channel, parser, options)

		if not args:
			return scope

		numOptions = 0
		if args.channel:
			numOptions = numOptions+1
		if args.role:
			numOptions = numOptions+1
		if args.user:
			numOptions = numOptions+1

		if numOptions != 1:
			await self.ctx.send_message(scope.channel, "You must use one and only one of this options: --role, --channel, --user.")
			return scope

		with self.ctx.dbcon:
			c = self.ctx.dbcon.cursor()
			c.execute("SELECT id FROM "+self.ctx.dbprefix+"mod_levels WHERE discord_sid = ? AND name = ?", [int(scope.server.id), str(args.name)])
			r = c.fetchone()
			if r:
				await self.ctx.send_message(scope.channel, "The moderator level `"+args.name+"` already exists.")
				return scope

		if args.channel:
			chan = self.ctx.find_channel(args.channel, scope.server)
			if not chan:
				await self.ctx.send_message(scope.channel, "Channel not found.")
				return scope

			with self.ctx.dbcon:
				if not self.ctx.dbcon.execute("INSERT INTO "+self.ctx.dbprefix+"mod_levels (name, discord_sid, type, value, priority, ban_timelimit, ban_prioritylimit) VALUES (?, ?, ?, ?, ?, ?, ?)", [str(args.name), int(scope.server.id), ModLevelType.Channel, int(chan.id), int(args.priority), 0, -1]):
					await self.ctx.send_message(scope.channel, "The moderator level can't be created.")

		elif args.role:
			role = self.ctx.find_role(args.role, scope.server)
			if not role:
				await self.ctx.send_message(scope.channel, "Role not found.")
				return scope

			with self.ctx.dbcon:
				if not self.ctx.dbcon.execute("INSERT INTO "+self.ctx.dbprefix+"mod_levels (name, discord_sid, type, value, priority, ban_timelimit, ban_prioritylimit) VALUES (?, ?, ?, ?, ?, ?, ?)", [str(args.name), int(scope.server.id), ModLevelType.Role, int(role.id), int(args.priority), 0, -1]):
					await self.ctx.send_message(scope.channel, "The moderator level can't be created.")

		elif args.user:
			user = self.ctx.find_member(args.user, scope.server)
			if not user:
				await self.ctx.send_message(scope.channel, "User not found.")
				return scope

			with self.ctx.dbcon:
				if not self.ctx.dbcon.execute("INSERT INTO "+self.ctx.dbprefix+"mod_levels (name, discord_sid, type, value, priority, ban_timelimit, ban_prioritylimit) VALUES (?, ?, ?, ?, ?, ?, ?)", [str(args.name), int(scope.server.id), ModLevelType.User, int(user.id), int(args.priority), 0, -1]):
					await self.ctx.send_message(scope.channel, "The moderator level can't be created.")

		return scope

	async def execute_delete_mod_level(self, command, options, scope):
		if scope.permission < UserPermission.Admin:
			await self.ctx.send_message(scope.channel, "Only admins can use this command.")
			return scope

		parser = argparse.ArgumentParser(description='Delete a moderator level.', prog=command)
		parser.add_argument('name', help='Name of the moderator level.')

		args = await self.parse_options(scope.channel, parser, options)

		if not args:
			return scope

		with self.ctx.dbcon:
			c = self.ctx.dbcon.cursor()
			c.execute("SELECT id FROM "+self.ctx.dbprefix+"mod_levels WHERE discord_sid = ? AND name = ?", [int(scope.server.id), str(args.name)])
			r = c.fetchone()
			if r:
				with self.ctx.dbcon:
					if not self.ctx.dbcon.execute("DELETE FROM "+self.ctx.dbprefix+"mod_levels WHERE id = ?", [r[0]]):
						await self.ctx.send_message(scope.channel, "The moderator level can't be deleted.")

			else:
				await self.ctx.send_message(scope.channel, "The moderator level `"+args.name+"` doesn't exist.")

		return scope

	async def execute_mod_levels(self, command, options, scope):
		text = "**__List of moderator levels__**\n"
		with self.ctx.dbcon:
			c = self.ctx.dbcon.cursor()
			for row in c.execute("SELECT name, priority, ban_timelimit, ban_prioritylimit, purge FROM "+self.ctx.dbprefix+"mod_levels WHERE discord_sid = ? ORDER BY priority DESC", [int(scope.server.id)]):
				text = text+"\n:label: **"+row[0]+"**"
				text = text+"\n   - Priority: "+str(row[1])
				if not row[2] or row[2] < 0:
					tlimit = 0
				else:
					tlimit = row[2]
				text = text+"\n   - Duration bewteen two bans: "+str(tlimit)+"h"
				if not row[3] or row[3] < 0:
					plimit = row[1]-1
				else:
					plimit = min(row[3], row[1])
				text = text+"\n   - Maximum priority that can be banned: "+str(plimit)
				if not row[4] or row[4] <= 0:
					purge = "Can't use purge command"
				else:
					purge = "Can use purge command"
				text = text+"\n   - "+purge

		await self.ctx.send_message(scope.channel, text)

		return scope

	async def execute_get_mod_level(self, command, options, scope):
		parser = argparse.ArgumentParser(description='Give the highest moderator level of a member.', prog=command)
		parser.add_argument('member', help='A member of the server.')

		args = await self.parse_options(scope.channel, parser, options)

		if not args:
			return scope

		member = self.ctx.find_member(self.ctx.format_text(args.member, scope), scope.server)
		if not member:
			await self.ctx.send_message(scope.channel, "Member not found.")
			return scope

		userLevel = self.get_mod_level(member)

		await self.ctx.send_message(scope.channel, member.name+"#"+member.discriminator+" moderator level is: "+userLevel["name"]+".")

		return scope

	async def execute_ban(self, command, options, scope):

		parser = argparse.ArgumentParser(description='Ban a member.', prog=command)
		parser.add_argument('member', help='Name of the member to ban.')

		args = await self.parse_options(scope.channel, parser, options)

		if not args:
			return scope

		u = self.ctx.find_member(self.ctx.format_text(args.member, scope), scope.server)
		if not u:
			await self.ctx.send_message(scope.channel, "Member not found. Member name must be of the form `@User#1234` or `User#1234`.")
			return scope

		if scope.user.id == u.id:
			await self.ctx.send_message(scope.channel, "You can't ban yourself.")
			return scope

		userLevel = self.get_mod_level(scope.user)
		targetLevel = self.get_mod_level(u)

		if targetLevel["priority"] > userLevel["ban_prioritylimit"]:
			await self.ctx.send_message(scope.channel, "You can't ban "+u.display_name+" with your level.")
			return scope

		try:
			with self.ctx.dbcon:
				c = self.ctx.dbcon.cursor()
				c.execute("SELECT id, last_time as 'last_time_ [timestamp]', datetime('now') as 'currtime [timestamp]' FROM "+self.ctx.dbprefix+"ban_time WHERE discord_sid = ? AND discord_uid = ?", [int(scope.server.id), int(scope.user.id)])
				r = c.fetchone()
				if r:
					limit = r[2] - datetime.timedelta(hours=userLevel["ban_timelimit"])
					if r[1] <= limit:
						await self.ctx.client.ban(u)

						self.ctx.dbcon.execute("UPDATE "+self.ctx.dbprefix+"ban_time SET last_time = datetime('now') WHERE id = ?", [r[0]])
					else:
						await self.ctx.send_message(scope.channel, "You already banned someone. Please wait until "+str(limit)+" to ban again.")
						return scope
				else:
					await self.ctx.client.ban(u)

					self.ctx.dbcon.execute("INSERT INTO "+self.ctx.dbprefix+"ban_time (discord_sid, discord_uid, last_time) VALUES (?, ?, datetime('now'))", [int(scope.server.id), int(scope.user.id)])
		except:
			await self.ctx.send_message(scope.channel, "You can't ban "+u.display_name+" (please check that PraxisBot role is high enough).")
			return scope

		scope.deletecmd = True
		return scope

	async def execute_set_mod_options(self, command, options, scope):

		parser = argparse.ArgumentParser(description='Configure bans for a moderation level.', prog=command)
		parser.add_argument('name', help='Name of moderation level.')
		parser.add_argument('--bantime', help='Minimum duration between two bans in hours.')
		parser.add_argument('--banpriority', help='Maximum level priority than can be banned.')
		parser.add_argument('--purge', help='Enable or disable purge command.')

		args = await self.parse_options(scope.channel, parser, options)

		if not args:
			return scope

		with self.ctx.dbcon:
			c = self.ctx.dbcon.cursor()
			c.execute("SELECT id FROM "+self.ctx.dbprefix+"mod_levels WHERE discord_sid = ? AND name = ?", [int(scope.server.id), str(args.name)])
			r = c.fetchone()
			if r:
				if args.bantime:
					if self.ctx.dbcon.execute("UPDATE "+self.ctx.dbprefix+"mod_levels SET ban_timelimit = ? WHERE id = ?", [int(args.bantime), int(r[0])]):
						await self.ctx.send_message(scope.channel, "Time limitation for moderator level `"+args.name+"` updated to: "+args.bantime+".")
					else:
						await self.ctx.send_message(scope.channel, "Can't update time limitation for moderator level `"+args.name+"`.")
				if args.banpriority:
					if self.ctx.dbcon.execute("UPDATE "+self.ctx.dbprefix+"mod_levels SET ban_prioritylimit = ? WHERE id = ?", [int(args.banpriority), int(r[0])]):
						await self.ctx.send_message(scope.channel, "Priority limitation for moderator level `"+args.name+"` updated to: "+args.banpriority+".")
					else:
						await self.ctx.send_message(scope.channel, "Can't update priority limitation for moderator level `"+args.name+"`.")
				if args.purge:
					if args.purge != 0:
						p = 1
					else:
						p = 0
					if self.ctx.dbcon.execute("UPDATE "+self.ctx.dbprefix+"mod_levels SET purge = ? WHERE id = ?", [int(p), int(r[0])]):
						await self.ctx.send_message(scope.channel, "Purge for moderator level `"+args.name+"` updated to: "+str(p)+".")
					else:
						await self.ctx.send_message(scope.channel, "Can't update purge for moderator level `"+args.name+"`.")

			else:
				await self.ctx.send_message(scope.channel, "The moderator level `"+args.name+"` doesn't exist.")

		return scope

	async def execute_purge(self, command, options, scope):
		if scope.permission < UserPermission.Script:
			userLevel = self.get_mod_level(scope.user)
			if userLevel["purge"] == 0:
				await self.ctx.send_message(scope.channel, "You can't purge messages with your level.")
				return scope

		parser = argparse.ArgumentParser(description='Purge last messages in a channel.', prog=command)
		parser.add_argument('num', help='Number of messages to purge.')
		parser.add_argument('--all', action='store_true' , help='Remove all messages, including pinned messages.')

		args = await self.parse_options(scope.channel, parser, options)

		if not args:
			return scope

		n = int(args.num)
		if n < 1:
			await self.ctx.send_message(scope.channel, "Invalid number of messages.")
			return scope

		def check_function(m):
			if not args.all:
				return m.pinned == False
			else:
				return True

		await self.ctx.client.purge_from(scope.channel, limit=n, check=check_function)

		return scope

	async def dump(self, server):
		text = []

		with self.ctx.dbcon:
			c = self.ctx.dbcon.cursor()
			for row in c.execute("SELECT name, priority, type, value, ban_timelimit, ban_prioritylimit, purge FROM "+self.ctx.dbprefix+"mod_levels WHERE discord_sid = ? ORDER BY priority DESC", [int(server.id)]):
				option = ""
				if row[2] == ModLevelType.User:
					option = " --user <@"+row[3]+">"
				elif row[2] == ModLevelType.Role:
					r = self.ctx.find_role(row[3], server)
					if r:
						option = " --role \""+r.name+"\""
					else:
						option = " --role <@&"+row[3]+">"
				elif row[2] == ModLevelType.Channel:
					c = self.ctx.find_channel(row[3], server)
					if c:
						option = " --channel \""+c.name+"\""
					else:
						option = " --channel <#"+row[3]+">"
				text.append("create_mod_level \""+row[0]+"\" "+str(row[1])+option)

				if row[6] and row[6] != 0:
					purge = 1
				else:
					purge = 0
				text.append("set_mod_options \""+row[0]+"\" --banpriority "+str(row[4])+" --bantime "+str(row[5])+" --purge "+str(purge))

		return text

	async def list_commands(self, server):
		return ["list_channels", "create_mod_level", "delete_mod_level", "mod_levels", "get_mod_level"]

	async def execute_command(self, shell, command, options, scope):
		if command == "ban":
			scope.iter = scope.iter+1
			return await self.execute_ban(command, options, scope)
		elif command == "list_channels":
			scope.iter = scope.iter+1
			return await self.execute_list_channels(command, options, scope)
		elif command == "create_mod_level":
			scope.iter = scope.iter+1
			return await self.execute_create_mod_level(command, options, scope)
		elif command == "delete_mod_level":
			scope.iter = scope.iter+1
			return await self.execute_delete_mod_level(command, options, scope)
		elif command == "mod_levels":
			scope.iter = scope.iter+1
			return await self.execute_mod_levels(command, options, scope)
		elif command == "get_mod_level":
			scope.iter = scope.iter+1
			return await self.execute_get_mod_level(command, options, scope)
		elif command == "set_mod_options":
			scope.iter = scope.iter+1
			return await self.execute_set_mod_options(command, options, scope)
		elif command == "purge":
			scope.iter = scope.iter+1
			return await self.execute_purge(command, options, scope)

		return scope