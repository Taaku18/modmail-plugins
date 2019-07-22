import asyncio
import enum
import json
import re
from types import SimpleNamespace

from discord.ext import commands

import aiohttp

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

    @property
    def headers(self):
        return {"Authorization": "token " + self.access_token,
                "Accept": "application/json"}

    @commands.command()
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    def token(self, *, access_token: str):
        """
        Set the GitHub access token.
        """
        await self.db.find_one_and_update(
            {'_id': 'report-config'},
            {'$set': {'access_token': access_token}},
            upsert=True
        )
        self.access_token = access_token

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
            return m.author == ctx.author.id

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

        await ctx.send('We will now start the composing the issue, type `:cancel` any time to stop.\n'
                       'Please type the title of your report (within 15 minutes):')

        try:
            msg = await self.bot.wait_for('message', check=message_wait, timeout=900.0)
        except ValueError:
            return await ctx.send('Cancelled.')
        except asyncio.TimeoutError:
            return await ctx.send('Timed out, you will need to restart.')
        title += msg.content

        await ctx.send('Please type the message of your report (within 15 minutes):')

        try:
            msg = await self.bot.wait_for('message', check=message_wait, timeout=900.0)
        except ValueError:
            return await ctx.send('Cancelled.')
        except asyncio.TimeoutError:
            return await ctx.send('Timed out, try again.')

        desc = msg.content
        desc += f'\n\nIssue created by @{ctx.author.name}#{ctx.author.discriminator}, Discord user ID: {ctx.author.id}.'

        await ctx.send('Specify the GitHub repo for the issue to be posted in, type "modmail" for "kyb3r/modmail" '
                       '(format: "owner/repo"):')

        try:
            msg = await self.bot.wait_for('message', check=message_wait, timeout=900.0)
        except ValueError:
            return await ctx.send('Cancelled.')
        except asyncio.TimeoutError:
            return await ctx.send(f'Timed out, you will need to restart.')

        url = 'https://api.github.com/repos/'
        if msg.lower() == 'modmail':
            url += 'kyb3r/modmail/'
        else:
            match = re.match(r'^/?([a-zA-Z0-9\-]+/[a-zA-Z0-9\-]+)/?$', msg)
            if match is None:
                return await ctx.send('Invalid GitHub repo, specify in the format "owner/repo".')
            url += match.group(1) + '/'
        url += 'issues'

        data = {
            'title': title,
            'body': desc,
            'labels': labels,
        }

        waiting_msg = await ctx.send('Issue noted, requires a bot Administrator\'s approval (within an hour).')
        await waiting_msg.pin()
        await waiting_msg.add_reaction('👍')
        await waiting_msg.add_reaction('👎')
        admin = None

        def reaction_wait(reaction, user):
            nonlocal admin
            await reaction.remove(user)
            if reaction.message == waiting_msg:
                if str(reaction.emoji) in {'👍', '👎'}:
                    temp_ctx = SimpleNamespace(bot=ctx.bot, author=user, channel=ctx.channel)
                    if checks.check_permissions(temp_ctx, None, PermissionLevel.ADMINISTRATOR):
                        admin = user
                        if str(reaction.emoji) == '👍':
                            return True
                        elif str(reaction.emoji) == '👎':
                            raise ValueError
            return False

        try:
            await self.bot.wait_for('reaction_add', check=reaction_wait, timeout=3600.0)
        except ValueError:
            return await ctx.send(f'Admin {admin.name if admin is not None else "unknown"} has denied your issue.')
        except asyncio.TimeoutError:
            return await ctx.send(f'Timed out, you will need to restart.')
        finally:
            await waiting_msg.unpin()
            await waiting_msg.clear_reactions()

        await ctx.send(f'Admin {admin.name if admin is not None else "unknown"} has approved your issue.')

        async with self.bot.session.post(url, headers=self.headers, json=data) as resp:
            try:
                content = await resp.json()
            except (json.JSONDecodeError, aiohttp.ContentTypeError):
                content = await resp.text()
                return await ctx.send(f'Failed to create issue: ```\n{content}\n```')
            if resp.status == 410:
                return await ctx.send(f'This GitHub repo is not accepting new issues: ```\n{content}\n```')
            if resp.status != 201:
                return await ctx.send(f'Failed to create issue, status {resp.status}: ```\n{content}\n```')
            await ctx.send(f'Successfully created issue: {content["html_url"]}.')


def setup(bot):
    bot.add_cog(Report(bot))
