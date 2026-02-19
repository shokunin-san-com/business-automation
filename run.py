"""
Script dispatcher for Cloud Run Jobs.

Reads the SCRIPT_NAME environment variable and runs the corresponding script.
Usage:
    SCRIPT_NAME=0_idea_generator python run.py
"""

import os
import sys
import importlib

SCRIPT_MAP = {
    "A_market_research": "scripts.A_market_research",
    "B_market_selection": "scripts.B_market_selection",
    "C_competitor_analysis": "scripts.C_competitor_analysis",
    "0_idea_generator": "scripts.0_idea_generator",
    "1_lp_generator": "scripts.1_lp_generator",
    "2_sns_poster": "scripts.2_sns_poster",
    "3_form_sales": "scripts.3_form_sales",
    "4_analytics_reporter": "scripts.4_analytics_reporter",
    "5_slack_reporter": "scripts.5_slack_reporter",
    "6_ads_monitor": "scripts.6_ads_monitor",
    "7_learning_engine": "scripts.7_learning_engine",
}


def main():
    script_name = os.getenv("SCRIPT_NAME", "")
    if not script_name:
        print("ERROR: SCRIPT_NAME environment variable not set")
        print(f"Available scripts: {', '.join(SCRIPT_MAP.keys())}")
        sys.exit(1)

    if script_name not in SCRIPT_MAP:
        print(f"ERROR: Unknown script: {script_name}")
        print(f"Available scripts: {', '.join(SCRIPT_MAP.keys())}")
        sys.exit(1)

    module_path = SCRIPT_MAP[script_name]

    # For modules with numeric prefixes, use importlib
    # Also add scripts/ to path for relative imports
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))
    sys.path.insert(0, os.path.dirname(__file__))

    # Import and run
    # Scripts use filenames like "0_idea_generator.py", import as module
    actual_file = f"scripts/{script_name}.py"
    spec = importlib.util.spec_from_file_location(script_name, actual_file)
    if spec is None or spec.loader is None:
        print(f"ERROR: Could not load module from {actual_file}")
        sys.exit(1)

    module = importlib.util.module_from_spec(spec)
    sys.modules[script_name] = module
    spec.loader.exec_module(module)

    if hasattr(module, "main"):
        module.main()
    else:
        print(f"WARNING: {script_name} has no main() function")


if __name__ == "__main__":
    main()
