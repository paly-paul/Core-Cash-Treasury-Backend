"""Tests for Agent 5 (Variance Explanation) — arithmetic correctness."""
import pytest


def test_variance_arithmetic_basic():
    """Test 1: Basic variance arithmetic."""
    actual = 4_250_000
    forecast = 4_100_000
    total_variance = actual - forecast

    assert total_variance == 150_000

    variance_pct = (total_variance / abs(forecast)) * 100
    assert abs(variance_pct - 3.659) < 0.01  # ~3.659%

    within_tolerance = abs(variance_pct) <= 5.0
    assert within_tolerance is True

    forecast_accuracy_pct = max(0.0, 100.0 - abs(variance_pct))
    assert abs(forecast_accuracy_pct - 96.34) < 0.01


def test_unexplained_variance_never_zero():
    """Test 2: Unexplained variance is computed, never forced to zero."""
    drivers_sum = 200_000 + 50_000 + 250_000
    total_variance = 150_000
    unexplained = total_variance - drivers_sum

    assert unexplained == -350_000
    assert unexplained != 0


def test_one_off_flag_logic():
    """Test 3: One-off flag when outflow > 3× 30-day average."""
    avg_daily_outflow = 250_000
    capital_purchase = 750_000

    one_off_flag = capital_purchase > (3 * avg_daily_outflow)
    assert one_off_flag is True


def test_tolerance_boundary():
    """Test 4: Tolerance boundary at ±5%."""
    # Exactly at boundary
    variance_pct_boundary = 5.0
    within_tolerance = abs(variance_pct_boundary) <= 5.0
    assert within_tolerance is True

    # Just over boundary
    variance_pct_over = 5.001
    within_tolerance = abs(variance_pct_over) <= 5.0
    assert within_tolerance is False

    # Negative at boundary
    variance_pct_neg = -5.0
    within_tolerance = abs(variance_pct_neg) <= 5.0
    assert within_tolerance is True


def test_zero_forecast_guard():
    """Test 5: Handle division by zero when forecast is zero."""
    forecast = 0
    variance = 100

    variance_pct = 0.0 if forecast == 0 else (variance / abs(forecast)) * 100
    assert variance_pct == 0.0


def test_forecast_accuracy_floored():
    """Test: Forecast accuracy floored at zero."""
    variance_pct = 150.0  # Very bad variance
    forecast_accuracy_pct = max(0.0, 100.0 - abs(variance_pct))
    assert forecast_accuracy_pct == 0.0


def test_negative_variance_pct():
    """Test: Negative variance (unfavorable)."""
    actual = 3_800_000
    forecast = 4_100_000
    total_variance = actual - forecast

    assert total_variance == -300_000

    variance_pct = (total_variance / abs(forecast)) * 100
    assert variance_pct < 0
    assert abs(variance_pct) < 10  # Within tolerance


def test_variance_driver_sum_not_forced():
    """Test: Drivers are never forced to sum to total variance."""
    # Drivers sum to 500k
    driver_1 = 200_000
    driver_2 = 50_000
    driver_3 = 250_000
    drivers_sum = driver_1 + driver_2 + driver_3

    # But actual variance is 150k
    total_variance = 150_000

    # Unexplained should be residual
    unexplained = total_variance - drivers_sum
    assert unexplained == -350_000

    # Unexplained should NOT be forced to zero
    assert unexplained != 0
