import asyncio
import enum
import json
import re
import typing
from datetime import datetime, timedelta
from types import SimpleNamespace

from discord import TextChannel, NotFound
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
        self._allowed = None
        self.in_progress = []

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
            config = await self.db.find_one_and_update(
                {'_id': 'report-config'},
                {'$pull': {'pending_approval': {'msg_id': popping['msg_id']}}},
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

    async def allowed(self, channel_id):
        if self._allowed is None:
            config = await self.db.find_one({'_id': 'report-config'})
            self._allowed = (config or {}).get('allowed_channels', [])
        return channel_id in self._allowed or not self._allowed

    @commands.command()
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def allow(self, ctx, *, channel: typing.Union[TextChannel, int] = None):
        """
        Add or remove a channel's ability to create issues.

        If no channels are specified, all channels are all allowed.
        """
        if channel is None:
            config = await self.db.find_one({'_id': 'report-config'})
            self._allowed = (config or {}).get('allowed_channels', [])
            if not self._allowed:
                return await ctx.send('All channels are allowed to create issues.')

            channel_names = []
            for id_ in self._allowed:
                ch = ctx.guild.get_channel(id_)
                if ch is not None:
                    channel_names.append(ch.mention)
                else:
                    channel_names.append(str(id_))
            return await ctx.send('These are the channel(s) that are allowed to '
                                  f'create issues: {", ".join(channel_names)}.')

        id_ = getattr(channel, 'id', channel)
        if self._allowed is None:
            config = await self.db.find_one({'_id': 'report-config'})
            self._allowed = (config or {}).get('allowed_channels', [])

        if id_ in self._allowed:
            config = await self.db.find_one_and_update(
                {'_id': 'report-config'},
                {'$pull': {'allowed_channels': id_}},
                upsert=True,
                return_document=ReturnDocument.AFTER
            )
            await ctx.send(f'Successfully disallowed {getattr(channel, "mention", channel)}; '
                           f'however, if no channels are set with `{self.bot.prefix}allow`, '
                           'all channels will be allowed.')
        else:
            config = await self.db.find_one_and_update(
                {'_id': 'report-config'},
                {'$push': {'allowed_channels': id_}},
                upsert=True,
                return_document=ReturnDocument.AFTER
            )
            await ctx.send(f'Successfully allowed {getattr(channel, "mention", channel)}.')

        self._allowed = config['allowed_channels']

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

        if not await self.allowed(ctx.channel.id):
            return await ctx.send('You\'re not allowed to create reports in this channel.')

        if (ctx.author.id, ctx.channel.id) in self.in_progress:
            return
        self.in_progress.append((ctx.author.id, ctx.channel.id))

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
        desc += f'\n\n\nIssue created by `@{ctx.author.name}#{ctx.author.discriminator}`, Discord ID: {ctx.author.id}.'

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
            'msg_id': waiting_msg.id,
            'user_id': ctx.author.id,
            'end_time': end_time.isoformat(),
            'data': data,
            'url': url
        })

        self.in_progress.remove((ctx.author.id, ctx.channel.id))

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        pending = await self.pending_approval()
        approved = None
        entry = None
        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except NotFound:
            return
        user = channel.guild.get_member(payload.user_id)
        if user is None:
            return

        for entry in pending:
            if entry['msg_id'] != payload.message_id:
                continue
            if str(payload.emoji) in {'\N{THUMBS UP SIGN}', '\N{THUMBS DOWN SIGN}'}:
                temp_ctx = SimpleNamespace(bot=self.bot, author=user, channel=channel)
                if await checks.check_permissions(temp_ctx, None, PermissionLevel.ADMINISTRATOR):
                    if str(payload.emoji) == '\N{THUMBS UP SIGN}':
                        approved = True
                    elif str(payload.emoji) == '\N{THUMBS DOWN SIGN}':
                        approved = False
            await self.pending_approval(popping=entry)
            await message.remove_reaction(payload.emoji, user)

        if approved is None:
            return
        await message.unpin()
        await message.clear_reactions()

        author = channel.guild.get_member(entry['user_id'])
        user_mention = f'<@!{entry["user_id"]}>' if author is None else f'{author.mention}'

        if not approved:
            return await channel.send(f'{user_mention} {user.name} has denied your issue.')
        await channel.send(f'{user_mention} {user.name} has approved your issue.')

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
    async def on_raw_reaction_remove(self, payload):
        pending = await self.pending_approval()
        for entry in pending:
            if entry['msg_id'] == payload.message_id and payload.user_id == self.bot.user.id:
                channel = self.bot.get_channel(payload.channel_id)
                if channel is None:
                    return
                try:
                    message = await channel.fetch_message(payload.message_id)
                except NotFound:
                    return
                return await message.add_reaction(payload.emoji)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        pending = await self.pending_approval()
        for entry in pending:
            if payload.message_id == entry['msg_id']:
                return await self.pending_approval(popping=entry)


def setup(bot):
    bot.add_cog(Report(bot))
