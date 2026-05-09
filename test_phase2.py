#!/usr/bin/env python3
"""
Simple integration test for Phase 2 LLM Enricher functionality.
Tests the queue API endpoints and enricher configuration loading.
"""

import json
import tempfile
from pathlib import Path

from memories_app.config import load_config


def test_config_loading():
    """Test that Phase 2 configuration loads correctly."""
    print("Testing Phase 2 configuration loading...")
    
    # Create a test config with Phase 2 settings
    test_config = {
        "immich": {
            "base_url": "http://test:2283",
            "api_key": "test-key"
        },
        "ntfy": {
            "base_url": "http://test",
            "topic": "test"
        },
        "enricher": {
            "enabled": True,
            "poll_interval_minutes": 15,
            "nas_url": "http://test:8080",
            "vision_model": "qwen2.5vl:7b",
            "fallback_model": "moondream2",
            "timeout_seconds": 30
        }
    }
    
    # Write test config to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        import yaml
        yaml.dump(test_config, f)
        temp_config_path = f.name
    
    try:
        # Load and validate config
        config = load_config(temp_config_path)
        
        # Check enricher config
        assert config.enricher.enabled == True
        assert config.enricher.poll_interval_minutes == 15
        assert config.enricher.nas_url == "http://test:8080"
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


def test_enrichment_response_model():
    """Test the EnrichmentResponse Pydantic model."""
    print("Testing EnrichmentResponse model...")
    
    try:
        from enricher import EnrichmentResponse
        
        # Test valid response
        response = EnrichmentResponse(
            score=8,
            best_index=2,
            caption="You were exploring the old city"
        )
        
        assert response.score == 8
        assert response.best_index == 2
        assert response.caption == "You were exploring the old city"
        
        # Test JSON validation
        json_str = '{"score": 7, "best_index": 0, "caption": "A peaceful morning"}'
        parsed = EnrichmentResponse.model_validate_json(json_str)
        
        assert parsed.score == 7
        assert parsed.best_index == 0
        assert parsed.caption == "A peaceful morning"
        
        print("✓ EnrichmentResponse model works correctly")
        return True
        
    except Exception as e:
        print(f"✗ EnrichmentResponse model failed: {e}")
        return False


def test_hide_server_endpoints():
    """Test that hide_server can be imported and has the new endpoints."""
    print("Testing hide_server Phase 2 endpoints...")
    
    try:
        # Import should work
        import hide_server
        
        # Check that the app has the new endpoints
        from fastapi.routing import APIRoute
        
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
        test_enrichment_response_model,
        test_hide_server_endpoints,
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print(f"Phase 2 Integration Tests: {passed}/{total} passed")
    
    if passed == total:
        print("🎉 All Phase 2 integration tests passed!")
        return True
    else:
        print("❌ Some Phase 2 tests failed")
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
