"""Sample DAG definition for nerve server.

This file can be run with:
    nerve server dag run examples/sample_dag.py

Or in dry-run mode:
    nerve server dag run examples/sample_dag.py --dry-run
"""

# DAG definition using dict format (for server execution)
dag = {
    "tasks": [
        {
            "id": "analyze",
            "session": "claude",  # Session name (will be created if needed)
            "prompt": "List the files in the current directory",
            "depends_on": [],
        },
        {
            "id": "summarize",
            "session": "claude",
            "prompt": "Summarize what you found: {analyze}",  # Can reference previous task output
            "depends_on": ["analyze"],
        },
        {
            "id": "suggest",
            "session": "claude",
            "prompt": "Based on the summary, suggest improvements",
            "depends_on": ["summarize"],
        },
    ]
}
