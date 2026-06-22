from plugin import InvenTreePlugin
from plugin.mixins import EventMixin, SettingsMixin
from part.models import Part

from django.core.exceptions import ValidationError

import logging
import re

logger = logging.getLogger("inventree")

PERMITTED_SPECIAL_LITERALS = "\-.:/\\"

# Default key under which each PartCategory stores its IPN code in the
# category's `metadata` field (e.g. {"ipn_code": "RES"}). Configurable via
# the METADATA_KEY plugin setting.
_DEFAULT_METADATA_KEY = "ipn_code"


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
        "Plugin for automatically assigning IPNs to parts created with empty IPN fields. "
        "Supports category-aware IPN generation from the part's category hierarchy, "
        "or pattern-based generation. See the website for syntax."
    )
    VERSION = "0.3.0"
    WEBSITE = "https://github.com/RobustBiscuit/inventree-ipn-generator"

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
            "description": "Generate IPN from the part's category hierarchy. If disabled, falls back to the PATTERN setting.",
            "validator": bool,
            "default": True,
        },
        "METADATA_KEY": {
            "name": "Category IPN Code Key",
            "description": "The metadata key on each PartCategory that holds its IPN code, e.g. 'ipn_code'.",
            "default": _DEFAULT_METADATA_KEY,
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

    def _assign_ipn(self, part, ipn):
        """Single chokepoint for assigning an IPN: set, persist, and log.

        Centralising assignment here keeps a future notification feature simple —
        it can emit an "IPN allocated" notification from this one place.
        """
        part.IPN = ipn
        part.save()
        logger.info("IPN Generator: assigned IPN '%s' to part %s", ipn, part.pk)

    def _wildcard_prefix(self, ipn):
        """Return the literal prefix from a wildcard IPN.

        Takes everything before the first '*' and strips a trailing '-':
        'CAP-0402-*' -> 'CAP-0402'; 'CAP-*-0402' -> 'CAP'; '*' -> ''.
        """
        return ipn.split("*", 1)[0].rstrip("-")

    def _get_category_code(self, category):
        """Return the IPN code stored in a category's metadata, or None if unset."""
        if category is None:
            return None
        key = self.get_setting("METADATA_KEY") or _DEFAULT_METADATA_KEY
        code = category.get_metadata(key)
        if not code:
            return None
        return str(code).strip()

    def _get_ipn_prefix(self, part):
        """Derive the IPN prefix from the part's category hierarchy.

        Reads the IPN code stored in the metadata of the part's category (secondary)
        and its parent category (primary), e.g. 'RES' + '0402' -> 'RES-0402'.
        Returns the prefix string or None if the category hierarchy is incomplete
        or either code is missing.
        """
        if not part.category:
            logger.warning("IPN Generator: Part has no category; skipping IPN generation")
            return None

        secondary_cat = part.category
        primary_cat = part.category.parent

        if primary_cat is None:
            logger.warning(
                f"IPN Generator: Category '{secondary_cat.pathstring}' is a top-level category "
                "with no parent; skipping IPN generation."
            )
            return None

        primary_code = self._get_category_code(primary_cat)
        secondary_code = self._get_category_code(secondary_cat)

        key = self.get_setting("METADATA_KEY") or _DEFAULT_METADATA_KEY

        if not primary_code:
            logger.warning(
                f"IPN Generator: Category '{primary_cat.pathstring}' has no '{key}' metadata; "
                "set it to enable IPN generation."
            )
            return None

        if not secondary_code:
            logger.warning(
                f"IPN Generator: Category '{secondary_cat.pathstring}' has no '{key}' metadata; "
                "set it to enable IPN generation."
            )
            return None

        return f"{primary_code}-{secondary_code}"

    def _find_next_sequential(self, prefix):
        """Return the next zero-padded 4-digit sequence number for the given IPN prefix."""
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

        part = Part.objects.get(id=id)

        # Wildcard auto-complete: a user-entered IPN like "CAP-0402-*" forces the
        # next sequential number for that literal prefix, overriding category-aware
        # logic. Must run BEFORE the "skip parts with IPNs" guard, since the
        # wildcard value is itself truthy.
        if part.IPN and "*" in part.IPN:
            prefix = self._wildcard_prefix(part.IPN)
            if not prefix:
                logger.warning(
                    "IPN Generator: wildcard IPN '%s' has no usable prefix; leaving as-is",
                    part.IPN,
                )
                return
            seq = self._find_next_sequential(prefix)
            self._assign_ipn(part, f"{prefix}-{seq}")
            return

        # Don't create IPNs for parts that already have a (non-wildcard) IPN
        if part.IPN:
            return

        if self.get_setting("CATEGORY_AWARE"):
            prefix = self._get_ipn_prefix(part)
            if prefix is None:
                return
            seq = self._find_next_sequential(prefix)
            self._assign_ipn(part, f"{prefix}-{seq}")
            return

        expression = self.construct_regex(True)
        latest = Part.objects.filter(IPN__regex=expression).order_by("-IPN").first()

        if not latest:
            new_ipn = self.construct_first_ipn()
        else:
            grouped_expression = self.construct_regex()
            new_ipn = self.increment_ipn(grouped_expression, latest.IPN)

        self._assign_ipn(part, new_ipn)

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
