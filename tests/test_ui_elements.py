import pytest
from unittest.mock import MagicMock
from src.ui_elements import UIElement, UIElementProvider

def test_ui_element_center():
    el = UIElement(
        index=1,
        name="Test",
        control_type="Button",
        rect=(10, 20, 30, 40)
    )
    assert el.center == (20, 30)
    assert el.width == 20
    assert el.height == 20

def test_click_element_native():
    provider = UIElementProvider()
    mock_el = UIElement(
        index=1,
        name="Btn",
        control_type="Button",
        rect=(0,0,10,10),
        is_interactive=True
    )
    mock_control = MagicMock()
    mock_el._control = mock_control
    
    provider._elements_map[1] = mock_el
    
    # Test InvokePattern succeeds
    assert provider.click_element(1) is True
    mock_control.GetInvokePattern().Invoke.assert_called_once()
    
def test_click_element_fallback():
    provider = UIElementProvider()
    mock_el = UIElement(
        index=2,
        name="Btn2",
        control_type="Button",
        rect=(0,0,10,10),
        is_interactive=True
    )
    mock_control = MagicMock()
    # Make GetInvokePattern fail
    mock_control.GetInvokePattern.side_effect = Exception("No InvokePattern")
    mock_control.GetTogglePattern.side_effect = Exception("No TogglePattern")
    mock_control.GetSelectionItemPattern.side_effect = Exception("No SelectionItemPattern")
    
    mock_el._control = mock_control
    provider._elements_map[2] = mock_el
    
    assert provider.click_element(2) is True
    mock_control.Click.assert_called_once_with(simulateMove=False)
