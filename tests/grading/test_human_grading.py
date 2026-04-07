import sys
from unittest.mock import MagicMock, patch

def test_get_human_grading_interface_singleton():
    """Test that get_human_grading_interface returns a singleton instance."""
    # Mock missing dependencies within the scope of this test only
    with patch.dict('sys.modules', {
        'pydantic': MagicMock(),
        'grading.grading_models': MagicMock(),
        'grading.grading_storage': MagicMock(),
    }):
        # Import the module under test inside the patched context
        import grading.human_grading as hg

        # Reset singleton state
        hg._human_grading = None

        # Mock HumanGradingInterface to avoid actual initialization (which might fail due to mocks)
        with patch('grading.human_grading.HumanGradingInterface') as mock_class:
            # Setup the mock instance
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance

            try:
                interface1 = hg.get_human_grading_interface()
                interface2 = hg.get_human_grading_interface()

                # Assertions
                assert interface1 is interface2
                assert interface1 is mock_instance
                assert mock_class.call_count == 1
            finally:
                # Cleanup singleton state
                hg._human_grading = None
