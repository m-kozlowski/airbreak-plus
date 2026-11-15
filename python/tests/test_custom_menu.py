"""Placement contracts; no firmware behavior is mocked by these tests."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.custom_menu import MenuBuilder, stock, custom


class MenuPlacementTests(unittest.TestCase):
    def setUp(self):
        self.menu = MenuBuilder()
        self.sites = {(0, 'FIRST'): 100, (0, 'LAST'): 200, (0, None): 200,
                      (1, None): 300, (4, None): 400}

    def anchors(self, container, name):
        try:
            return self.sites[container, name]
        except KeyError:
            raise ValueError('unknown stock anchor') from None

    def add(self, item, container=0, flags=0, **placement):
        return self.menu.add((container, flags, item, 0xfff), **placement)

    def plan(self):
        return self.menu.compile(self.anchors, int)

    def ids(self):
        return [entry[2] for entry in self.plan().entries]

    def test_default_section_order_and_only_used_hooks(self):
        self.add(10)
        self.add(20, container=4)
        self.add(11)
        plan = self.plan()
        self.assertEqual([e[2] for e in plan.entries], [10, 11, 20])
        self.assertEqual([(d.site, d.after_count) for d in plan.dispatch], [(200, 2), (400, 1)])

    def test_before_after_and_custom_chain(self):
        last = self.add(10, after=stock('FIRST'))
        self.add(11, after=last)
        self.add(12, before=last)
        self.add(13, before=stock('FIRST'))
        self.add(14, after=stock('FIRST'))
        self.assertEqual(self.ids(), [13, 12, 10, 11, 14])
        d, = self.plan().dispatch
        self.assertEqual((d.before_first, d.before_count, d.after_first, d.after_count), (0, 1, 1, 4))

    def test_custom_descendants_stay_on_same_side_of_native_row(self):
        a = self.add(1, before=stock('FIRST'))
        self.add(2, after=a)
        self.add(3, after=stock('FIRST'))
        self.assertEqual(self.ids(), [1, 2, 3])
        self.assertEqual(self.plan().dispatch[0].before_count, 2)

    def test_forward_custom_reference(self):
        self.add(2, after=custom(1))
        self.add(1, before=stock('FIRST'))
        self.assertEqual(self.ids(), [1, 2])

    def test_native_order_wins_over_registration_order(self):
        self.add(3, after=stock('LAST'))
        self.add(2, before=stock('LAST'))
        self.add(1, after=stock('FIRST'))
        self.assertEqual(self.ids(), [1, 2, 3])
        self.assertEqual(len(self.plan().dispatch), 2)

    def test_default_and_explicit_end_share_one_dispatch(self):
        self.add(1)
        self.add(2, after=stock('LAST'))
        self.assertEqual(len(self.plan().dispatch), 1)
        self.assertEqual(self.ids(), [1, 2])

    def test_heading_and_page_handles(self):
        heading = self.add(100, flags=2, before=stock('FIRST'))
        page = self.add(101, flags=4, after=heading)
        self.add(1, before=page)
        self.assertEqual(self.ids(), [100, 1, 101])

    def test_nested_page_ordinals_follow_reordered_registry(self):
        self.add(100, container=4, flags=4)   # page A: old 0x80
        self.add(101, flags=4)                # page B: old 0x81
        self.add(102, container=0x80, flags=4)  # nested page C: old 0x82
        self.add(1, container=0x80)
        self.add(2, container=0x81)
        self.add(3, container=0x82)
        plan = self.plan()
        self.assertEqual(plan.page_containers, {0x81: 0x80, 0x80: 0x81, 0x82: 0x82})
        self.assertEqual({e[2]: e[0] for e in plan.entries},
                         {100: 4, 101: 0, 102: 0x81, 1: 0x81, 2: 0x80, 3: 0x82})
        self.assertEqual(len(plan.dispatch), 2)

    def test_generated_page_order_and_heading_scope(self):
        self.add(100, flags=4)
        self.add(1, container=0x80)
        heading = self.add(200, container=0x80, flags=2)
        self.add(3, container=0x80, after=heading)
        self.add(2, container=0x80, before=heading)
        self.assertEqual(self.ids(), [100, 1, 2, 200, 3])
        self.assertEqual(len(self.plan().dispatch), 1)

    def test_cycles_including_disconnected_and_self(self):
        for pairs in ([(1, 1)], [(1, 2), (2, 1)]):
            with self.subTest(pairs=pairs):
                self.menu = MenuBuilder()
                for item, target in pairs:
                    self.add(item, after=custom(target))
                with self.assertRaisesRegex(ValueError, 'cycle'):
                    self.plan()

    def test_missing_custom_and_stock_are_errors(self):
        for reference in (custom(99), stock('MISSING')):
            with self.subTest(reference=reference):
                self.menu = MenuBuilder()
                self.add(1, after=reference)
                with self.assertRaises(ValueError):
                    self.plan()

    def test_cross_container_reference_is_error(self):
        item = self.add(1)
        self.add(2, container=4, after=item)
        with self.assertRaisesRegex(ValueError, 'crosses containers'):
            self.plan()

    def test_foreign_handle_is_error(self):
        other = MenuBuilder().add((0, 0, 99, 1))
        self.add(1, after=other)
        with self.assertRaisesRegex(ValueError, 'another registry'):
            self.plan()

    def test_stock_anchor_in_generated_page_is_error(self):
        self.add(100, flags=4)
        self.add(1, container=0x80, after=stock('FIRST'))
        with self.assertRaisesRegex(ValueError, 'no stock anchors'):
            self.plan()

    def test_invalid_placement_and_limit(self):
        with self.assertRaisesRegex(ValueError, 'either'):
            self.add(1, before=stock('FIRST'), after=stock('LAST'))
        with self.assertRaisesRegex(ValueError, 'requires'):
            self.add(1, after='FIRST')
        self.assertEqual(len(self.menu.entries), 0)
        for i in range(MenuBuilder.LIMIT):
            self.add(i)
        self.assertEqual(self.plan().dispatch[0].after_count, MenuBuilder.LIMIT)
        with self.assertRaisesRegex(ValueError, 'limit'):
            self.add(100)


if __name__ == '__main__':
    unittest.main()
