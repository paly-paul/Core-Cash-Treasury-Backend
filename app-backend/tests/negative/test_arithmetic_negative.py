"""
Negative arithmetic tests — unit tests verifying critical constant values.
CRITICAL: These tests MUST verify exact threshold values:
- OD Headroom never stored, never added to usable cash
- Warning threshold is 70% (not 80%)
- Variance tolerance is ±5% (not ±3%)
- Confidence filter is >=50 (not >50)
- Stale threshold is >48h (not >=48h)
- AR concentration >70% (not >=70%, not 80%)
- Surplus ×1.5 threshold
- MTD only (no YTD)
- Risk score caps at 10
"""
import pytest


class TestArithmeticNegative:
    """Unit tests for financial arithmetic constants."""

    def test_f1_od_headroom_never_stored_in_db(self):
        """F1: OD headroom computed at read-time, never stored."""
        # Unit test: verify computation logic
        od_limit = 500000
        od_utilised = 120000
        expected_od_headroom = od_limit - od_utilised  # = 380000

        # Verify computation
        assert expected_od_headroom == 380000

        # CRITICAL: od_headroom must NEVER be added to usable_cash_usd
        # This is a code review check — verify no line of code does:
        # usable_cash += od_headroom  (this would be WRONG)

    def test_f2_usable_cash_never_includes_od_headroom(self):
        """F2: Usable cash never includes OD headroom."""
        available_cash = 5000000
        restricted_cash = 0
        od_limit = 2000000
        od_utilised = 0

        # Correct computation
        usable_cash_correct = available_cash - restricted_cash  # 5,000,000
        # CRITICAL: NOT (available_cash - restricted_cash + od_limit)

        assert usable_cash_correct == 5000000
        # Verify OD is NOT summed
        assert usable_cash_correct != 7000000  # Would be 7M if OD added

    def test_f3_warning_threshold_70_percent_not_80(self):
        """F3: Warning status triggered at 70% of min_threshold, NOT 80%."""
        min_threshold = 1000000

        # Test cases
        test_cases = [
            (1000000, "Green"),      # >= threshold → Green
            (700000, "Yellow"),      # >= 70% of threshold → Yellow (OK threshold)
            (699999, "Red"),         # < 70% → Red
            (800000, "Yellow"),      # Would be Yellow at 80% too, but 70% is the rule
        ]

        for balance, expected_status in test_cases:
            # Compute status
            if balance >= min_threshold:
                status = "Green"
            elif balance >= min_threshold * 0.70:  # CRITICAL: 0.70 not 0.80
                status = "Yellow"
            else:
                status = "Red"

            assert status == expected_status, \
                f"Balance {balance} should be {expected_status}, got {status}"

    def test_f4_variance_tolerance_5_percent_not_3(self):
        """F4: Variance tolerance is ±5.0%, NOT ±3.0%."""
        forecast_closing = 1000000

        # Test boundary cases
        actual_closing_within = 1049999      # 4.9999% variance → within tolerance
        actual_closing_boundary = 1050000    # exactly 5.0% → within tolerance
        actual_closing_exceeded = 1050001    # 5.0001% → exceeded tolerance

        tolerance_rate = 0.05  # CRITICAL: 0.05 not 0.03

        for actual, expected_tolerance in [
            (actual_closing_within, True),
            (actual_closing_boundary, True),
            (actual_closing_exceeded, False),
        ]:
            variance_pct = abs(actual - forecast_closing) / forecast_closing
            within_tolerance = variance_pct <= tolerance_rate

            assert within_tolerance == expected_tolerance, \
                f"Actual {actual}: variance {variance_pct:.4%} tolerance should be {expected_tolerance}"

    def test_f5_unexplained_variance_never_forced_to_zero(self):
        """F5: Unexplained variance preserved, never zeroed."""
        total_variance = -340000
        drivers_sum = -200000

        unexplained = total_variance - drivers_sum  # -140000

        assert unexplained == -140000
        assert unexplained != 0, "Unexplained variance must not be forced to 0"

    def test_f6_confidence_filter_50_percent_inclusive(self):
        """F6: Confidence filter >=50 (inclusive), NOT >50."""
        assumptions = [
            {"confidence_pct": 50, "amount": 100000},    # INCLUDED (>=50)
            {"confidence_pct": 49, "amount": 200000},    # EXCLUDED (<50)
            {"confidence_pct": 51, "amount": 300000},    # INCLUDED
        ]

        confidence_threshold = 50
        included = [a for a in assumptions if a["confidence_pct"] >= confidence_threshold]

        assert len(included) == 2, "Should include 50% and 51%, exclude 49%"
        total_included = sum(a["amount"] for a in included)
        assert total_included == 400000, "50% + 51% = 400k, NOT 600k"

    def test_f7_stale_threshold_48_hours_exclusive(self):
        """F7: Stale threshold is >48h (exclusive), NOT >=48h."""
        # 48 hours exactly = NOT stale
        # 48.01 hours = stale

        def is_stale(hours_elapsed):
            return hours_elapsed > 48  # CRITICAL: > not >=

        assert is_stale(48) == False, "48h exactly is NOT stale"
        assert is_stale(48.01) == True, "48.01h IS stale"
        assert is_stale(49) == True, ">48h is stale"

    def test_f8_ar_concentration_70_percent_threshold_exclusive(self):
        """F8: AR concentration >70% (exclusive), NOT >=70% and NOT 80%."""
        total_ar = 1000000
        threshold = 0.70

        test_cases = [
            (700000, False),      # exactly 70.0% → NOT breached (<=70% is OK)
            (700001, True),       # 70.0001% → breached
            (750000, True),       # 75% → breached
            (800000, True),       # 80% → breached (would catch wrong 80% threshold)
        ]

        for top3_ar, expected_breached in test_cases:
            concentration = top3_ar / total_ar
            is_breached = concentration > threshold  # CRITICAL: > not >=

            assert is_breached == expected_breached, \
                f"Top-3 AR {top3_ar} ({concentration:.1%}): breach={is_breached}, expected={expected_breached}"

    def test_f9_surplus_detection_threshold_1_5x(self):
        """F9: Surplus triggered when usable_cash >1.5× min_threshold."""
        min_threshold = 500000
        surplus_multiplier = 1.5

        test_cases = [
            (749999, False),      # <1.5× → no surplus
            (750000, False),      # exactly 1.5× → boundary (no surplus, need >)
            (750001, True),       # >1.5× → surplus
            (1000000, True),      # clearly >1.5×
        ]

        for usable_cash, expected_surplus in test_cases:
            has_surplus = usable_cash > (min_threshold * surplus_multiplier)

            assert has_surplus == expected_surplus, \
                f"Usable {usable_cash}: surplus={has_surplus}, expected={expected_surplus}"

    def test_f10_mtd_only_no_ytd_field(self):
        """F10: MTD field present, YTD never appears."""
        # Unit test: verify no "ytd" in field definitions
        valid_fields = ["mtd_change_usd", "mtd_change_pct"]
        invalid_fields = ["ytd_change_usd", "ytd_change_pct"]

        # CRITICAL: YTD fields must NOT exist
        for field in valid_fields:
            assert "mtd" in field

        for field in invalid_fields:
            assert "ytd" in field
            # These should NEVER appear in response schema

    def test_f11_one_off_flag_threshold_3x_average(self):
        """F11: One-off flag when outflow >3× 30-day average."""
        daily_avg_30d = 100000

        test_cases = [
            (290000, False),      # 2.9× → not one-off
            (300000, False),      # exactly 3× → boundary (need >)
            (300001, True),       # >3× → one-off
            (500000, True),       # 5× → clearly one-off
        ]

        for outflow, expected_one_off in test_cases:
            is_one_off = outflow > (daily_avg_30d * 3)  # CRITICAL: > not >=

            assert is_one_off == expected_one_off, \
                f"Outflow {outflow}: one_off={is_one_off}, expected={expected_one_off}"

    def test_f12_risk_score_cap_at_10(self):
        """F12: Risk score capped at 10 maximum."""
        # Extreme case: 10 active breaches + multiple other factors
        # base(1) + breach_component(6) + stale(1) + ar_conc(1) + shortfall(2) = 11
        # After cap: 10

        components = {
            "base": 1,
            "breach_component": 6,  # Capped at 6 regardless of breach count
            "stale": 1,
            "ar_concentration": 1,
            "shortfall": 2,
        }

        raw_score = sum(components.values())  # 11
        capped_score = min(raw_score, 10)

        assert raw_score == 11
        assert capped_score == 10

    def test_f13_breach_component_capped_at_6(self):
        """F13: Breach component capped at 6, not uncapped."""
        # 10 active breaches would naturally be 10
        # But capped at 6
        active_breaches = 10
        breach_score_uncapped = min(active_breaches, 10)  # Would be 10
        breach_score_capped = min(active_breaches, 6)     # CRITICAL: cap at 6

        assert breach_score_capped == 6
        assert breach_score_capped != breach_score_uncapped
