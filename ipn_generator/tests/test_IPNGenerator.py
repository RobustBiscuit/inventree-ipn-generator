from django.test import TestCase
from django.core.exceptions import ValidationError
import logging

from django.conf import settings
from part.models import PartCategory, SupplierPart, Part, PartCategoryParameterTemplate, PartParameterTemplate
from company.models import Company
from common.models import InvenTreeSetting

from plugin import registry

logger = logging.getLogger("inventree")


def setup_func(cls):
    settings.PLUGIN_TESTING_EVENTS = True
    settings.TESTING_TABLE_EVENTS = True
    InvenTreeSetting.set_setting("ENABLE_PLUGINS_EVENTS", True)
    cls.plugin = registry.get_plugin("ipngen")
    conf = cls.plugin.plugin_config()
    conf.active = True
    conf.save()


def teardown_func():
    settings.PLUGIN_TESTING_EVENTS = False
    settings.TESTING_TABLE_EVENTS = False
    InvenTreeSetting.set_setting("ENABLE_PLUGINS_EVENTS", False)


class IPNGeneratorPatternTests(TestCase):
    """Tests for verifying IPN pattern validation works properly"""

    def setUp(self):
        """Set up test environment"""
        setup_func(self)

    def tearDown(self):
        """Teardown test environment"""
        teardown_func()

    def test_cannot_add_only_literal(self):
        """Verify that setting PATTERN to only literals fails validation"""
        with self.assertRaises(ValidationError):
            self.plugin.set_setting("PATTERN", "(123)")

    def test_cannot_add_only_random_string(self):
        """Verify that setting PATTERN to an invalid string"""
        with self.assertRaises(ValidationError):
            self.plugin.set_setting("PATTERN", "asldkferljgjtdS:DfS_D:fE_SD:FA_;G")

    def test_numeric_setting_length_1(self):
        """Verify that numeric regex accepts more than 1 int."""
        # Single digit
        try:
            self.plugin.set_setting("PATTERN", "{1}")
        except ValidationError:
            self.fail("Correct numeric syntax raised a ValidationError")

    def test_numeric_setting_length_2(self):
        # Two digits
        try:
            self.plugin.set_setting("PATTERN", "{15}")
        except ValidationError:
            self.fail("Correct numeric syntax raised a ValidationError")

    def test_numeric_setting_length_3(self):
        # Multiple digits
        try:
            self.plugin.set_setting("PATTERN", "{125}")
        except ValidationError:
            self.fail("Correct numeric syntax raised a ValidationError")

    def text_numeric_setting_prefix_zero(self):
        """Zeroes should be filtered out when prefixed to numerics"""
        try:
            self.plugin.set_setting("PATTERN", "{05}")
        except ValidationError:
            self.fail("Numeric with 0 prefix raised a ValidationError")

    def test_numeric_setting_with_start(self):
        """Appending a + to numerics should work"""
        try:
            self.plugin.set_setting("PATTERN", "{25+}")
        except ValidationError:
            self.fail("Numeric with + suffix raised a ValidationError")

    def test_character_must_contain_more_than_one_character(self):
        """Verify that character groups must contain more than 1 character"""
        with self.assertRaises(ValidationError):
            self.plugin.set_setting("PATTERN", "[a]")

    def test_character_invalid_format(self):
        """Verify that character ranges are properly formatted"""
        with self.assertRaises(ValidationError):
            self.plugin.set_setting("PATTERN", "[a-]")

        with self.assertRaises(ValidationError):
            self.plugin.set_setting("PATTERN", "[aa-]")

    def test_character_range_valid(self):
        """Verify that properly formatted character ranges are accepted"""
        try:
            self.plugin.set_setting("PATTERN", "[a-b]")
        except ValidationError:
            self.fail("Valid character group range raised a ValidationError")

    def test_character_list_valid(self):
        """Verify that list of individual characters are accepted"""
        try:
            self.plugin.set_setting("PATTERN", "[abcsd]")
        except ValidationError:
            self.fail("Valid character list raised a ValidationError")

    def test_pattern_combinations(self):
        """"""
        try:
            self.plugin.set_setting("PATTERN", "(1b)[a-b]{2}")
        except ValidationError:
            self.fail("Valid pattern (1b)[a-b]{2} raised a ValidationError")

        try:
            self.plugin.set_setting("PATTERN", "[ab][a-d]{2}{3}")
        except ValidationError:
            self.fail("Valid pattern [ab][a-d]{2}{3} raised a ValidationError")

        try:
            self.plugin.set_setting("PATTERN", "{2}[bc](a2)[a-c]")
        except ValidationError:
            self.fail("Valid pattern {2}[bc](a2)[a-c] raised a ValidationError")

        try:
            self.plugin.set_setting("PATTERN", "[a-b](1s){2}(3d)")
        except ValidationError:
            self.fail("Valid pattern [a-b](1s){2}(3d) raised a ValidationError")

        try:
            self.plugin.set_setting("PATTERN", "{1}[aa]{2}(1r)")
        except ValidationError:
            self.fail("Valid pattern {1}[aa]{2}(1r) raised a ValidationError")


class InvenTreeIPNGeneratorNumericGroupTests(TestCase):
    """Tests verifying that numeric groupe behave properly"""

    def setUp(self):
        """Set up test environment"""
        setup_func(self)

    def tearDown(self):
        """Teardown test environment"""
        teardown_func()

    def test_add_numeric(self):
        """Verify that numeric patterns work."""

        self.plugin.set_setting("PATTERN", "{1}")

        cat = PartCategory.objects.all().first()
        new_part = Part.objects.create(category=cat, name="PartName")

        part = Part.objects.get(pk=new_part.pk)

        self.assertIsNotNone(part.IPN)

        self.assertEqual(part.IPN, "1")

    def test_add_numeric_with_start(self):
        """Verify that Numeric patterns with start number works."""

        self.plugin.set_setting("PATTERN", "{11+}")

        cat = PartCategory.objects.all().first()
        new_part = Part.objects.create(category=cat, name="PartName")

        self.assertEqual(Part.objects.get(pk=new_part.pk).IPN, "11")

    def test_add_numeric_incrementing(self):
        """Verify that numeric patterns increment on subsequent parts."""

        self.plugin.set_setting("PATTERN", "{1}")

        self.assertEqual(self.plugin.get_setting("PATTERN"), "{1}")

        cat = PartCategory.objects.all().first()
        Part.objects.create(category=cat, name="PartName")

        new_part = Part.objects.create(category=cat, name="PartName")

        part = Part.objects.get(pk=new_part.pk)

        self.assertEqual(part.IPN, "2")

    def test_add_numeric_incrementing_with_start(self):
        """Verify that numeric patterns with start number increment on subsequent parts."""
        self.plugin.set_setting("PATTERN", "{11+}")

        cat = PartCategory.objects.all().first()
        Part.objects.create(category=cat, name="PartName")

        new_part = Part.objects.create(category=cat, name="PartName")

        part = Part.objects.get(pk=new_part.pk)

        self.assertEqual(part.IPN, "12")

    def test_add_numeric_with_prepend_zero(self):
        """Verify that numeric patterns work."""

        self.plugin.set_setting("PATTERN", "{3}")

        cat = PartCategory.objects.all().first()
        new_part = Part.objects.create(category=cat, name="PartName")

        part = Part.objects.get(pk=new_part.pk)

        self.assertIsNotNone(part.IPN)

        self.assertEqual(part.IPN, "001")

    def test_numeric_rollover(self):
        """Verify that numeric groups rollover when reaching max"""

        self.plugin.set_setting("PATTERN", "{2}")

        cat = PartCategory.objects.all().first()
        Part.objects.create(category=cat, name="PartName", IPN="99")

        p = Part.objects.create(category=cat, name="PartName")

        part = Part.objects.get(pk=p.pk)
        self.assertEqual(part.IPN, "01")

    def test_numeric_with_start_rollover(self):
        """Verify that numeric groups with start number rollover when reaching max"""

        self.plugin.set_setting("PATTERN", "{26+}")

        cat = PartCategory.objects.all().first()
        Part.objects.create(category=cat, name="PartName", IPN="99")

        p = Part.objects.create(category=cat, name="PartName")

        part = Part.objects.get(pk=p.pk)
        self.assertEqual(part.IPN, "26")


class InvenTreeIPNGeneratorLiteralsTests(TestCase):
    """Tests verifying that literals function as they should"""

    def setUp(self):
        """Set up test environment"""
        setup_func(self)

    def tearDown(self):
        """Teardown test environment"""
        teardown_func()

    def test_literal_persists(self):
        """Verify literals do not change"""

        self.plugin.set_setting("PATTERN", "{1}(1v3)")

        cat = PartCategory.objects.all().first()

        Part.objects.create(category=cat, name="PartName")

        new_part = Part.objects.create(category=cat, name="PartName")

        part = Part.objects.get(pk=new_part.pk)

        self.assertEqual(part.IPN, "21v3")


class InvenTreeIPNGeneratorCharacterTests(TestCase):
    """Verify that character groups perform as they should"""

    def setUp(self):
        """Set up test environment"""
        setup_func(self)

    def tearDown(self):
        """Teardown test environment"""
        teardown_func()

    def test_character_list(self):
        """Verify that lists of characters are looped through."""

        self.plugin.set_setting("PATTERN", "[abc]")

        cat = PartCategory.objects.all().first()

        def gen_part(expected_ipn):
            p = Part.objects.create(category=cat, name="PartName")

            part = Part.objects.get(pk=p.pk)
            self.assertEqual(part.IPN, expected_ipn)

        gen_part("a")
        gen_part("b")
        gen_part("c")

    def test_character_list_rollover(self):
        """Verify that character lists restart after reaching the end"""

        self.plugin.set_setting("PATTERN", "[abc]")

        cat = PartCategory.objects.all().first()
        Part.objects.create(category=cat, name="PartName", IPN="c")

        p = Part.objects.create(category=cat, name="PartName")

        part = Part.objects.get(pk=p.pk)
        self.assertEqual(part.IPN, "a")

    def test_character_range(self):
        """Verify that ranges of characters are looped through."""

        self.plugin.set_setting("PATTERN", "[a-c]")

        cat = PartCategory.objects.all().first()

        def gen_part(expected_ipn):
            p = Part.objects.create(category=cat, name="PartName")

            part = Part.objects.get(pk=p.pk)
            self.assertEqual(part.IPN, expected_ipn)

        gen_part("a")
        gen_part("b")
        gen_part("c")

    def test_character_range_rollover(self):
        """Verify that character ranges loop around after reaching the end."""

        self.plugin.set_setting("PATTERN", "[a-c]")

        cat = PartCategory.objects.all().first()
        Part.objects.create(category=cat, name="PartName", IPN="c")

        p = Part.objects.create(category=cat, name="PartName")

        part = Part.objects.get(pk=p.pk)
        self.assertEqual(part.IPN, "a")


class IPNGeneratorCombiningTests(TestCase):
    """Verify that combining different groups works properly"""

    def setUp(self):
        """Set up test environment"""
        setup_func(self)

    def tearDown(self):
        """Teardown test environment"""
        teardown_func()

    def test_literal_and_number(self):
        """Verify literals and numbers work together"""

        self.plugin.set_setting("PATTERN", "(AB){2}")

        cat = PartCategory.objects.all().first()
        Part.objects.create(category=cat, name="PartName", IPN="AB12")

        p = Part.objects.create(category=cat, name="PartName")

        part = Part.objects.get(pk=p.pk)
        self.assertEqual(part.IPN, "AB13")

    def test_only_last_incrementable_is_changed(self):
        """Verify that only last group in pattern gets incremented"""

        self.plugin.set_setting("PATTERN", "[abc]{2}")

        cat = PartCategory.objects.all().first()
        Part.objects.create(category=cat, name="PartName", IPN="a25")

        p = Part.objects.create(category=cat, name="PartName")

        part = Part.objects.get(pk=p.pk)
        self.assertEqual(part.IPN, "a26")


class IPNGeneratorCategoryAwareTests(TestCase):
    """Tests for category-parameter-based IPN generation"""

    def setUp(self):
        setup_func(self)
        self.plugin.set_setting("CATEGORY_AWARE", True)
        self.plugin.set_setting("CATEGORY_PARAMETER_NAME", "sku_prefix")

        self.param_template = PartParameterTemplate.objects.create(name="sku_prefix")

        self.cat = PartCategory.objects.create(name="Test Subcategory")
        PartCategoryParameterTemplate.objects.create(
            category=self.cat,
            parameter_template=self.param_template,
            default_value="IC-ADC",
        )

        self.cat_no_param = PartCategory.objects.create(name="Unconfigured Category")

    def tearDown(self):
        teardown_func()

    def test_generates_correct_ipn_from_category_parameter(self):
        """Category with sku_prefix parameter produces correct IPN"""
        p = Part.objects.create(category=self.cat, name="TestPart")
        part = Part.objects.get(pk=p.pk)
        self.assertEqual(part.IPN, "IC-ADC-0001")

    def test_increments_sequentially(self):
        """Second part in same category gets next sequential IPN"""
        Part.objects.create(category=self.cat, name="TestPart1")
        p = Part.objects.create(category=self.cat, name="TestPart2")
        part = Part.objects.get(pk=p.pk)
        self.assertEqual(part.IPN, "IC-ADC-0002")

    def test_picks_up_existing_ipns_when_sequencing(self):
        """Sequential count is derived from existing matching IPNs in the database"""
        Part.objects.create(category=self.cat, name="ExistingPart", IPN="IC-ADC-0042")
        p = Part.objects.create(category=self.cat, name="NewPart")
        part = Part.objects.get(pk=p.pk)
        self.assertEqual(part.IPN, "IC-ADC-0043")

    def test_category_without_parameter_skips_ipn(self):
        """Parts in categories without sku_prefix get no IPN assigned"""
        p = Part.objects.create(category=self.cat_no_param, name="TestPart")
        part = Part.objects.get(pk=p.pk)
        self.assertFalse(part.IPN)

    def test_manual_ipn_not_overwritten(self):
        """Parts with a manually set IPN are not overwritten"""
        p = Part.objects.create(category=self.cat, name="TestPart", IPN="MANUAL-001")
        part = Part.objects.get(pk=p.pk)
        self.assertEqual(part.IPN, "MANUAL-001")

    def test_category_aware_false_falls_back_to_pattern(self):
        """When CATEGORY_AWARE is False, pattern-based generation is used instead"""
        self.plugin.set_setting("CATEGORY_AWARE", False)
        self.plugin.set_setting("PATTERN", "{4}")

        p = Part.objects.create(category=self.cat, name="TestPart")
        part = Part.objects.get(pk=p.pk)
        self.assertEqual(part.IPN, "0001")


class IPNGeneratorModelTests(TestCase):
    """Verify model behaviours"""

    def setUp(self):
        """Set up test environment"""
        setup_func(self)

    def tearDown(self):
        """Teardown test environment"""
        teardown_func()

    def test_supplier_part_does_not_trigger_plugin(self):
        """Supplier parts events should not trigger the plugin"""

        cat = PartCategory.objects.all().first()
        part = Part.objects.create(category=cat, name="PartName")
        supplier = Company.objects.create(name="Suppliercompany", currency="USD")

        with self.assertLogs(logger=logger, level="DEBUG") as cm:
            SupplierPart.objects.create(part=part, SKU="abc", supplier=supplier)
            self.assertNotIn(
                "DEBUG:inventree:Plugin 'ipngen' is processing triggered event 'part_part.created'",
                cm[1],
            )
