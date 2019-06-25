import datetime
from asyncio import sleep
from json import JSONDecodeError

from aiohttp import ClientResponseError

from discord import Embed, TextChannel, NotFound
from discord.ext import commands
from discord.enums import AuditLogAction

from core import checks
from core.models import PermissionLevel


class Logger(commands.Cog):
    """
    Logs stuff.
    """

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.plugin_db.get_partition(self)
        self.bg_task = self.bot.loop.create_task(self.audit_logs_logger())
        self.last_audit_log = datetime.datetime.utcnow()

    @commands.command()
    @checks.has_permissions(PermissionLevel.OWNER)
    async def lchannel(self, ctx, channel: TextChannel):
        """
        Sets the log channel.
        """
        await self.set_log_channel(channel)
        await ctx.send(f'Successfully set logger channel to: {channel.mention}.')

    async def set_log_channel(self, channel):
        await self.db.find_one_and_update(
            {'_id': 'logger-config'},
            {'$set': {'channel_id': channel.id}},
            upsert=True
        )

    async def get_log_channel(self):
        config = await self.db.find_one({'_id': 'logger-config'})
        if config is None:
            raise ValueError(f'No logger channel specified, set one with `{self.bot.prefix}lchannel #channel`.')
        channel_id = config['channel_id']
        channel = self.bot.guild.get_channel(channel_id)
        if channel is None:
            self.db.find_one_and_delete({'_id': 'logger-config'})
            raise ValueError(f'Logger channel with ID `{channel_id}` not found.')
        return channel

    async def audit_logs_logger(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            async for audit in self.bot.guild.audit_logs(after=self.last_audit_log):
                self.last_audit_log = audit.created_at
                if audit.action == AuditLogAction.channel_create:
                    ...
                elif audit.action == AuditLogAction.channel_update:
                    ...
                elif audit.action == AuditLogAction.channel_delete:
                    ...
                elif audit.action == AuditLogAction.kick:
                    ...
                elif audit.action == AuditLogAction.member_prune:
                    ...
                elif audit.action == AuditLogAction.ban:
                    ...
                elif audit.action == AuditLogAction.unban:
                    ...
                elif audit.action == AuditLogAction.message_delete:
                    ...
            await sleep(5)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if payload.guild_id != self.bot.guild_id:
            return
        channel = await self.get_log_channel()
        message = payload.cached_message

        if message:
            return await channel.send(embed=self.make_embed(
                f'A message sent by {message.author.name}#{message.author.discriminator} '
                f'({message.author.id}) has been deleted from #{message.channel.name}.',
                message.content,
                fields=[('Message ID:', payload.message_id, True),
                        ('Channel ID:', payload.channel_id, True),
                        ('Message sent on:', message.created_at.strftime('%b %-d at %-I:%M %p'), True)
                        ]
            ))

        payload_channel = self.bot.guild.get_channel(payload.channel_id)
        if payload_channel is not None:
            channel_text = payload_channel.name
        else:
            channel_text = 'deleted-channel'
        return await channel.send(embed=self.make_embed(
            f'A message was deleted in #{channel_text}.',
            'The message content cannot be found, a further message may '
            'follow if this message was not deleted by the author.',
            fields=[('Message ID:', payload.message_id, True),
                    ('Channel ID:', payload.channel_id, True)
                    ]
        ))

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        if payload.guild_id != self.bot.guild_id:
            return
        channel = await self.get_log_channel()

        messages = sorted(payload.cached_messages, key=lambda msg: msg.created_at)
        message_ids = payload.message_ids
        upload_text = 'Here are the messages that were deleted:\n'

        if not messages:
            upload_text += 'There are no known messages.\n'
            upload_text += 'Unknown message IDs: ' + ', '.join(map(str, message_ids)) + '.'
        else:
            known_message_ids = set()
            for message in messages:
                known_message_ids.add(message.id)
                time = message.created_at.strftime('%b %-d at %-I:%M %p')
                upload_text += f'{time} {message.author.name}#{message.author.discriminator} ({message.author.id}). ' \
                    f'Message ID: {message.id}. {message.content}\n'
            unknown_message_ids = message_ids ^ known_message_ids
            if unknown_message_ids:
                upload_text += 'Unknown message IDs: ' + ', '.join(map(str, unknown_message_ids)) + '.'

        payload_channel = self.bot.guild.get_channel(payload.channel_id)
        if payload_channel is not None:
            channel_text = payload_channel.name
        else:
            channel_text = 'deleted-channel'

        try:
            async with self.bot.session.post('https://hasteb.in/documents', data=upload_text) as resp:
                key = (await resp.json())["key"]
                return await channel.send(embed=self.make_embed(
                    f'Multiple messages deleted from #{channel_text}.',
                    f'Deleted messages: https://hasteb.in/{key}.',
                    fields=[('Channel ID:', payload.channel_id, True)]
                ))
        except (JSONDecodeError, ClientResponseError, IndexError):
            return await channel.send(embed=self.make_embed(
                f'Multiple messages deleted from {channel_text}.',
                'Failed to upload to Hastebin. Deleted message IDs: ' + ', '.join(map(str, message_ids)) + '.',
                fields=[('Channel ID', payload.channel_id, True)]
            ))

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        channel_id = int(payload.data['channel_id'])
        message_id = int(payload.data['id'])

        new_content = payload.data.get('content')
        if new_content is None:
            # Currently does not support Embed edits
            return

        payload_channel = self.bot.guild.get_channel(channel_id)
        if payload_channel is not None:
            if payload_channel.guild.id != self.bot.guild_id:
                return
            channel_text = payload_channel.name
        else:
            channel_text = 'deleted-channel'

        channel = await self.get_log_channel()
        old_message = payload.cached_message

        if old_message:
            return await channel.send(embed=self.make_embed(
                f'A message was updated in #{channel_text}.',
                fields=[('Before', old_message.content, False),
                        ('After', new_content, False),
                        ('Message ID:', f'[{message_id}]({old_message.jump_url})', True),
                        ('Channel ID:', channel_id, True),
                        ('Message sent on:', old_message.created_at.strftime('%b %-d, %Y at %-I:%M %p'), True)
                        ]
            ))

        if payload_channel is not None:
            try:
                message = await payload_channel.fetch_message(message_id)
                return await channel.send(embed=self.make_embed(
                    f'A message was updated in #{channel_text}.',
                    'The former message content cannot be found.',
                    fields=[('Now', new_content, False),
                            ('Message ID:', f'[{message_id}]({message.jump_url})', True),
                            ('Channel ID:', channel_id, True),
                            ('Message sent on:', message.created_at.strftime('%b %-d, %Y at %-I:%M %p'), True),
                            ]
                ))
            except NotFound:
                pass
        return await channel.send(embed=self.make_embed(
            f'A message was updated in {channel_text}.',
            'The former message content cannot be found.',
            fields=[('Now', new_content, False),
                    ('Message ID:', message_id, True),
                    ('Channel ID:', channel_id, True)
                    ]
        ))

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild.id != self.bot.guild_id:
            return
        channel = await self.get_log_channel()
        await channel.send(embed=self.make_embed(
            'Member Joined',
            f'{member.name}#{member.discriminator} ({member.id}) has joined.'
        ))

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.guild.id != self.bot.guild_id:
            return
        channel = await self.get_log_channel()
        await channel.send(embed=self.make_embed(
            'Member Joined',
            f'{member.name}#{member.discriminator} ({member.id}) has left.'
        ))

    def make_embed(self, title, description='', *, time=None, fields=None):
        embed = Embed(title=title, description=description, color=self.bot.main_color)
        time = time if time is not None else datetime.datetime.utcnow()
        embed.set_footer(text=time.strftime('%b %-d at %-I:%M %p UTC'))
        if fields is not None:
            for n, v, i in fields:
                embed.add_field(name=n, value=v, inline=i)
        return embed


def setup(bot):
    bot.add_cog(Logger(bot))
