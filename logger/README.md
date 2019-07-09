# Logger

Provides logging for Discord events (message edits, user join, user leave, message deletes, etc).

This only logs activity in the main Modmail guild.

## Installation

To add this plugin, use this command in your Modmail server: `?plugin add logger`.

## Usage

The commands usage list assumes you retain the default prefix, `?`.

| Permission level | Usage | Function | Note |
|------------------|-------|----------|------|
| ADMINISTRATOR [4] | `?lchannel #channel` | Sets the channel for the log messages. | Has to be a channel in Modmail's functioning guild (destined by `GUILD_ID`). |
| ADMINISTRATOR [4] | `?lmodmail` | Toggle whether to log Modmail bot messages. | Defaults to yes. |
| ADMINISTRATOR [4] | `?nolog #channel` | Toggle whether to log a channel or category. | Can be either channel or category. |
