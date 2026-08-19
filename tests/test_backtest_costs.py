"""Behavioural spec for transaction costs, slippage and capacity."""

import unittest
from datetime import date

import pandas as pd

from backtest.costs import (
    BUY,
    DEFAULT_SCHEDULES,
    SELL,
    ChargeSchedule,
    CostModel,
    apply_costs,
    capacity_report,
    round_trip_cost_rate,
)


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.model = CostModel()

    def test_schedule_in_force_is_selected_by_date(self):
        self.assertEqual(
            self.model.schedule_for(date(2022, 8, 1)).exchange_txn_rate, 0.0000325
        )
        self.assertEqual(
            self.model.schedule_for(date(2025, 1, 1)).exchange_txn_rate, 0.0000297
        )

    def test_boundary_date_uses_the_new_schedule(self):
        self.assertEqual(
            self.model.schedule_for(date(2024, 10, 1)).exchange_txn_rate, 0.0000297
        )

    def test_day_before_boundary_uses_the_old_schedule(self):
        self.assertEqual(
            self.model.schedule_for(date(2024, 9, 30)).exchange_txn_rate, 0.0000322
        )

    def test_date_before_every_schedule_falls_back_not_to_zero_cost(self):
        """A pre-window date must not silently become a free trade."""
        self.assertGreater(
            self.model.explicit_fees(100000, BUY, date(2010, 1, 1)), 0.0
        )

    def test_charges_are_not_hard_coded_to_one_era(self):
        early = self.model.explicit_fees(1_000_000, BUY, date(2022, 8, 1))
        late = self.model.explicit_fees(1_000_000, BUY, date(2025, 8, 1))
        self.assertNotAlmostEqual(early, late)

    def test_empty_schedule_list_is_rejected(self):
        with self.assertRaises(ValueError):
            CostModel(schedules=())


class ExplicitFeeTests(unittest.TestCase):
    def setUp(self):
        self.model = CostModel()
        self.value = 100_000.0
        self.day = date(2025, 1, 15)

    def test_buy_leg_pays_stamp_duty(self):
        """Isolated by zeroing the rate: at 1 lakh the flat DP charge on the sell
        leg (Rs 15.93) slightly exceeds stamp duty (Rs 15), so comparing the two
        legs directly would test the wrong thing."""
        no_stamp = CostModel(
            schedules=(
                ChargeSchedule(
                    effective_from=date(2020, 1, 1), stamp_duty_buy_rate=0.0
                ),
            )
        )
        with_stamp = CostModel(
            schedules=(
                ChargeSchedule(
                    effective_from=date(2020, 1, 1), stamp_duty_buy_rate=0.00015
                ),
            )
        )
        difference = with_stamp.explicit_fees(
            self.value, BUY, self.day
        ) - no_stamp.explicit_fees(self.value, BUY, self.day)
        self.assertAlmostEqual(difference, self.value * 0.00015, places=6)

    def test_sell_leg_pays_no_stamp_duty(self):
        no_stamp = CostModel(
            schedules=(
                ChargeSchedule(
                    effective_from=date(2020, 1, 1), stamp_duty_buy_rate=0.0
                ),
            )
        )
        with_stamp = CostModel(
            schedules=(
                ChargeSchedule(
                    effective_from=date(2020, 1, 1), stamp_duty_buy_rate=0.00015
                ),
            )
        )
        self.assertAlmostEqual(
            with_stamp.explicit_fees(self.value, SELL, self.day),
            no_stamp.explicit_fees(self.value, SELL, self.day),
            places=6,
        )

    def test_sell_leg_pays_a_flat_dp_charge(self):
        small = self.model.explicit_fees(1_000.0, SELL, self.day)
        self.assertGreaterEqual(small, DEFAULT_SCHEDULES[-1].dp_charge_per_sell)

    def test_dp_charge_hits_small_positions_hardest(self):
        small_rate = self.model.explicit_fees(2_000.0, SELL, self.day) / 2_000.0
        large_rate = self.model.explicit_fees(2_000_000.0, SELL, self.day) / 2_000_000.0
        self.assertGreater(small_rate, large_rate)

    def test_stt_dominates_the_explicit_cost(self):
        fees = self.model.explicit_fees(self.value, BUY, self.day)
        stt = self.value * 0.001
        self.assertGreater(stt / fees, 0.7)

    def test_gst_applies_to_service_charges_not_to_stt(self):
        """With zero brokerage, GST is tiny; if it hit STT it would not be."""
        fees = self.model.explicit_fees(self.value, BUY, self.day)
        without_gst_on_stt = self.value * (0.001 + 0.00015)
        self.assertLess(fees - without_gst_on_stt, self.value * 0.0002)

    def test_zero_value_costs_nothing(self):
        self.assertAlmostEqual(self.model.explicit_fees(0.0, BUY, self.day), 0.0)

    def test_full_service_brokerage_raises_cost(self):
        pricey = CostModel(
            schedules=(
                ChargeSchedule(effective_from=date(2020, 1, 1), brokerage_rate=0.003),
            )
        )
        self.assertGreater(
            pricey.explicit_fees(self.value, BUY, self.day),
            self.model.explicit_fees(self.value, BUY, self.day),
        )


class ImpactTests(unittest.TestCase):
    def setUp(self):
        self.model = CostModel(impact_coefficient=0.10, max_participation_rate=0.10)

    def test_participation_is_order_over_daily_turnover(self):
        self.assertAlmostEqual(
            self.model.participation_rate(500_000, 5_000_000), 0.10
        )

    def test_impact_grows_with_participation(self):
        small = self.model.impact_cost(100_000, 50_000_000)
        large = self.model.impact_cost(5_000_000, 50_000_000)
        self.assertGreater(large / 5_000_000, small / 100_000)

    def test_impact_is_sublinear_in_size(self):
        """Square-root shape: 4x the order is less than 4x the cost per rupee."""
        base_rate = self.model.impact_cost(1_000_000, 50_000_000) / 1_000_000
        quad_rate = self.model.impact_cost(4_000_000, 50_000_000) / 4_000_000
        self.assertAlmostEqual(quad_rate / base_rate, 2.0, places=6)

    def test_unknown_turnover_yields_none_not_zero(self):
        """Zero would be the most favourable assumption for illiquid names."""
        self.assertIsNone(self.model.impact_cost(100_000, None))
        self.assertIsNone(self.model.impact_cost(100_000, 0))

    def test_total_cost_is_none_when_impact_is_unmeasurable(self):
        breakdown = self.model.total_cost(100_000, BUY, date(2025, 1, 1), None)
        self.assertIsNone(breakdown["impact"])
        self.assertIsNone(breakdown["total"])
        self.assertIsNone(breakdown["cost_rate"])

    def test_slippage_is_charged_regardless_of_size(self):
        model = CostModel(half_spread_rate=0.001)
        self.assertAlmostEqual(model.slippage_cost(100_000), 100.0)

    def test_total_cost_sums_the_three_components(self):
        breakdown = self.model.total_cost(
            100_000, BUY, date(2025, 1, 1), 50_000_000
        )
        self.assertAlmostEqual(
            breakdown["total"],
            breakdown["explicit_fees"] + breakdown["slippage"] + breakdown["impact"],
            places=3,
        )

    def test_schedule_label_is_reported(self):
        breakdown = self.model.total_cost(
            100_000, BUY, date(2025, 1, 1), 50_000_000
        )
        self.assertIn("Oct-2024", breakdown["schedule"])


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.model = CostModel(max_participation_rate=0.10)

    def test_build_days_reflect_the_participation_limit(self):
        # 10% of 5,000,000 is 500,000 a day; a 1,000,000 order needs two days.
        self.assertAlmostEqual(self.model.build_days(1_000_000, 5_000_000), 2.0)

    def test_order_inside_the_limit_does_not_violate_capacity(self):
        self.assertFalse(self.model.violates_capacity(500_000, 5_000_000))

    def test_order_above_the_limit_violates_capacity(self):
        self.assertTrue(self.model.violates_capacity(600_000, 5_000_000))

    def test_unknown_turnover_counts_as_a_violation(self):
        """Unmeasurable liquidity must fail closed, not pass."""
        self.assertTrue(self.model.violates_capacity(100_000, None))

    def test_capacity_report_scales_with_portfolio_size(self):
        frame = pd.DataFrame({"Median_Turnover_INR": [5_000_000.0] * 20})
        report = capacity_report(
            self.model, frame, [1_000_000, 100_000_000], positions=20
        )
        small = report.iloc[0]
        large = report.iloc[1]
        self.assertLess(small["median_build_days"], large["median_build_days"])
        self.assertLess(
            small["capacity_violation_share"], large["capacity_violation_share"]
        )

    def test_capacity_report_handles_an_empty_frame(self):
        report = capacity_report(
            self.model, pd.DataFrame({"Median_Turnover_INR": []}), [1_000_000]
        )
        self.assertEqual(report["names"].iloc[0], 0)
        self.assertIsNone(report["median_build_days"].iloc[0])


class RoundTripTests(unittest.TestCase):
    def setUp(self):
        self.model = CostModel()

    def test_round_trip_charges_both_legs(self):
        one_leg = self.model.total_cost(
            100_000, BUY, date(2025, 1, 1), 50_000_000
        )["cost_rate"]
        both = round_trip_cost_rate(
            self.model, 100_000, date(2025, 1, 1), date(2025, 4, 1), 50_000_000
        )
        self.assertGreater(both, one_leg)

    def test_round_trip_is_none_when_turnover_is_unknown(self):
        self.assertIsNone(
            round_trip_cost_rate(
                self.model, 100_000, date(2025, 1, 1), date(2025, 4, 1), None
            )
        )

    def test_realistic_round_trip_is_a_few_tens_of_basis_points(self):
        rate = round_trip_cost_rate(
            self.model, 100_000, date(2025, 1, 1), date(2025, 4, 1), 50_000_000
        )
        self.assertGreater(rate, 0.002)
        self.assertLess(rate, 0.02)


class ApplyCostsTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame(
            {
                "Security_ID": ["SEC1", "SEC2"],
                "Entry_Session": ["2025-01-02", "2025-01-02"],
                "Exit_Session": ["2025-04-01", "2025-04-01"],
                "Return_Pct": [10.0, -5.0],
                "Median_Turnover_INR": [50_000_000.0, None],
            }
        )

    def test_net_return_is_below_gross(self):
        out = apply_costs(
            self.frame(),
            CostModel(),
            value_per_position=100_000,
            return_column="Return_Pct",
            entry_column="Entry_Session",
            exit_column="Exit_Session",
        )
        self.assertLess(out["Net_Return_Pct"].iloc[0], out["Return_Pct"].iloc[0])

    def test_gross_is_retained_alongside_net(self):
        out = apply_costs(
            self.frame(),
            CostModel(),
            value_per_position=100_000,
            return_column="Return_Pct",
            entry_column="Entry_Session",
            exit_column="Exit_Session",
        )
        self.assertIn("Return_Pct", out.columns)
        self.assertIn("Net_Return_Pct", out.columns)

    def test_unpriceable_position_has_no_net_return(self):
        out = apply_costs(
            self.frame(),
            CostModel(),
            value_per_position=100_000,
            return_column="Return_Pct",
            entry_column="Entry_Session",
            exit_column="Exit_Session",
        )
        # pandas coerces None to NaN inside a float column; either way the row
        # must carry no net return rather than an optimistic zero-cost one.
        self.assertTrue(pd.isna(out["Cost_Rate"].iloc[1]))
        self.assertTrue(pd.isna(out["Net_Return_Pct"].iloc[1]))

    def test_empty_frame_passes_through(self):
        self.assertTrue(
            apply_costs(
                pd.DataFrame(),
                CostModel(),
                value_per_position=1,
                return_column="Return_Pct",
                entry_column="Entry_Session",
                exit_column="Exit_Session",
            ).empty
        )


if __name__ == "__main__":
    unittest.main()
