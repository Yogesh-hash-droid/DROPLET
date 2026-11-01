"""
Phase 3 Tests: Safety Rule Engine and Water Quality Scoring Service.

All tests use an isolated in-memory SQLite database.
No MySQL connection required for these tests.
"""
import pytest
from app.services import safety_service, quality_service
from app.models.prediction import SafetyStatus
from app.models.system_config import SystemConfig
from datetime import datetime, timezone


def make_config(
    ph_min=6.5, ph_max=8.5,
    tds_max=500.0,
    turbidity_max=5.0,
    temperature_min=10.0,
    temperature_max=35.0
) -> SystemConfig:
    """Create a SystemConfig object with given thresholds (without DB)."""
    cfg = SystemConfig()
    cfg.id = 1
    cfg.ph_min = ph_min
    cfg.ph_max = ph_max
    cfg.tds_max = tds_max
    cfg.turbidity_max = turbidity_max
    cfg.temperature_min = temperature_min
    cfg.temperature_max = temperature_max
    cfg.updated_at = datetime.now(timezone.utc)
    return cfg


# ─────────────────────────────────────────────
# SAFETY RULE ENGINE TESTS
# ─────────────────────────────────────────────

class TestSafetyRuleEngine:

    def test_normal_water_is_safe(self):
        """Test 1: All parameters in configured ranges → SAFE, no warning."""
        cfg = make_config()
        result = safety_service.evaluate_safety(7.0, 250.0, 2.0, 25.0, cfg)
        assert result.status == SafetyStatus.SAFE
        assert result.warning_message is None
        assert result.violated_parameters == []

    def test_ph_below_min_warning(self):
        """Test 2a: pH moderately below min → WARNING."""
        cfg = make_config(ph_min=6.5)
        # pH = 6.1 → below 6.5 but above 6.5 - 0.5 = 6.0 → WARNING
        result = safety_service.evaluate_safety(6.1, 250.0, 2.0, 25.0, cfg)
        assert result.status == SafetyStatus.WARNING
        assert "pH" in result.violated_parameters
        assert result.warning_message is not None

    def test_ph_severely_below_min_unsafe(self):
        """Test 2b: pH severely below min → UNSAFE."""
        cfg = make_config(ph_min=6.5)
        # pH = 5.0 → below 6.5 - 0.5 = 6.0 → UNSAFE
        result = safety_service.evaluate_safety(5.0, 250.0, 2.0, 25.0, cfg)
        assert result.status == SafetyStatus.UNSAFE
        assert "pH" in result.violated_parameters
        assert "acidic" in result.warning_message.lower()

    def test_ph_above_max_warning(self):
        """Test 3a: pH moderately above max → WARNING."""
        cfg = make_config(ph_max=8.5)
        # pH = 8.8 → above 8.5 but below 8.5 + 0.5 = 9.0 → WARNING
        result = safety_service.evaluate_safety(8.8, 250.0, 2.0, 25.0, cfg)
        assert result.status == SafetyStatus.WARNING
        assert "pH" in result.violated_parameters

    def test_ph_severely_above_max_unsafe(self):
        """Test 3b: pH severely above max → UNSAFE."""
        cfg = make_config(ph_max=8.5)
        # pH = 11.0 → above 8.5 + 0.5 = 9.0 → UNSAFE
        result = safety_service.evaluate_safety(11.0, 250.0, 2.0, 25.0, cfg)
        assert result.status == SafetyStatus.UNSAFE
        assert "pH" in result.violated_parameters
        assert "alkaline" in result.warning_message.lower()

    def test_high_tds_warning(self):
        """Test 4a: TDS moderately above threshold → WARNING."""
        cfg = make_config(tds_max=500.0)
        # TDS = 600 → above 500 but below 500*1.5 = 750 → WARNING
        result = safety_service.evaluate_safety(7.0, 600.0, 2.0, 25.0, cfg)
        assert result.status == SafetyStatus.WARNING
        assert "TDS" in result.violated_parameters

    def test_high_tds_unsafe(self):
        """Test 4b: TDS severely above threshold → UNSAFE."""
        cfg = make_config(tds_max=500.0)
        # TDS = 900 → above 500*1.5 = 750 → UNSAFE
        result = safety_service.evaluate_safety(7.0, 900.0, 2.0, 25.0, cfg)
        assert result.status == SafetyStatus.UNSAFE
        assert "TDS" in result.violated_parameters

    def test_high_turbidity_warning(self):
        """Test 5a: Turbidity moderately above threshold → WARNING."""
        cfg = make_config(turbidity_max=5.0)
        # turbidity = 7.0 → above 5.0 but below 5.0*2.0 = 10.0 → WARNING
        result = safety_service.evaluate_safety(7.0, 250.0, 7.0, 25.0, cfg)
        assert result.status == SafetyStatus.WARNING
        assert "Turbidity" in result.violated_parameters

    def test_high_turbidity_unsafe(self):
        """Test 5b: Turbidity severely above threshold → UNSAFE."""
        cfg = make_config(turbidity_max=5.0)
        # turbidity = 25.0 → above 5.0*2.0 = 10.0 → UNSAFE
        result = safety_service.evaluate_safety(7.0, 250.0, 25.0, 25.0, cfg)
        assert result.status == SafetyStatus.UNSAFE
        assert "Turbidity" in result.violated_parameters

    def test_temperature_outside_range_warning(self):
        """Test 6a: Temperature slightly outside range → WARNING."""
        cfg = make_config(temperature_min=10.0, temperature_max=35.0)
        # temp = 37 → above 35 but below 35+5 = 40 → WARNING
        result = safety_service.evaluate_safety(7.0, 250.0, 2.0, 37.0, cfg)
        assert result.status == SafetyStatus.WARNING
        assert "Temperature" in result.violated_parameters

    def test_temperature_severely_outside_range_unsafe(self):
        """Test 6b: Temperature severely outside range → UNSAFE."""
        cfg = make_config(temperature_min=10.0, temperature_max=35.0)
        # temp = 50 → above 35+5 = 40 → UNSAFE
        result = safety_service.evaluate_safety(7.0, 250.0, 2.0, 50.0, cfg)
        assert result.status == SafetyStatus.UNSAFE
        assert "Temperature" in result.violated_parameters

    def test_multiple_violations(self):
        """Test 7: Multiple abnormal parameters all reported → worst status wins."""
        cfg = make_config()
        # pH severely bad + turbidity severely bad → UNSAFE with multiple violations
        result = safety_service.evaluate_safety(3.0, 250.0, 50.0, 25.0, cfg)
        assert result.status == SafetyStatus.UNSAFE
        assert "pH" in result.violated_parameters
        assert "Turbidity" in result.violated_parameters
        # Warning message mentions both
        assert "pH" in result.warning_message or "Turbidity" in result.warning_message

    def test_boundary_ph_at_min(self):
        """Test 8a: pH exactly at ph_min boundary → SAFE."""
        cfg = make_config(ph_min=6.5, ph_max=8.5)
        result = safety_service.evaluate_safety(6.5, 250.0, 2.0, 25.0, cfg)
        assert result.status == SafetyStatus.SAFE

    def test_boundary_ph_at_max(self):
        """Test 8b: pH exactly at ph_max boundary → SAFE."""
        cfg = make_config(ph_min=6.5, ph_max=8.5)
        result = safety_service.evaluate_safety(8.5, 250.0, 2.0, 25.0, cfg)
        assert result.status == SafetyStatus.SAFE

    def test_boundary_tds_at_max(self):
        """Test 8c: TDS exactly at tds_max boundary → SAFE."""
        cfg = make_config(tds_max=500.0)
        result = safety_service.evaluate_safety(7.0, 500.0, 2.0, 25.0, cfg)
        assert result.status == SafetyStatus.SAFE

    def test_boundary_turbidity_at_max(self):
        """Test 8d: Turbidity exactly at turbidity_max boundary → SAFE."""
        cfg = make_config(turbidity_max=5.0)
        result = safety_service.evaluate_safety(7.0, 250.0, 5.0, 25.0, cfg)
        assert result.status == SafetyStatus.SAFE

    def test_warning_does_not_override_unsafe(self):
        """Test 9: Mixed WARNING + UNSAFE → overall status is UNSAFE."""
        cfg = make_config()
        # pH mildly high (WARNING) + turbidity severely high (UNSAFE) → UNSAFE overall
        result = safety_service.evaluate_safety(8.8, 250.0, 50.0, 25.0, cfg)
        assert result.status == SafetyStatus.UNSAFE

    def test_safe_has_no_violations(self):
        """Test 9b: SAFE result has empty violated_parameters list."""
        cfg = make_config()
        result = safety_service.evaluate_safety(7.0, 200.0, 1.5, 22.0, cfg)
        assert result.status == SafetyStatus.SAFE
        assert len(result.violated_parameters) == 0
        assert result.warning_message is None


# ─────────────────────────────────────────────
# QUALITY SCORE TESTS
# ─────────────────────────────────────────────

class TestQualityScoreService:

    def test_excellent_values_high_score(self):
        """Test 1: Excellent parameters produce a score close to 100."""
        cfg = make_config()
        result = quality_service.calculate_water_quality_score(7.0, 150.0, 0.5, 22.0, cfg)
        assert result.overall_score >= 95.0, f"Expected >=95, got {result.overall_score}"

    def test_moderate_deviation_lowers_score(self):
        """Test 2: Moderate deviation produces score meaningfully below excellent."""
        cfg = make_config()
        result_good = quality_service.calculate_water_quality_score(7.0, 150.0, 0.5, 22.0, cfg)
        result_moderate = quality_service.calculate_water_quality_score(7.0, 480.0, 4.5, 22.0, cfg)
        assert result_moderate.overall_score < result_good.overall_score

    def test_severe_deviation_produces_low_score(self):
        """Test 3: Extreme parameter values produce a low score."""
        cfg = make_config()
        result = quality_service.calculate_water_quality_score(2.0, 1500.0, 80.0, 55.0, cfg)
        assert result.overall_score <= 30.0, f"Expected <=30, got {result.overall_score}"

    def test_score_never_below_zero(self):
        """Test 4: Score is always >= 0.0 even for extreme values."""
        cfg = make_config()
        result = quality_service.calculate_water_quality_score(0.0, 9999.0, 999.0, 99.0, cfg)
        assert result.overall_score >= 0.0

    def test_score_never_above_100(self):
        """Test 5: Score is always <= 100.0."""
        cfg = make_config()
        result = quality_service.calculate_water_quality_score(7.0, 50.0, 0.1, 22.0, cfg)
        assert result.overall_score <= 100.0

    def test_boundary_ph_at_min_scores_100_ph(self):
        """Test 6a: pH exactly at ph_min → pH sub-score is 100."""
        cfg = make_config(ph_min=6.5, ph_max=8.5)
        result = quality_service.calculate_water_quality_score(6.5, 150.0, 0.5, 22.0, cfg)
        assert result.sub_scores["ph"] == 100.0

    def test_boundary_ph_at_max_scores_100_ph(self):
        """Test 6b: pH exactly at ph_max → pH sub-score is 100."""
        cfg = make_config(ph_min=6.5, ph_max=8.5)
        result = quality_service.calculate_water_quality_score(8.5, 150.0, 0.5, 22.0, cfg)
        assert result.sub_scores["ph"] == 100.0

    def test_high_ph_lowers_score(self):
        """Test 7a: Abnormal pH reduces overall score."""
        cfg = make_config()
        result_normal = quality_service.calculate_water_quality_score(7.0, 150.0, 0.5, 22.0, cfg)
        result_high_ph = quality_service.calculate_water_quality_score(12.0, 150.0, 0.5, 22.0, cfg)
        assert result_high_ph.overall_score < result_normal.overall_score

    def test_high_tds_lowers_score(self):
        """Test 7b: Abnormal TDS reduces overall score."""
        cfg = make_config()
        result_normal = quality_service.calculate_water_quality_score(7.0, 150.0, 0.5, 22.0, cfg)
        result_high_tds = quality_service.calculate_water_quality_score(7.0, 1800.0, 0.5, 22.0, cfg)
        assert result_high_tds.overall_score < result_normal.overall_score

    def test_high_turbidity_lowers_score(self):
        """Test 7c: Abnormal turbidity reduces overall score."""
        cfg = make_config()
        result_normal = quality_service.calculate_water_quality_score(7.0, 150.0, 0.5, 22.0, cfg)
        result_high_turb = quality_service.calculate_water_quality_score(7.0, 150.0, 80.0, 22.0, cfg)
        assert result_high_turb.overall_score < result_normal.overall_score

    def test_sub_scores_present_and_bounded(self):
        """Test 8: All sub-scores are present and within [0, 100]."""
        cfg = make_config()
        result = quality_service.calculate_water_quality_score(7.0, 300.0, 3.0, 25.0, cfg)
        for key in ["ph", "tds", "turbidity", "temperature"]:
            assert key in result.sub_scores
            assert 0.0 <= result.sub_scores[key] <= 100.0

    def test_weights_sum_to_one(self):
        """Test 9: Weight sum equals 1.0."""
        cfg = make_config()
        result = quality_service.calculate_water_quality_score(7.0, 200.0, 1.5, 22.0, cfg)
        total_weight = sum(result.weights.values())
        assert abs(total_weight - 1.0) < 1e-9

    def test_score_is_deterministic(self):
        """Test 10: Identical inputs always produce identical scores."""
        cfg = make_config()
        r1 = quality_service.calculate_water_quality_score(7.0, 250.0, 2.5, 26.0, cfg)
        r2 = quality_service.calculate_water_quality_score(7.0, 250.0, 2.5, 26.0, cfg)
        assert r1.overall_score == r2.overall_score
