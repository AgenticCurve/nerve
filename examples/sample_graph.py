"""Sample Graph definition for nerve server.

This file can be run with:
    nerve server graph run examples/sample_graph.py --server myproject

Or in dry-run mode:
    nerve server graph run examples/sample_graph.py --server myproject --dry-run
"""

# Graph definition using dict format (for server execution)
graph = {
    "steps": [
        {
            "id": "analyze",
            "node": "claude",  # Node name (will be created if needed)
            "prompt": "List the files in the current directory",
            "depends_on": [],
        },
        {
            "id": "summarize",
            "node": "claude",
            "prompt": "Summarize what you found: {analyze}",  # Can reference previous step output
            "depends_on": ["analyze"],
        },
        {
            "id": "suggest",
            "node": "claude",
            "prompt": "Based on the summary, suggest improvements",
            "depends_on": ["summarize"],
        },
    ]
}
