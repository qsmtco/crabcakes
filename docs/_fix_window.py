with open('ui/window.py', 'r') as f:
    content = f.read()

# The bug: _agent_runtime_handler used before assigned
# Fix: move the two usages AFTER the AgentRuntimeHandler instantiation

old_block = '''        # AgentRuntime handler — owns AgentRuntime instances for special agents (Phase 1.4)
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        self._agent_runtime_handler = AgentRuntimeHandler(
            main_content=self._main_content,
            chat_render_handler=self._chat_render_handler,
            GLib_module=GLib,
            review_handler=self._review_handler,
        )

        # Register built-in special agents
        self._agent_runtime_handler.add_special_agent("Coder", "special/coder")'''

new_block = '''        # AgentRuntime handler — owns AgentRuntime instances for special agents (Phase 1.4)
        from ui.handlers.agent_runtime_handler import AgentRuntimeHandler
        self._agent_runtime_handler = AgentRuntimeHandler(
            main_content=self._main_content,
            chat_render_handler=self._chat_render_handler,
            GLib_module=GLib,
            review_handler=self._review_handler,
        )

        # Register built-in special agents
        self._agent_runtime_handler.add_special_agent("Coder", "special/coder")

        # NOW inject into dependents — after _agent_runtime_handler is assigned
        self._chat_handler.set_agent_runtime_handler(self._agent_runtime_handler)
        self._left_panel.set_special_agents(self._agent_runtime_handler)'''

if old_block in content:
    # Remove the misplaced usages first
    misplace1 = '        self._chat_handler.set_agent_runtime_handler(self._agent_runtime_handler)\n\n        # Wire Send button'
    misplace2 = '        self._left_panel.set_special_agents(self._agent_runtime_handler)\n\n        # AgentRuntime'
    
    content = content.replace(misplace1, '        # Wire Send button')
    content = content.replace(misplace2, '        # AgentRuntime')
    
    # Now add the correct placements after the assignment block
    old_block2 = '''        # Register built-in special agents
        self._agent_runtime_handler.add_special_agent("Coder", "special/coder")'''
    new_block2 = '''        # Register built-in special agents
        self._agent_runtime_handler.add_special_agent("Coder", "special/coder")

        # Inject into dependents after _agent_runtime_handler is assigned
        self._chat_handler.set_agent_runtime_handler(self._agent_runtime_handler)
        self._left_panel.set_special_agents(self._agent_runtime_handler)'''
    content = content.replace(old_block2, new_block2)
    
    with open('ui/window.py', 'w') as f:
        f.write(content)
    print("Fixed")
else:
    print("Block not found - content may have changed")
    # Show around AgentRuntimeHandler
    idx = content.find('AgentRuntimeHandler')
    print(repr(content[idx:idx+600]))
