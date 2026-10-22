# Agent configuration

- `agent_config.json`: the agent as returned by the Managed Agents API (`python3 tools/ma_client.py agent get`). It records the model, the built-in toolset with its permissions, and the pinned version of every skill. The ids belong to the account the agent was built in. In your own account you get new ids.
- `system_prompt.md`: the system prompt (the same text as `system` in the config). It defines the 11-step workflow, the progress lines the UI reads (`STEP n/11: <name> - started|done|failed`), and the user commands `APPROVE`, `CHANGES:`, `REGENERATE`, `ADD CLIP` and `REVISION:`.

To update the prompt on an existing agent:

```bash
python3 tools/ma_client.py agent set-system --file agent/system_prompt.md
```

Every update creates a new agent version. Running sessions keep the version they started with, so start a new session to use it.
