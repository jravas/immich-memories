#!/usr/bin/env python3
"""
Integration tests for Phase 2 LLM Enricher functionality.
Tests config loading, models, queue API endpoints, and metrics.
"""

import os
import tempfile
import yaml
from pathlib import Path

from memories_app.config import load_config


def test_config_loading():
    """Test that Phase 2 configuration loads and env vars resolve."""
    print("Testing Phase 2 configuration loading...")

    test_config = {
        "immich": {"base_url": "http://test:2283", "api_key": "test-key"},
        "ntfy": {"base_url": "http://test", "topic": "test"},
        "enricher": {
            "enabled": True,
            "poll_interval_minutes": 15,
            "nas_url": "http://test:8080",
            "ollama_url": "http://localhost:11434",
            "vision_model": "qwen2.5vl:7b",
            "fallback_model": "moondream2",
            "timeout_seconds": 30,
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(test_config, f)
        temp_config_path = f.name

    try:
        config = load_config(temp_config_path)

        assert config.enricher.enabled is True
        assert config.enricher.poll_interval_minutes == 15
        assert config.enricher.nas_url == "http://test:8080"
        assert config.enricher.ollama_url == "http://localhost:11434"
        assert config.enricher.vision_model == "qwen2.5vl:7b"
        assert config.enricher.fallback_model == "moondream2"
        assert config.enricher.timeout_seconds == 30

        print("✓ Phase 2 configuration loading works correctly")
        return True

    except Exception as e:
        print(f"✗ Configuration loading failed: {e}")
        return False
    finally:
        Path(temp_config_path).unlink()


def test_enricher_secret_resolution():
    """Test that ENRICHER_SECRET is resolved from the environment."""
    print("Testing ENRICHER_SECRET env resolution...")

    test_config = {
        "immich": {"base_url": "http://test:2283", "api_key": "test-key"},
        "ntfy": {"base_url": "http://test", "topic": "test"},
        "enricher": {"shared_secret": "${ENRICHER_SECRET}"},
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(test_config, f)
        temp_config_path = f.name

    try:
        os.environ["ENRICHER_SECRET"] = "my-test-secret"
        config = load_config(temp_config_path)
        assert config.enricher.shared_secret == "my-test-secret", (
            f"Expected 'my-test-secret', got '{config.enricher.shared_secret}'"
        )

        print("✓ ENRICHER_SECRET resolves correctly from env")
        return True

    except Exception as e:
        print(f"✗ ENRICHER_SECRET resolution failed: {e}")
        return False
    finally:
        Path(temp_config_path).unlink()
        os.environ.pop("ENRICHER_SECRET", None)


def test_enrichment_response_model():
    """Test the EnrichmentResponse Pydantic model."""
    print("Testing EnrichmentResponse model...")

    try:
        from enricher import EnrichmentResponse

        response = EnrichmentResponse(score=8, best_index=2, caption="You were exploring the old city")
        assert response.score == 8
        assert response.best_index == 2
        assert response.caption == "You were exploring the old city"

        parsed = EnrichmentResponse.model_validate_json(
            '{"score": 7, "best_index": 0, "caption": "A peaceful morning"}'
        )
        assert parsed.score == 7
        assert parsed.best_index == 0

        print("✓ EnrichmentResponse model works correctly")
        return True

    except Exception as e:
        print(f"✗ EnrichmentResponse model failed: {e}")
        return False


def test_cycle_metrics():
    """Test CycleMetrics accumulation and summary."""
    print("Testing CycleMetrics...")

    try:
        from enricher import CycleMetrics

        m = CycleMetrics()
        m.record("enriched", 2.5)
        m.record("skipped", 1.0)
        m.record("failed", 0.5)

        assert m.attempted == 3
        assert m.enriched == 1
        assert m.skipped == 1
        assert m.failed == 1
        assert abs(sum(m.latencies) / len(m.latencies) - 4.0 / 3) < 0.01

        print("✓ CycleMetrics works correctly")
        return True

    except Exception as e:
        print(f"✗ CycleMetrics failed: {e}")
        return False


def test_hide_server_endpoints():
    """Test that hide_server has all Phase 2 endpoints."""
    print("Testing hide_server Phase 2 endpoints...")

    try:
        import hide_server

        routes = [route.path for route in hide_server.app.routes]

        assert "/hide" in routes
        assert "/queue/pending" in routes
        assert "/queue/update" in routes

        print("✓ hide_server Phase 2 endpoints are available")
        return True

    except Exception as e:
        print(f"✗ hide_server endpoint test failed: {e}")
        return False


def main():
    """Run all Phase 2 integration tests."""
    print("Running Phase 2 integration tests...\n")

    tests = [
        test_config_loading,
        test_enricher_secret_resolution,
        test_enrichment_response_model,
        test_cycle_metrics,
        test_hide_server_endpoints,
    ]

    passed = sum(1 for t in tests if (print() or True) and t())
    total = len(tests)

    print(f"\nPhase 2 Integration Tests: {passed}/{total} passed")
    return passed == total


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
