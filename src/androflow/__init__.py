"""AndroFlow: YAML-driven Android UI testing."""

from .android import AndroidDriver, AndroidError
from .reports import generate_html_report, generate_junit_xml
from .runner import FlowError, FlowResult, FlowRunner, StepResult

__version__ = "0.1.0"
__all__ = [
    "AndroidDriver",
    "AndroidError",
    "FlowError",
    "FlowResult",
    "FlowRunner",
    "StepResult",
    "generate_html_report",
    "generate_junit_xml",
]
