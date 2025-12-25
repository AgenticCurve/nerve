./
├── docs/
│   └── prd/
│       └── [L: 850] openai-provider-support.md
├── examples/
│   ├── agents/
│   │   └── [L:  72] debate.py
│   ├── [L: 141] bash_node_example.py
│   ├── core_only/
│   │   ├── [L: 109] graph_execution.py
│   │   ├── [L:  63] multi_session.py
│   │   ├── [L:  58] simple_session.py
│   │   └── [L:  52] streaming.py
│   ├── [L: 312] debate.py
│   ├── [L: 237] demo_proxy.py
│   ├── [L: 587] dev_coach.py
│   ├── [L: 574] dev_coach_architecture.py
│   ├── [L: 657] dev_coach_consultants.py
│   ├── [L: 760] dev_coach_review.py
│   ├── [L: 844] dev_coach_review_prd.py
│   ├── embedded/
│   │   └── [L:  86] in_process.py
│   ├── [L: 180] graph_chain_test.py
│   ├── [L: 324] number_loop.py
│   ├── remote/
│   │   ├── [L:  54] client.py
│   │   └── [L:  40] server.py
│   └── [L:  32] sample_graph.py
├── [L:  24] Makefile
├── [L:  87] pyproject.toml
├── [L:   1] README.md
├── scripts/
│   ├── [L:  52] bump.py
│   ├── [L:  85] run_anthropic_passthrough.py
│   └── [L:  58] run_openai_proxy.py
├── src/
│   └── nerve/
│       ├── [L:  90] __init__.py
│       ├── [L:   3] __version__.py
│       ├── [L: 231] compose.py
│       ├── core/
│       │   ├── [L: 178] __init__.py
│       │   ├── nodes/
│       │   │   ├── [L: 143] __init__.py
│       │   │   ├── [L: 270] base.py
│       │   │   ├── [L: 271] bash.py
│       │   │   ├── [L: 190] budget.py
│       │   │   ├── [L: 101] cancellation.py
│       │   │   ├── [L: 202] context.py
│       │   │   ├── graph/
│       │   │   │   ├── [L:  21] __init__.py
│       │   │   │   ├── [L: 151] builder.py
│       │   │   │   ├── [L:  29] events.py
│       │   │   │   ├── [L: 712] graph.py
│       │   │   │   └── [L:  59] step.py
│       │   │   ├── [L: 562] history.py
│       │   │   ├── [L: 109] policies.py
│       │   │   ├── terminal/
│       │   │   │   ├── [L:  24] __init__.py
│       │   │   │   ├── [L: 472] claude_wezterm_node.py
│       │   │   │   ├── [L: 598] pty_node.py
│       │   │   │   └── [L: 684] wezterm_node.py
│       │   │   └── [L: 215] trace.py
│       │   ├── parsers/
│       │   │   ├── [L:  62] __init__.py
│       │   │   ├── [L:  56] base.py
│       │   │   ├── [L: 344] claude.py
│       │   │   ├── [L:  92] gemini.py
│       │   │   └── [L:  84] none.py
│       │   ├── patterns/
│       │   │   ├── [L:  21] __init__.py
│       │   │   ├── [L: 215] debate.py
│       │   │   └── [L: 299] dev_coach.py
│       │   ├── pty/
│       │   │   ├── [L:  60] __init__.py
│       │   │   ├── [L: 127] backend.py
│       │   │   ├── [L: 108] manager.py
│       │   │   ├── [L: 262] process.py
│       │   │   ├── [L: 276] pty_backend.py
│       │   │   └── [L: 520] wezterm_backend.py
│       │   ├── session/
│       │   │   ├── [L:  60] __init__.py
│       │   │   ├── [L: 125] manager.py
│       │   │   ├── [L: 257] persistence.py
│       │   │   └── [L: 289] session.py
│       │   ├── [L: 172] types.py
│       │   └── [L:  64] validation.py
│       ├── frontends/
│       │   ├── [L:  15] __init__.py
│       │   ├── cli/
│       │   │   ├── [L:  21] __init__.py
│       │   │   ├── [L: 243] extract.py
│       │   │   ├── [L: 182] main.py
│       │   │   ├── repl/
│       │   │   │   ├── [L:  34] __init__.py
│       │   │   │   ├── [L: 227] adapters.py
│       │   │   │   ├── [L:  38] cli.py
│       │   │   │   ├── commands/
│       │   │   │   ├── [L: 841] core.py
│       │   │   │   ├── [L:  83] display.py
│       │   │   │   ├── [L:  83] file_runner.py
│       │   │   │   └── [L:  15] state.py
│       │   │   ├── server/
│       │   │   │   ├── [L: 549] __init__.py
│       │   │   │   ├── [L: 447] graph.py
│       │   │   │   ├── [L: 790] node.py
│       │   │   │   └── [L: 292] session.py
│       │   │   ├── [L: 270] utils.py
│       │   │   └── [L: 209] wezterm.py
│       │   ├── mcp/
│       │   │   ├── [L:  30] __init__.py
│       │   │   └── [L: 213] server.py
│       │   └── sdk/
│       │       ├── [L:  27] __init__.py
│       │       └── [L: 372] client.py
│       ├── gateway/
│       │   ├── [L:  54] __init__.py
│       │   ├── [L: 357] anthropic_proxy.py
│       │   ├── clients/
│       │   │   ├── [L:  23] __init__.py
│       │   │   └── [L: 450] llm_client.py
│       │   ├── [L:  17] errors.py
│       │   ├── [L: 553] openai_proxy.py
│       │   ├── [L:  28] passthrough_proxy.py
│       │   ├── [L:  96] tracing.py
│       │   └── transforms/
│       │       ├── [L:  42] __init__.py
│       │       ├── [L: 429] anthropic.py
│       │       ├── [L: 360] openai.py
│       │       ├── [L:  98] tool_id_mapper.py
│       │       ├── [L: 115] types.py
│       │       └── [L: 197] validation.py
│       ├── server/
│       │   ├── [L:  64] __init__.py
│       │   ├── [L:1414] engine.py
│       │   ├── [L: 154] protocols.py
│       │   └── [L: 468] proxy_manager.py
│       └── transport/
│           ├── [L:  52] __init__.py
│           ├── [L: 372] http.py
│           ├── [L: 125] in_process.py
│           ├── [L:  67] protocol.py
│           ├── [L: 346] tcp_socket.py
│           └── [L: 353] unix_socket.py
└── tests/
    ├── [L:   1] __init__.py
    ├── cli/
    │   ├── [L:   0] __init__.py
    │   ├── [L:  76] test_graph_commands.py
    │   ├── [L:  76] test_node_commands.py
    │   └── [L:  70] test_session_commands.py
    ├── [L: 109] conftest.py
    ├── core/
    │   ├── [L:   1] __init__.py
    │   ├── fixtures/
    │   │   ├── [L:  29] pane_content.txt
    │   │   ├── [L:  36] sample_pane_02.txt
    │   │   ├── [L:  58] sample_pane_03.txt
    │   │   ├── [L: 144] sample_pane_04.txt
    │   │   └── [L: 103] sample_pane_05.txt
    │   ├── nodes/
    │   │   ├── [L:   1] __init__.py
    │   │   ├── [L: 209] test_base.py
    │   │   ├── [L: 206] test_bash.py
    │   │   ├── [L: 231] test_budget.py
    │   │   ├── [L: 126] test_cancellation.py
    │   │   ├── [L: 173] test_claude_wezterm_proxy.py
    │   │   ├── [L: 258] test_context.py
    │   │   ├── [L: 524] test_graph.py
    │   │   ├── [L: 121] test_policies.py
    │   │   ├── [L: 924] test_terminal.py
    │   │   ├── [L: 317] test_trace.py
    │   │   └── [L: 332] test_unified_api.py
    │   ├── session/
    │   │   ├── [L:   0] __init__.py
    │   │   └── [L: 103] test_session_factory.py
    │   ├── [L: 549] test_history.py
    │   ├── [L: 412] test_managers.py
    │   ├── [L: 502] test_parsers.py
    │   └── [L:  90] test_validation.py
    ├── frontends/
    │   ├── [L:   1] __init__.py
    │   └── sdk/
    │       ├── [L:   1] __init__.py
    │       └── [L: 206] test_client.py
    ├── gateway/
    │   ├── [L:   1] __init__.py
    │   ├── clients/
    │   │   ├── [L:   1] __init__.py
    │   │   └── [L: 340] test_llm_client.py
    │   ├── [L: 297] test_anthropic_proxy.py
    │   ├── [L: 318] test_openai_proxy.py
    │   ├── [L: 360] test_passthrough_proxy.py
    │   └── transforms/
    │       ├── [L:   1] __init__.py
    │       ├── [L: 357] test_anthropic.py
    │       ├── [L: 388] test_openai.py
    │       └── [L: 148] test_tool_id_mapper.py
    ├── server/
    │   ├── [L:   0] __init__.py
    │   ├── [L: 513] test_engine.py
    │   ├── [L: 269] test_engine_proxy.py
    │   ├── [L: 283] test_engine_sessions.py
    │   └── [L: 284] test_proxy_manager.py
    └── transport/
        └── [L:   1] __init__.py

44 directories, 162 files, 35,912 total lines
