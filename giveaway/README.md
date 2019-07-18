# Colors

Simple plugin to work with colors.

## Installation

To add this plugin, use this command in your Modmail server: `?plugin add colors`.

## Usage

The commands usage list assumes you retain the default prefix, `?`.

| Permission level | Usage | Function | Note |
|------------------|-------|----------|------|
| REGULAR [1] | `?color <color name>`, replace `<color name>` with the name of the color. | Convert a color name to its relative hex code and RGB value. | May not always be the inverse of `?color hex` or `?color rgb`. |
| REGULAR [1] | `?color hex <color hex>`, replace `<color hex>` with the hex code of the color. | Convert a hex code to it's relative color name. | May not always be the inverse of `?color`. |
| REGULAR [1] | `?color rgb <color RGB>`, replace `<color RGB>` with the RGB value of the color. | Convert a RGB value to it's relative color name. | May not always be the inverse of `?color`. |
| REGULAR [1] | `?rgbtohex <color RGB>`, replace `<color RGB>` with the RGB value of the color. | Calculates the hex code from an RGB value. Reverse of `?hextorgb`. | |
| REGULAR [1] | `?hextorgb <color hex>`, replace `<color hex>` with the hex code of the color. | Calculates the RGB from an hex code. Reverse of `?rgbtohex`. | |

