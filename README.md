[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

## Introduction
This is a plugin for [InvenTree](https://github.com/inventree/InvenTree/).
Installing this plugin enables the automatic generation if Internal Part Numbers (IPN) for parts.

## Installation
To automatically install the plugin when running `invoke install`:
Add `inventree-ipn-generator` to your plugins.txt file.

Or, install the plugin manually:

```
pip install inventree-ipn-generator
```

For the plugin to be listed as available, you need to enable "Event Integration" in your plugin settings.
This setting is located with the Plugin Settings on the settings page.

## Settings

- Active - Enables toggling of plugin without having to disable it
- On Create - If on, the plugin will assign IPNs to newly created parts
- On Change - If on, the plugin will assign IPNs to parts after a change has been made.
Enabling this setting will remove the ability to have parts without IPNs.
- Category Aware - If on, IPNs are built from the part's category hierarchy (see below). If off, the Pattern setting is used instead.
- Category IPN Code Key - The metadata key on each category that holds its IPN code (default `ipn_code`).
- Notify on Allocation - If on, an in-app notification is sent to all active users each time an IPN is allocated (see below).

## Category-Aware IPN Generation

When **Category Aware** is enabled, the plugin builds an IPN of the form:

```
{PRIMARY_CODE}-{SECONDARY_CODE}-{SEQUENCE}     e.g.  RES-0402-0001
```

The codes are read from each category's **metadata**, not from a central mapping.
Store a short `ipn_code` on each category:

- The part's category (the sub-category) provides the **secondary** code.
- Its parent category provides the **primary** code.

For example, a part in `Resistors / 0402` where `Resistors` has `ipn_code = "RES"`
and `0402` has `ipn_code = "0402"` receives `RES-0402-0001`, then `RES-0402-0002`, etc.

If either category is missing its `ipn_code`, or the part sits in a top-level
category with no parent, the plugin logs a warning and leaves the IPN blank so
you can set it manually.

### Setting category codes

You can set the `ipn_code` metadata on individual categories via the InvenTree
API or admin. To bulk-populate many categories at once, edit and run the helper
script in [`tools/set_category_codes.py`](tools/set_category_codes.py):

```
python tools/set_category_codes.py --url https://your-inventree --token YOUR_TOKEN --dry-run
```

Drop `--dry-run` to apply.

## Wildcard Auto-complete

You can force a specific IPN prefix on any part by setting its IPN to a value
containing `*`. The plugin replaces the `*` with the next sequential number for
that prefix, overriding category-aware generation:

```
Set IPN to "CAP-0402-*"   ->   CAP-0402-0001   (then CAP-0402-0002, ...)
```

This works whether or not Category Aware is enabled, and is handy when a part
doesn't fit its category's mapping. Everything before the first `*` (minus a
trailing `-`) is used as the literal prefix.

> **Note:** Setting a wildcard on a **newly created** part works out of the box.
> To use it on an **existing** part you must enable the *On Change* setting, since
> the plugin only re-processes saved parts when that is on.

## Allocation Notifications

When **Notify on Allocation** is enabled (default), the plugin posts an in-app
notification to the InvenTree notification tray every time it assigns an IPN —
whether via category-aware, wildcard, or pattern generation. The message reads,
for example: *"IPN RES-0402-0001 was allocated to part 'My Part'."*

The notification is sent to **all active users**, regardless of permissions or
subscriptions. It is delivered to the in-app tray only (not email).

## Pattern (legacy / non-category mode)
Part Number patterns follow three basic groups. Literals, Numerics, and characters.
When incrementing a part number, the rightmost group that is mutable will be incremented.
All groups can be combined in any order.

A pattern cannot consist of _only_ Literals.

For any pattern, only the rightmost non-literal group will be incremented.
When this group rolls over its max, the next non-literal group to the left will be incremented.
Example: Given the groups (named for demo): L1C1N1C2L2
Incrementing follows this order: C2, N1, C1.

> **_NOTE:_** When C1 in the above example rolls over, the plugin will loop back to the first IPN.
> This will cause duplicate IPNs if your InvenTree allows duplicate IPNs.
> If your InvenTree does not allow duplicate IPNs, this will cause an error at the moment!
> This will be addressed in an upcoming update.

### Literals (Immutable)
Anything encased in `()` will be rendered as-is. no change will be made to anything within.

Example: `(A6C)` will _always_ render as "A6C", regardless of other groups

### Numeric
Numbers that should change over time should be encased in `{}`
- `{5}` respresents a number with max 5 digits
- `{25+}` represents a number 25-99

Example: `{5+}{3}` will result in this range: 5000-9999

### Characters
Characters that change should be encased in `[]`
- `[abc]` represents looping through the letters `a`, `b`, `c` in order.
- `[a-f]` represents looping through the letters from `a` to `f` alphabetaically

These two directives can be combined.
- `[aQc-f]` represents:
- - `a`, `Q`, `c-f`

### Examples
1. `(AB){3}[ab]` -> AB001a, AB001b, AB002a, AB021b, AB032a, etc
2. `{2}[Aq](BD)` -> 01ABD, 01qBD, 02ABD, 02qBD, etc
3. `{1}[a-d]{8+}` -> 1a8, 1a9, 1b8, 1b9, 1c8, 1c9, 1d8, 1d9, 2a8, etc
