./
├── examples/
│   ├── agents/
│   │   ├── [L:  11] __init__.py
│   │   ├── debate/
│   │   │   ├── [L:   1] __init__.py
│   │   │   ├── [L:  76] main.py
│   │   │   └── [L:  23] prompts.py
│   │   ├── dev_coach_architecture/
│   │   │   ├── [L:   1] __init__.py
│   │   │   ├── [L: 460] main.py
│   │   │   └── [L: 135] prompts.py
│   │   ├── dev_coach_base/
│   │   │   ├── [L:   1] __init__.py
│   │   │   ├── [L: 458] main.py
│   │   │   └── [L: 150] prompts.py
│   │   ├── dev_coach_consultants/
│   │   │   ├── [L:   1] __init__.py
│   │   │   ├── [L: 449] main.py
│   │   │   └── [L: 238] prompts.py
│   │   ├── dev_coach_review/
│   │   │   ├── [L:   1] __init__.py
│   │   │   ├── [L: 541] main.py
│   │   │   └── [L: 223] prompts.py
│   │   └── dev_coach_review_prd/
│   │       ├── [L:   1] __init__.py
│   │       ├── [L: 636] main.py
│   │       └── [L: 234] prompts.py
│   ├── [L: 142] bash_node_example.py
│   ├── core_only/
│   │   ├── [L: 110] graph_execution.py
│   │   ├── [L:  63] multi_session.py
│   │   ├── [L:  60] simple_session.py
│   │   └── [L:  52] streaming.py
│   ├── [L: 312] debate.py
│   ├── [L: 237] demo_proxy.py
│   ├── embedded/
│   │   └── [L:  86] in_process.py
│   ├── [L: 180] graph_chain_test.py
│   ├── [L: 139] GRAPH_COMMANDER_TEST.md
│   ├── [L: 328] number_loop.py
│   ├── remote/
│   │   ├── [L:  54] client.py
│   │   └── [L:  40] server.py
│   ├── [L:  32] sample_graph.py
│   ├── [L: 108] test_graph_in_commander.py
│   ├── [L:  92] test_workspace.py
│   ├── workflows/
│   │   ├── [L:   7] __init__.py
│   │   ├── [L: 333] basic_workflow.py
│   │   ├── [L: 316] code_review_workflow.py
│   │   ├── [L: 199] multi_step_demo.py
│   │   └── [L:  58] simple_loadable.py
│   ├── workspace/
│   │   └── driver_navigator/
│   │       ├── [L: 125] main.py
│   │       ├── [L: 145] workflow_bug_hunter.py
│   │       └── [L: 151] workflow_verify_refactoring.py
│   └── [L: 107] workspace_example.py
├── features/
│   ├── glm/
│   │   ├── [L: 214] glm_chat_node.py
│   │   ├── [L: 133] glm_node.py
│   │   └── [L: 414] tool_calling.py
│   ├── openrouter/
│   │   ├── [L: 223] openrouter_chat_node.py
│   │   ├── [L: 162] openrouter_node.py
│   │   └── [L: 414] tool_calling.py
│   └── parser/
│       └── claude/
│           └── samples/
│               ├── [L:  48] sample_pane_01.txt
│               ├── [L: 432] sample_pane_02.txt
│               ├── [L: 379] sample_pane_03.txt
│               └── [L:  57] sample_pane_04.txt
├── [L:  90] Makefile
├── prompts/
│   └── refactoring/
│       ├── [L: 220] bug-hunter.md
│       └── [L: 167] verify-refactoring.md
├── [L:  93] pyproject.toml
├── [L:  30] README.md
├── scripts/
│   ├── [L:  52] bump.py
│   ├── proxy/
│   │   ├── [L:1200] browse_conversation.py
│   │   ├── [L:1167] browse_file_operations.py
│   │   ├── [L: 510] dump_request.py
│   │   ├── shared/
│   │   │   ├── [L:  44] __init__.py
│   │   │   ├── [L:  23] cli.py
│   │   │   ├── [L:  16] colors.py
│   │   │   ├── [L:  74] formatting.py
│   │   │   ├── [L:  67] models.py
│   │   │   ├── [L: 149] parsing.py
│   │   │   └── [L:  98] themes.py
│   │   └── [L:1199] summarize_session.py
│   ├── [L:  85] run_anthropic_passthrough.py
│   └── [L:  58] run_openai_proxy.py
├── src/
│   └── nerve/
│       ├── [L:  90] __init__.py
│       ├── [L:   3] __version__.py
│       ├── [L: 231] compose.py
│       ├── core/
│       │   ├── [L: 215] __init__.py
│       │   ├── [L: 242] logging_config.py
│       │   ├── nodes/
│       │   │   ├── [L: 160] __init__.py
│       │   │   ├── [L: 377] base.py
│       │   │   ├── [L: 468] bash.py
│       │   │   ├── [L: 190] budget.py
│       │   │   ├── [L: 101] cancellation.py
│       │   │   ├── [L: 256] context.py
│       │   │   ├── graph/
│       │   │   │   ├── [L:  21] __init__.py
│       │   │   │   ├── [L: 151] builder.py
│       │   │   │   ├── [L:  29] events.py
│       │   │   │   ├── [L:1056] graph.py
│       │   │   │   └── [L:  59] step.py
│       │   │   ├── [L: 562] history.py
│       │   │   ├── [L: 165] identity.py
│       │   │   ├── llm/
│       │   │   │   ├── [L:  70] __init__.py
│       │   │   │   ├── [L: 756] base.py
│       │   │   │   ├── [L: 660] chat.py
│       │   │   │   ├── [L: 141] glm.py
│       │   │   │   ├── [L: 105] openrouter.py
│       │   │   │   └── [L: 526] suggestion.py
│       │   │   ├── [L: 109] policies.py
│       │   │   ├── [L: 302] run_logging.py
│       │   │   ├── [L: 742] session_logging.py
│       │   │   ├── terminal/
│       │   │   │   ├── [L:  24] __init__.py
│       │   │   │   ├── [L: 879] claude_wezterm_node.py
│       │   │   │   ├── [L: 779] pty_node.py
│       │   │   │   └── [L: 872] wezterm_node.py
│       │   │   ├── [L: 340] tools.py
│       │   │   └── [L: 215] trace.py
│       │   ├── parsers/
│       │   │   ├── [L:  62] __init__.py
│       │   │   ├── [L:  59] base.py
│       │   │   ├── [L: 373] claude.py
│       │   │   ├── [L: 104] gemini.py
│       │   │   └── [L:  96] none.py
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
│       │   │   └── [L: 528] wezterm_backend.py
│       │   ├── session/
│       │   │   ├── [L:  60] __init__.py
│       │   │   ├── [L: 137] manager.py
│       │   │   ├── [L: 257] persistence.py
│       │   │   └── [L: 539] session.py
│       │   ├── [L: 172] types.py
│       │   ├── [L:  64] validation.py
│       │   └── workflow/
│       │       ├── [L:  48] __init__.py
│       │       ├── [L: 453] context.py
│       │       ├── [L:  74] events.py
│       │       ├── [L: 427] run.py
│       │       └── [L: 134] workflow.py
│       ├── frontends/
│       │   ├── [L:  15] __init__.py
│       │   ├── cli/
│       │   │   ├── [L:  21] __init__.py
│       │   │   ├── [L: 347] extract.py
│       │   │   ├── [L: 267] main.py
│       │   │   ├── [L: 193] output.py
│       │   │   ├── repl/
│       │   │   │   ├── [L:  34] __init__.py
│       │   │   │   ├── [L: 918] adapters.py
│       │   │   │   ├── [L: 139] cleanup.py
│       │   │   │   ├── [L:  38] cli.py
│       │   │   │   ├── commands/
│       │   │   │   ├── [L: 342] core.py
│       │   │   │   ├── [L:  83] display.py
│       │   │   │   ├── [L:  85] file_runner.py
│       │   │   │   ├── [L: 486] registry.py
│       │   │   │   └── [L:  15] state.py
│       │   │   ├── server/
│       │   │   │   ├── [L: 548] __init__.py
│       │   │   │   ├── [L: 214] graph.py
│       │   │   │   ├── [L:1048] node.py
│       │   │   │   ├── [L: 206] session.py
│       │   │   │   └── [L: 193] workflow.py
│       │   │   ├── [L: 363] utils.py
│       │   │   └── [L: 209] wezterm.py
│       │   ├── mcp/
│       │   │   ├── [L:  30] __init__.py
│       │   │   └── [L: 213] server.py
│       │   ├── sdk/
│       │   │   ├── [L:  27] __init__.py
│       │   │   └── [L: 417] client.py
│       │   └── tui/
│       │       ├── [L:   8] __init__.py
│       │       └── commander/
│       │           ├── [L:  33] __init__.py
│       │           ├── [L: 384] blocks.py
│       │           ├── [L:  65] clipboard.py
│       │           ├── [L: 616] commander.py
│       │           ├── [L: 596] commands.py
│       │           ├── [L: 167] entity_manager.py
│       │           ├── [L: 481] executor.py
│       │           ├── [L: 481] input_dispatcher.py
│       │           ├── [L: 377] loop.py
│       │           ├── [L: 682] monitor.py
│       │           ├── [L: 311] persistence.py
│       │           ├── [L: 533] rendering.py
│       │           ├── [L:  65] result_handler.py
│       │           ├── [L: 128] status_indicators.py
│       │           ├── [L: 126] suggestion_history.py
│       │           ├── [L: 366] suggestion_manager.py
│       │           ├── [L: 175] suggestion_picker.py
│       │           ├── [L: 225] suggestion_record.py
│       │           ├── [L: 154] text_builder.py
│       │           ├── [L: 195] themes.py
│       │           ├── [L: 663] variables.py
│       │           ├── [L: 178] workflow_events.py
│       │           ├── [L: 589] workflow_runner.py
│       │           ├── [L:  42] workflow_state.py
│       │           ├── [L: 205] workflow_tracker.py
│       │           └── [L: 441] workflow_ui.py
│       ├── gateway/
│       │   ├── [L:  54] __init__.py
│       │   ├── [L: 639] anthropic_proxy.py
│       │   ├── clients/
│       │   │   ├── [L:  23] __init__.py
│       │   │   └── [L: 450] llm_client.py
│       │   ├── [L:  17] errors.py
│       │   ├── [L: 553] openai_proxy.py
│       │   ├── [L:  28] passthrough_proxy.py
│       │   ├── [L: 260] tracing.py
│       │   └── transforms/
│       │       ├── [L:  42] __init__.py
│       │       ├── [L: 429] anthropic.py
│       │       ├── [L: 360] openai.py
│       │       ├── [L:  98] tool_id_mapper.py
│       │       ├── [L: 115] types.py
│       │       └── [L: 197] validation.py
│       ├── server/
│       │   ├── [L:  65] __init__.py
│       │   ├── [L: 314] engine.py
│       │   ├── factories/
│       │   │   ├── [L:  11] __init__.py
│       │   │   └── [L: 345] node_factory.py
│       │   ├── handlers/
│       │   │   ├── [L:  32] __init__.py
│       │   │   ├── [L: 502] graph_handler.py
│       │   │   ├── [L: 337] node_interaction_handler.py
│       │   │   ├── [L: 501] node_lifecycle_handler.py
│       │   │   ├── [L: 255] python_executor.py
│       │   │   ├── [L: 217] repl_command_handler.py
│       │   │   ├── [L: 114] server_handler.py
│       │   │   ├── [L: 190] session_handler.py
│       │   │   └── [L: 306] workflow_handler.py
│       │   ├── [L: 200] protocols.py
│       │   ├── [L: 478] proxy_manager.py
│       │   ├── [L: 158] session_registry.py
│       │   └── [L:  94] validation.py
│       └── transport/
│           ├── [L:  52] __init__.py
│           ├── [L: 380] http.py
│           ├── [L: 125] in_process.py
│           ├── [L:  67] protocol.py
│           ├── [L: 414] tcp_socket.py
│           └── [L: 421] unix_socket.py
└── tests/
    ├── [L:   1] __init__.py
    ├── cli/
    │   ├── [L:   0] __init__.py
    │   ├── [L:  34] test_graph_commands.py
    │   ├── [L:  76] test_node_commands.py
    │   └── [L:  64] test_session_commands.py
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
    │   │   ├── llm/
    │   │   │   ├── [L:   1] __init__.py
    │   │   │   ├── [L: 176] test_chat_node.py
    │   │   │   ├── [L: 383] test_fork.py
    │   │   │   └── [L: 493] test_openrouter.py
    │   │   ├── terminal/
    │   │   │   └── [L: 507] test_claude_wezterm_fork.py
    │   │   ├── [L: 213] test_base.py
    │   │   ├── [L: 210] test_bash.py
    │   │   ├── [L: 231] test_budget.py
    │   │   ├── [L: 126] test_cancellation.py
    │   │   ├── [L: 173] test_claude_wezterm_proxy.py
    │   │   ├── [L: 258] test_context.py
    │   │   ├── [L: 529] test_graph.py
    │   │   ├── [L: 121] test_policies.py
    │   │   ├── [L: 942] test_terminal.py
    │   │   ├── [L: 308] test_tools.py
    │   │   ├── [L: 317] test_trace.py
    │   │   └── [L: 354] test_unified_api.py
    │   ├── session/
    │   │   ├── [L:   0] __init__.py
    │   │   └── [L: 103] test_session_factory.py
    │   ├── [L: 549] test_history.py
    │   ├── [L: 415] test_managers.py
    │   ├── [L: 538] test_parsers.py
    │   ├── [L:  90] test_validation.py
    │   └── workflow/
    │       ├── [L:   1] __init__.py
    │       ├── [L: 728] test_run.py
    │       └── [L: 178] test_workflow.py
    ├── frontends/
    │   ├── [L:   1] __init__.py
    │   ├── sdk/
    │   │   ├── [L:   1] __init__.py
    │   │   └── [L: 279] test_client.py
    │   └── tui/
    │       ├── [L:   1] __init__.py
    │       ├── [L: 682] test_commander_dependencies.py
    │       └── [L: 665] test_variable_expansion.py
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
    │   ├── [L: 516] test_engine.py
    │   ├── [L: 287] test_engine_proxy.py
    │   ├── [L: 302] test_engine_sessions.py
    │   ├── [L: 354] test_fork_handler.py
    │   ├── [L: 445] test_graph_handler.py
    │   ├── [L: 284] test_proxy_manager.py
    │   ├── [L: 195] test_session_registry.py
    │   └── [L: 204] test_validation.py
    └── transport/
        └── [L:   1] __init__.py

71 directories, 285 files, 69,393 total lines
