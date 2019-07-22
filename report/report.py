import asyncio
import enum
import json
import re
from datetime import datetime, timedelta
from types import SimpleNamespace

from discord.ext import commands

import aiohttp
from pymongo import ReturnDocument

from core import checks
from core.models import PermissionLevel


class IssueType(enum.Enum):
    BUG = 'bug'
    FEATURE = 'feature'
    CONFIG = 'config'

    @classmethod
    def replace(cls, item):
        item = item.lower().replace('-', ' ').strip()
        if item == 'bug report':
            return cls.BUG
        if item in {'feature request', 'new feature'}:
            return cls.FEATURE
        if item in {'config suggestion', 'new config'}:
            return cls.CONFIG
        return IssueType(item)


class Report(commands.Cog):
    """
    Create GitHub issues.
    """

    def __init__(self, bot):
        self.bot: commands.Bot = bot
        self.db = bot.plugin_db.get_partition(self)
        self.access_token = ''
        self._pending_approval = None

    @property
    def headers(self):
        return {"Authorization": "token " + self.access_token,
                "Accept": "application/json"}

    async def pending_approval(self, *, setting=None, popping=None):
        if setting is not None:
            config = await self.db.find_one_and_update(
                {'_id': 'report-config'},
                {'$push': {'pending_approval': setting}},
                upsert=True,
                return_document=ReturnDocument.AFTER
            )
            self._pending_approval = config['pending_approval']

        if popping is not None:
            if isinstance(popping, (list, tuple)):
                popping = [str(i) for i in popping]
            else:
                popping = str(popping)
            config = await self.db.find_one_and_update(
                {'_id': 'report-config'},
                {'$pull': {'pending_approval': popping}},
                upsert=True,
                return_document=ReturnDocument.AFTER
            )
            self._pending_approval = config['pending_approval']

        if self._pending_approval is None:
            config = await self.db.find_one({'_id': 'report-config'})
            self._pending_approval = (config or {}).get('pending_approval', [])

        now = datetime.utcnow()
        pending = []
        dismissed = 0

        for entry in self._pending_approval:
            if datetime.fromisoformat(entry['end_time']) >= now:
                pending.append(entry)
            else:
                dismissed += 1
        if dismissed:
            await self.db.update_one(
                {'_id': 'report-config'}, {'$set': {'pending_approval': pending}}
            )

        return self._pending_approval

    @commands.command()
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def token(self, ctx, *, access_token: str):
        """
        Set the GitHub access token.
        """
        await self.db.find_one_and_update(
            {'_id': 'report-config'},
            {'$set': {'access_token': access_token}},
            upsert=True
        )
        self.access_token = access_token
        await ctx.send('Successfully set access token.')

    @commands.command()
    @checks.has_permissions(PermissionLevel.REGULAR)
    async def report(self, ctx, *, issue_type: str.lower = 'bug'):
        """
        Interactively report a bug or feature request in GitHub.

        Issue type can be "bug", "feature request" ("request"), "new config" ("config").
        """
        try:
            issue_type = IssueType.replace(issue_type)
        except ValueError:
            return await ctx.send(f'Unexpected issue type.')

        if not self.access_token:
            config = await self.db.find_one({'_id': 'report-config'})
            access_token = (config or {}).get('access_token', '')
            if not access_token:
                return await ctx.send(f'No access token found, set one with `{self.bot.prefix}token accesstoken`.')
            self.access_token = access_token

        def message_wait(m):
            if m.content.lower() == ':cancel':
                raise ValueError
            return m.author == ctx.author

        title = ''
        labels = []
        if issue_type == IssueType.FEATURE:
            title = '[FEATURE REQUEST] '
            labels.append('feature-request')
        elif issue_type == IssueType.BUG:
            title = '[BUG] '
            labels.append('bug')
        elif issue_type == IssueType.CONFIG:
            title = '[CONFIG SUGGESTION] '
            labels.append('config-suggestion')

        await ctx.send('We will now start the composing the issue, type `:cancel` any time to stop.\n\n'
                       'Please type the **title** of your report (within 15 minutes):')

        try:
            msg = await self.bot.wait_for('message', check=message_wait, timeout=900.0)
        except ValueError:
            return await ctx.send('Cancelled.')
        except asyncio.TimeoutError:
            return await ctx.send('Timed out, you will need to restart.')
        title += msg.content.strip('` \n\t\r')

        await ctx.send('Please type the **message** of your report (within 15 minutes):')

        try:
            msg = await self.bot.wait_for('message', check=message_wait, timeout=900.0)
        except ValueError:
            return await ctx.send('Cancelled.')
        except asyncio.TimeoutError:
            return await ctx.send('Timed out, try again.')

        desc = msg.content.strip('` \n\t\r')
        desc += f'\n\nIssue created by @{ctx.author.name}#{ctx.author.discriminator}, Discord user ID: {ctx.author.id}.'

        await ctx.send('Specify the **GitHub Repo** for the issue to be posted in, type "modmail" for `kyb3r/modmail` '
                       '(format: `owner/repo` or `https://github.com/owner/repo/`):')

        try:
            msg = await self.bot.wait_for('message', check=message_wait, timeout=900.0)
        except ValueError:
            return await ctx.send('Cancelled.')
        except asyncio.TimeoutError:
            return await ctx.send(f'Timed out, you will need to restart.')

        url = 'https://api.github.com/repos/'
        if msg.content.strip('` \n\t\r').lower() == 'modmail':
            url += 'kyb3r/modmail/'
        else:
            match = re.match(r'^<?(?:(?:https?://)?github\.com/|/)?([a-zA-Z0-9\-]+/[a-zA-Z0-9\-]+)/?>?$',
                             msg.content.strip('` \n\t\r'))
            if match is None:
                return await ctx.send('Invalid GitHub repo, specify in the format `owner/repo`.')
            url += match.group(1) + '/'
        url += 'issues'

        data = {
            'title': title,
            'body': desc,
            'labels': labels,
        }

        waiting_msg = await ctx.send('Issue noted, requires a bot Administrator\'s approval (within 12 hours).')
        await waiting_msg.pin()
        await waiting_msg.add_reaction('\N{THUMBS UP SIGN}')
        await waiting_msg.add_reaction('\N{THUMBS DOWN SIGN}')
        end_time = datetime.utcnow() + timedelta(hours=12)

        await self.pending_approval(setting={
            'msg_id': waiting_msg.id, 'end_time': end_time.isoformat(), 'data': data, 'url': url
        })

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user == self.bot.user:
            return
        pending = await self.pending_approval()
        approved = None
        entry = None
        for entry in pending:
            if entry['msg_id'] != reaction.message.id:
                continue
            if reaction.emoji in {'\N{THUMBS UP SIGN}', '\N{THUMBS DOWN SIGN}'}:
                temp_ctx = SimpleNamespace(bot=self.bot, author=user, channel=reaction.message.channel)
                if await checks.check_permissions(temp_ctx, None, PermissionLevel.ADMINISTRATOR):
                    if str(reaction.emoji) == '\N{THUMBS UP SIGN}':
                        approved = True
                    elif str(reaction.emoji) == '\N{THUMBS DOWN SIGN}':
                        approved = False
            await self.pending_approval(popping=entry)
            await reaction.remove(user)

        if approved is None:
            return
        await reaction.message.unpin()
        await reaction.message.clear_reactions()
        channel = reaction.message.channel
        if not approved:
            return await channel.send(f'Admin {user.name} has denied your issue.')
        await channel.send(f'Admin {user.name} has approved your issue.')

        async with self.bot.session.post(entry['url'], headers=self.headers, json=entry['data']) as resp:
            try:
                content = await resp.json()
            except (json.JSONDecodeError, aiohttp.ContentTypeError):
                content = await resp.text()
                return await channel.send(f'Failed to create issue: ```\n{content}\n```')
            if resp.status == 410:
                return await channel.send(f'This GitHub repo is not accepting new issues: ```\n{content}\n```')
            if resp.status != 201:
                return await channel.send(f'Failed to create issue, status {resp.status}: ```\n{content}\n```')
            await channel.send(f'Successfully created issue: {content["html_url"]}.')

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        pending = await self.pending_approval()
        for entry in pending:
            if entry['msg_id'] == reaction.message.id and user == self.bot.user:
                return await reaction.message.add_reaction(reaction)


def setup(bot):
    bot.add_cog(Report(bot))
