from plugin import InvenTreePlugin
from plugin.mixins import EventMixin, SettingsMixin
from part.models import Part

from django.core.exceptions import ValidationError

import json
import logging
import re

logger = logging.getLogger("inventree")

PERMITTED_SPECIAL_LITERALS = "\-.:/\\"

# Illustrative examples only — replace with your own mappings via the plugin settings UI:
# Settings → Plugins → IPN Generator → Primary / Secondary Category Mapping.
_DEFAULT_PRIMARY_MAPPING = json.dumps({
    "Resistors": "RES",
    "Capacitors": "CAP",
    "Integrated Circuits": "IC",
})

_DEFAULT_SECONDARY_MAPPING = json.dumps({
    "Surface Mount": "SMD",
    "Through Hole": "THL",
    "0402": "0402",
    "Analog-to-Digital": "ADC",
})


def validate_pattern(pattern):
    """Validates pattern groups"""
    regex = re.compile(r"(\{\d+\+?\})|(\[(?!\w\])(?:\w+|(?:\w-\w)+)+\])")
    if not regex.search(pattern):
        raise ValidationError("Pattern must include more than Literals")

    return True


class AutoGenIPNPlugin(EventMixin, SettingsMixin, InvenTreePlugin):
    """Plugin to generate IPN automatically"""

    AUTHOR = "Nichlas W."
    DESCRIPTION = (
        "Plugin for automatically assigning IPN to parts created with empty IPN fields.\
        IPN pattern syntax can be found on the website linked here."
    )
    VERSION = "0.1"
    WEBSITE = "https://github.com/LavissaWoW/inventree-ipn-generator"

    NAME = "IPNGenerator"
    SLUG = "ipngen"
    TITLE = "IPN Generator"

    SETTINGS = {
        "ACTIVE": {
            "name": "Active",
            "description": "IPN generator is active",
            "validator": bool,
            "default": True,
        },
        "ON_CREATE": {
            "name": "On Create",
            "description": "Active when creating new parts",
            "validator": bool,
            "default": True,
        },
        "ON_CHANGE": {
            "name": "On Edit",
            "description": "Active when editing existing parts",
            "validator": bool,
            "default": False,
        },
        "CATEGORY_AWARE": {
            "name": "Category Aware",
            "description": "Generate IPN from the part's category path. If disabled, falls back to the PATTERN setting.",
            "validator": bool,
            "default": True,
        },
        "PRIMARY_MAPPING": {
            "name": "Primary Category Mapping",
            "description": "JSON mapping of top-level category names to SKU codes, e.g. {\"Antennas\": \"ANT\"}",
            "default": _DEFAULT_PRIMARY_MAPPING,
        },
        "SECONDARY_MAPPING": {
            "name": "Secondary Category Mapping",
            "description": "JSON mapping of sub-category names to SKU codes, e.g. {\"Surface Mount\": \"SMD\"}",
            "default": _DEFAULT_SECONDARY_MAPPING,
        },
        "PATTERN": {
            "name": "IPN pattern",
            "description": "Pattern for IPN generation, used when Category Aware is disabled (See website for guide)",
            "default": "(IPN-){4}",
            "validator": validate_pattern,
        },
    }

    min_pattern_char = ord("A")
    max_pattern_char = ord("Z")
    skip_chars = range(ord("["), ord("a"))

    def plugin_ready(self):
        """Write default values to the DB for any settings that have no record yet.

        InvenTree's settings UI only renders settings that have a DB record.
        Without this, freshly installed plugins show blank fields for settings
        that have large defaults (like the JSON mapping strings).
        """
        from plugin.models import PluginSetting

        for key, config in self.SETTINGS.items():
            if "default" not in config:
                continue
            exists = PluginSetting.objects.filter(
                plugin=self.plugin_config(), key=key
            ).exists()
            if not exists:
                self.set_setting(key, config["default"])

    def wants_process_event(self, event):
        """Lets InvenTree know what events to listen for."""

        if not self.get_setting("ACTIVE"):
            return False

        if event == "part_part.saved":
            return self.get_setting("ON_CHANGE")

        if event == "part_part.created":
            return self.get_setting("ON_CREATE")

        return False

    def _get_sku_prefix(self, part):
        """Derive the SKU prefix from the part's category pathstring and the configured mappings.

        Reads part.category.pathstring (e.g. 'Antennas/Surface Mount'), splits it into
        primary and secondary names, and looks each up in the JSON mapping settings.
        Returns the prefix string (e.g. 'ANT-SMD') or None if the category is unmapped.
        """
        if not part.category:
            logger.warning("IPN Generator: Part has no category; skipping IPN generation")
            return None

        pathstring = part.category.pathstring or ""
        path_parts = [p.strip() for p in pathstring.split("/")]

        if len(path_parts) < 2:
            logger.warning(
                f"IPN Generator: Category '{pathstring}' is a top-level category with no parent; "
                "skipping IPN generation."
            )
            return None

        primary_name, secondary_name = path_parts[0], path_parts[1]

        try:
            primary_map = json.loads(self.get_setting("PRIMARY_MAPPING") or "{}")
            secondary_map = json.loads(self.get_setting("SECONDARY_MAPPING") or "{}")
        except json.JSONDecodeError as e:
            logger.warning(f"IPN Generator: Invalid JSON in mapping settings: {e}")
            return None

        primary_code = primary_map.get(primary_name)
        secondary_code = secondary_map.get(secondary_name)

        if not primary_code:
            logger.warning(
                f"IPN Generator: No code found for primary category '{primary_name}'; "
                "add it to the PRIMARY_MAPPING setting."
            )
            return None

        if not secondary_code:
            logger.warning(
                f"IPN Generator: No code found for sub-category '{secondary_name}'; "
                "add it to the SECONDARY_MAPPING setting."
            )
            return None

        return f"{primary_code}-{secondary_code}"

    def _find_next_sequential(self, prefix):
        """Return the next zero-padded 4-digit sequence number for the given SKU prefix."""
        existing = Part.objects.filter(IPN__startswith=f"{prefix}-").values_list("IPN", flat=True)

        max_seq = 0
        for ipn in existing:
            suffix = ipn[len(prefix) + 1:]
            try:
                seq = int(suffix)
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                continue

        return str(max_seq + 1).zfill(4)

    def process_event(self, event, *args, **kwargs):
        """Main plugin handler function"""

        if not self.get_setting("ACTIVE"):
            return False

        id = kwargs.pop("id", None)
        model = kwargs.pop("model", None)

        # Events can fire on unrelated models
        if model != "Part":
            logger.debug("IPN Generator: Event Model is not part")
            return

        # Don't create IPNs for parts with IPNs
        part = Part.objects.get(id=id)
        if part.IPN:
            return

        if self.get_setting("CATEGORY_AWARE"):
            prefix = self._get_sku_prefix(part)
            if prefix is None:
                return
            seq = self._find_next_sequential(prefix)
            part.IPN = f"{prefix}-{seq}"
            part.save()
            return

        expression = self.construct_regex(True)
        latest = Part.objects.filter(IPN__regex=expression).order_by("-IPN").first()

        if not latest:
            part.IPN = self.construct_first_ipn()
        else:
            grouped_expression = self.construct_regex()
            part.IPN = self.increment_ipn(grouped_expression, latest.IPN)

        part.save()

        return

    def construct_regex(self, disable_groups=False):
        """Constructs a valid regex from provided IPN pattern.
        This regex is used to find the latest assigned IPN
        """
        regex = "^"

        m = re.findall(
            r"(\{\d+\+?\})|(\([\w\(\)\-.:/\\]+\))|(\[(?:\w+|\w-\w)+\])",
            self.get_setting("PATTERN"),
        )

        for idx, group in enumerate(m):
            numeric, literal, character = group
            # Numeric, increment
            if numeric:
                start = "+" in numeric
                g = numeric.strip("{}+")
                if start:
                    regex += "("
                    if not disable_groups:
                        regex += f"?P<Np{g}i{idx}>"
                    for char in g:
                        regex += f"[{char}-9]"
                else:
                    regex += "("
                    if not disable_groups:
                        regex += f"?P<N{g}i{idx}>"
                    regex += f"\d{ {int(g)} }"
                regex += ")"

            # Literal, won't change
            if literal:
                lit = literal.strip("()")
                regex += "("
                if not disable_groups:
                    regex += f"?P<Li{idx}>"
                regex += f"{re.escape(lit)})"

            # Letters, a collection or sequence
            # Sequences incremented using ASCII
            if character:
                regex += "("
                if not disable_groups:
                    regex += "?P<C"

                sequences = re.findall(r"(\w)(?!-)|(\w\-\w)", character)

                exp = []
                for seq in sequences:
                    single, range = seq

                    if single:
                        exp.append(single)
                    elif range:
                        exp.append(range)

                if not disable_groups:
                    regex += f'{"_".join(exp).replace("-", "")}i{idx}>'
                regex += f'[{"".join(exp)}]'
                regex += ")"

        regex += "$"

        return regex

    def increment_ipn(self, exp, latest):
        """Deconstructs IPN pattern based on latest IPN and constructs a the next IPN in the series."""
        m: re.Match = re.match(exp, latest)

        ipn_list = []

        # True after a fields has been incremented
        # Does not apply on count rollover (i.e. 999 -> 001)
        incremented = False

        for key, val in reversed(m.groupdict().items()):
            type, _ = key.split("i")

            if incremented or type == "L":
                ipn_list.append(val)
                continue

            if type == "N":
                ipn_list.append(str(int(val) + 1))
                incremented = True
            elif type.startswith("C"):
                integerized_char = ord(val)
                choices = type[1:].split("_")

                ranges = any(len(x) > 1 for x in choices)

                if not ranges:
                    if choices.index(val) == len(choices) - 1:
                        ipn_list.append(choices[0])
                    else:
                        ipn_list.append(choices[choices.index(val) + 1])
                        incremented = True
                else:
                    for choice in choices:
                        if len(choice) > 1:
                            min = ord(choice[0])
                            max = ord(choice[1])
                            if integerized_char in range(min, max + 1):
                                if integerized_char == max:
                                    ipn_list.append(choice[0])
                                else:
                                    ipn_list.append(chr(integerized_char + 1))
                                incremented = True
                                break
                        elif choices.index(val) < choices.index(choice):
                            ipn_list.append(choice)
                            incremented = True
                            break

            elif type.startswith("N"):
                if type[1] == "p":
                    num = int(type[2:])
                else:
                    num = int(type[1:])
                if type[1] == "p":
                    next = int(val) + 1
                    if len(str(next)) > len(type[2:]):
                        ipn_list.append(type[2:])
                    else:
                        ipn_list.append(str(next))
                elif len(str(int(val) + 1)) > num:
                    ipn_list.append(str(1).zfill(num))
                else:
                    ipn_list.append(str(int(val) + 1).zfill(num))
                    incremented = True

        ipn_list.reverse()
        return "".join(ipn_list)

    def construct_first_ipn(self):
        """No IPNs matching the pattern were found. Constructing the first IPN."""
        m = re.findall(
            r"(\{\d+\+?\})|(\([\w\(\)\-.:/\\]+\))|(\[(?:\w+|(?:\w-\w)+)\])",
            self.get_setting("PATTERN"),
        )

        ipn = ""

        for group in m:
            numeric, literal, character = group
            if numeric:
                num = numeric.strip("{}+")
                if "+" in numeric:
                    ipn += num
                else:
                    ipn += str(1).zfill(int(num))

            if literal:
                ipn += literal.strip("()")

            if character:
                ipn += character.strip("[]")[0]

        return ipn
