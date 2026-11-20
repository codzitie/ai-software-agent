"""Project-wide exceptions. The chat layer shows these to the user as plain messages."""


class AgentError(Exception):
    """Base class. The message is safe to show to the user."""


class InvalidRepoError(AgentError):
    """The repository path does not exist or is not a directory."""


class ToolError(AgentError):
    """A shared tool failed in a way the node cannot recover from."""


class UnsafeCommandError(AgentError):
    """A command (e.g. an LLM-written repro command) was blocked by the sandbox rules."""