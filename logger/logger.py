import datetime
from asyncio import sleep, CancelledError
from logging import getLogger
from json import JSONDecodeError

from aiohttp import ClientResponseError

from discord import Embed, TextChannel, NotFound
from discord.ext import commands
from discord.enums import AuditLogAction

from core import checks
from core.models import PermissionLevel


logger = getLogger('Modmail')


class Logger(commands.Cog):
    """
    Logs stuff.
    """

    def __init__(self, bot):
        self.bot = bot
        self.db = bot.plugin_db.get_partition(self)
        self._channel = None
        self.bg_task = self.bot.loop.create_task(self.audit_logs_logger())
        self.last_audit_log = datetime.datetime.utcnow(), -1

    def cog_unload(self):
        self.bg_task.cancel()
        self._channel = None
        self.last_audit_log = datetime.datetime.utcnow(), -1

    @commands.command()
    @checks.has_permissions(PermissionLevel.ADMINISTRATOR)
    async def lchannel(self, ctx, channel: TextChannel):
        """
        Sets the log channel.
        """
        await self.set_log_channel(channel)
        await ctx.send(f'Successfully set logger channel to: {channel.mention}.')

    async def set_log_channel(self, channel):
        logger.info('Setting channel_id for logger.')
        await self.db.find_one_and_update(
            {'_id': 'logger-config'},
            {'$set': {'channel_id': channel.id}},
            upsert=True
        )
        self._channel = channel

    async def get_log_channel(self):
        if self._channel is not None:
            return self._channel
        logger.info('Retrieving channel_id for logger from config.')
        config = await self.db.find_one({'_id': 'logger-config'})
        if config is None:
            raise ValueError(f'No logger channel specified, set one with `{self.bot.prefix}lchannel #channel`.')
        channel_id = config['channel_id']
        channel = self.bot.guild.get_channel(channel_id)
        if channel is None:
            self.db.find_one_and_delete({'_id': 'logger-config'})
            raise ValueError(f'Logger channel with ID `{channel_id}` not found.')
        self._channel = channel
        return channel

    async def audit_logs_logger(self):
        await self.bot.wait_until_ready()
        logger.info('Starting audit log listener loop.')
        while not self.bot.is_closed():
            try:
                channel = await self.get_log_channel()
                audits = []
                async for audit in self.bot.guild.audit_logs(limit=30):
                    if audit.created_at < self.last_audit_log[0] or audit.id == self.last_audit_log[1]:
                        break
                    audits.append(audit)

                for audit in reversed(audits):
                    if audit.action == AuditLogAction.channel_create:
                        # TODO: display category
                        name = getattr(audit.target, 'name', getattr(audit.after, 'name', 'unknown-channel'))
                        await channel.send(embed=self.make_embed(
                            f'Channel Created',
                            f'#{name} has been created by {audit.user.mention}.',
                            time=audit.created_at,
                            fields=[('Channel ID:', audit.target.id, True)]
                        ))

                    elif audit.action == AuditLogAction.channel_update:
                        name = getattr(audit.target, 'name',
                                       getattr(audit.after, 'name',
                                               getattr(audit.before, 'name', 'unknown-channel')
                                               )
                                       )
                        await channel.send(embed=self.make_embed(
                            f'Channel Updated',
                            f'#{name} has been updated by {audit.user.mention}.',
                            time=audit.created_at,
                            fields=[
                                ('Channel ID:', audit.target.id, True),
                                ('Changes:', ', '.join(map(lambda a: a[0].replace('_', ' ').title(),
                                                           iter(audit.after))), False)
                            ]
                        ))

                    elif audit.action == AuditLogAction.channel_delete:
                        name = getattr(audit.target, 'name', getattr(audit.before, 'name', audit.target.id))
                        await channel.send(embed=self.make_embed(
                            f'Channel Deleted',
                            f'#{name} has been deleted by {audit.user.mention}.',
                            time=audit.created_at,
                            fields=[('Channel ID:', audit.target.id, True)]
                        ))

                    elif audit.action == AuditLogAction.kick:
                        await channel.send(embed=self.make_embed(
                            f'Member Kicked',
                            f'{audit.target.mention} has been kicked by {audit.user.mention}.',
                            time=audit.created_at,
                            fields=[('Reason:', audit.reason or 'No Reason', False)]
                        ))

                    elif audit.action == AuditLogAction.member_prune:
                        await channel.send(embed=self.make_embed(
                            f'Members Pruned',
                            f'{audit.extra.members_removed} members has been pruned by {audit.user.mention}.',
                            time=audit.created_at,
                            fields=[('Prune days:', str(audit.extra.delete_members_days), False)]
                        ))

                    elif audit.action == AuditLogAction.ban:
                        await channel.send(embed=self.make_embed(
                            f'Member Banned',
                            f'{audit.target.mention} has been banned by {audit.user.mention}.',
                            time=audit.created_at,
                            fields=[('Reason:', audit.reason or 'No Reason', False)]
                        ))

                    elif audit.action == AuditLogAction.unban:
                        await channel.send(embed=self.make_embed(
                            f'Member Unbanned',
                            f'{audit.target.mention} has been unbanned by {audit.user.mention}.',
                            time=audit.created_at
                        ))

                    elif audit.action == AuditLogAction.message_delete:
                        pl = '' if audit.extra.count == 1 else 's'
                        channel_text = getattr(audit.extra.channel, 'name', 'unknown-channel')
                        await channel.send(embed=self.make_embed(
                            f'Message{pl} Deleted',
                            f'{audit.user.mention} deleted {audit.extra.count} message{pl} sent by '
                            f'{audit.target.mention} from #{channel_text}.',
                            time=audit.created_at,
                            fields=[('Channel ID:', audit.target.id, True)]
                        ))

                if audits:
                    self.last_audit_log = audits[-1].created_at, audits[-1].id

                    if len(audits) == 30:
                        await channel.send(embed=self.make_embed(
                            'Warning',
                            'Due to the nature of Discord API, there may be more audits undisplayed. '
                            'Check the audits page for a complete list of audits.'
                        ))
                await sleep(5)
            except CancelledError:
                break
            except Exception:
                logger.error('An error in audit loop occurred', exc_info=True)
        logger.info('Audit log listener loop cancelled.')

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if payload.guild_id != self.bot.guild_id:
            return
        channel = await self.get_log_channel()
        message = payload.cached_message

        if message:
            time = message.created_at.strftime('%b %-d at %-I:%M %p UTC')
            md_time = message.created_at.strftime('%H%M_%d_%B_%Y_in_UTC')

            return await channel.send(embed=self.make_embed(
                f'A message sent by {message.author.name}#{message.author.discriminator} '
                f'({message.author.id}) has been deleted from #{message.channel.name}.',
                message.content or 'No Content',
                fields=[('Message ID:', payload.message_id, True),
                        ('Channel ID:', payload.channel_id, True),
                        ('Message sent on:', f'[{time}](https://time.is/{md_time}?Message_Deleted)', True)],
                footer='A further message may follow if this message was not deleted by the author.'
            ))

        payload_channel = self.bot.guild.get_channel(payload.channel_id)
        if payload_channel is not None:
            channel_text = payload_channel.name
        else:
            channel_text = 'deleted-channel'
        return await channel.send(embed=self.make_embed(
            f'A message was deleted in #{channel_text}.',
            fields=[('Message ID:', payload.message_id, True),
                    ('Channel ID:', payload.channel_id, True)],
            footer='The message content cannot be found, a further message may '
                   'follow if the message was not deleted by the original author.'
        ))

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        if payload.guild_id != self.bot.guild_id:
            return
        channel = await self.get_log_channel()

        messages = sorted(payload.cached_messages, key=lambda msg: msg.created_at)
        message_ids = payload.message_ids
        pl = '' if len(message_ids) == 1 else 's'
        pl_be = 'is' if len(message_ids) == 1 else 'are'
        pl_be_past = 'was' if len(message_ids) == 1 else 'were'
        upload_text = f'Here {pl_be} the message{pl} that {pl_be_past} deleted:\n'

        if not messages:
            upload_text += 'There are no known messages.\n'
            upload_text += f'Unknown message ID{pl}: ' + ', '.join(map(str, message_ids)) + '.'
        else:
            known_message_ids = set()
            for message in messages:
                known_message_ids.add(message.id)
                time = message.created_at.strftime('%b %-d at %-I:%M %p')
                upload_text += f'{time} {message.author.name}#{message.author.discriminator} ({message.author.id}). ' \
                    f'Message ID: {message.id}. {message.content}\n'
            unknown_message_ids = message_ids ^ known_message_ids
            if unknown_message_ids:
                pl_unknown = '' if len(unknown_message_ids) == 1 else 's'
                upload_text += f'Unknown message ID{pl_unknown}: ' + ', '.join(map(str, unknown_message_ids)) + '.'

        payload_channel = self.bot.guild.get_channel(payload.channel_id)
        if payload_channel is not None:
            channel_text = payload_channel.name
        else:
            channel_text = 'deleted-channel'

        try:
            async with self.bot.session.post('https://hasteb.in/documents', data=upload_text) as resp:
                key = (await resp.json())["key"]
                return await channel.send(embed=self.make_embed(
                    f'{len(message_ids)} message{pl} deleted from #{channel_text}.',
                    f'Deleted message{pl}: https://hasteb.in/{key}.',
                    fields=[('Channel ID:', payload.channel_id, True)]
                ))
        except (JSONDecodeError, ClientResponseError, IndexError):
            return await channel.send(embed=self.make_embed(
                f'{len(message_ids)} message{pl} deleted from {channel_text}.',
                f'Failed to upload to Hastebin. Deleted message ID{pl}: ' + ', '.join(map(str, message_ids)) + '.',
                fields=[('Channel ID', payload.channel_id, True)]
            ))

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        channel_id = int(payload.data['channel_id'])
        message_id = int(payload.data['id'])

        new_content = payload.data.get('content', '')
        old_message = payload.cached_message

        if not new_content or new_content == old_message.content:
            # Currently does not support Embed edits
            return

        payload_channel = self.bot.guild.get_channel(channel_id)
        if payload_channel is None:
            return
        if payload_channel.guild.id != self.bot.guild_id:
            return
        channel_text = payload_channel.name

        channel = await self.get_log_channel()

        if old_message:
            time = old_message.created_at.strftime('%b %-d, %Y at %-I:%M %p UTC')
            md_time = old_message.created_at.strftime('%H%M_%d_%B_%Y_in_UTC')

            return await channel.send(embed=self.make_embed(
                f'A message was updated in #{channel_text}.',
                fields=[('Before', old_message.content or 'No Content', False),
                        ('After', new_content or 'No Content', False),
                        ('Message ID:', f'[{message_id}]({old_message.jump_url})', True),
                        ('Channel ID:', channel_id, True),
                        ('Sent by:', old_message.author.mention, True),
                        ('Message sent on:', f'[{time}](https://time.is/{md_time}?Message_Edited)', True)
                        ]
            ))

        try:
            message = await payload_channel.fetch_message(message_id)
            time = message.created_at.strftime('%b %-d, %Y at %-I:%M %p UTC')
            md_time = message.created_at.strftime('%H%M_%d_%B_%Y_in_UTC')

            return await channel.send(embed=self.make_embed(
                f'A message was updated in #{channel_text}.',
                'The former message content cannot be found.',
                fields=[('Now', new_content or 'No Content', False),
                        ('Message ID:', f'[{message_id}]({message.jump_url})', True),
                        ('Channel ID:', channel_id, True),
                        ('Sent by:', message.author.mention, True),
                        ('Message sent on:', f'[{time}](https://time.is/{md_time}?Message_Edited)', True),
                        ]
            ))
        except NotFound:
            return await channel.send(embed=self.make_embed(
                f'A message was updated in {channel_text}.',
                'The former message content cannot be found.',
                fields=[('Now', new_content or 'No Content', False),
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
            f'{member.mention} has joined.'
        ))

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.guild.id != self.bot.guild_id:
            return
        channel = await self.get_log_channel()
        await channel.send(embed=self.make_embed(
            'Member Joined',
            f'{member.mention} has left.'
        ))

    def make_embed(self, title, description='', *, time=None, fields=None, footer=None):
        embed = Embed(title=title, description=description, color=self.bot.main_color)
        embed.timestamp = time if time is not None else datetime.datetime.utcnow()
        if fields is not None:
            for n, v, i in fields:
                n = str(n)
                v = str(v)

                if not n or not v:
                    logger.info('Invalid form name/body: %s, %s', n, v)
                    continue
                if len(n) > 256 or len(v) > 1024:
                    logger.info('Name/body too long: %s, %s', n, v)
                    continue
                embed.add_field(name=n, value=v, inline=i)
        if footer is not None:
            embed.set_footer(text=footer)
        return embed


def setup(bot):
    bot.add_cog(Logger(bot))
