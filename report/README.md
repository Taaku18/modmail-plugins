# Report

Create GitHub issues directly from Discord.

## Installation

To add this plugin, use this command in your Modmail server: `?plugin add report`.

## Usage

The commands usage list assumes you retain the default prefix, `?`.

| Permission level | Usage | Function | Note |
|------------------|-------|----------|------|
| ADMINISTRATOR [4] | `?token <access token>`, replace `<access token>` with your GitHub access token. | Sets the access token. | Access token must have permission to create issues. |
| REGULAR [1] | `?report <issue type>`, replace `<issue type>` with one one of the following: "bug", "feature request" ("request"), "new config" ("config"). | |