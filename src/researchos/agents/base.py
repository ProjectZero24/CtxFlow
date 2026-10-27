"""Base Agent — abstract base class for all ResearchOS agents.

Defines the common interface and lifecycle for agents in the pipeline.
Each agent receives context, executes its task, and returns a structured
result that can be passed to the next agent in the chain.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Agent Status
# ---------------------------------------------------------------------------

class AgentStatus(str, Enum):
    """Execution status of an agent."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Agent Messages
# ---------------------------------------------------------------------------

@dataclass
class AgentMessage:
    """A message passed between agents in the pipeline.

    Attributes
    ----------
    sender : str
        Name of the sending agent.
    content : Any
        Payload data.
    message_type : str
        Type of message (e.g. ``"query"``, ``"result"``, ``"error"``).
    metadata : dict
        Additional context.
    timestamp : float
        When the message was created.
    """

    sender: str
    content: Any
    message_type: str = "data"
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentResult:
    """Standardized result from an agent execution.

    Attributes
    ----------
    agent_name : str
        Name of the agent that produced this result.
    success : bool
        Whether execution succeeded.
    data : Any
        The primary output payload.
    error : str | None
        Error message if execution failed.
    messages : list[AgentMessage]
        Messages generated during execution.
    metadata : dict
        Auxiliary data (latency, token counts, etc.).
    duration_ms : float
        Execution time in milliseconds.
    """

    agent_name: str
    success: bool = True
    data: Any = None
    error: Optional[str] = None
    messages: List[AgentMessage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Base Agent
# ---------------------------------------------------------------------------

class BaseAgent(ABC):
    """Abstract base class for ResearchOS agents.

    Subclasses must implement :meth:`execute`. The base class provides
    lifecycle hooks, logging, and timing.

    Parameters
    ----------
    name : str
        Unique agent name.
    llm : callable | None
        An LLM callable ``(prompt, system) -> str`` for agents that
        need language model access.
    """

    def __init__(
        self,
        name: str,
        llm: Optional[Callable[[str, str], str]] = None,
    ) -> None:
        self.name = name
        self._llm = llm
        self._status = AgentStatus.IDLE
        self._execution_count = 0

    @property
    def status(self) -> AgentStatus:
        return self._status

    @property
    def execution_count(self) -> int:
        return self._execution_count

    def run(self, **kwargs: Any) -> AgentResult:
        """Execute the agent with timing and error handling.

        Calls :meth:`execute` internally. Subclasses should override
        :meth:`execute`, not this method.

        Parameters
        ----------
        **kwargs
            Arguments passed to :meth:`execute`.

        Returns
        -------
        AgentResult
        """
        self._status = AgentStatus.RUNNING
        start = time.time()

        try:
            result = self.execute(**kwargs)
            self._status = AgentStatus.COMPLETED
            self._execution_count += 1

            if not isinstance(result, AgentResult):
                result = AgentResult(
                    agent_name=self.name,
                    success=True,
                    data=result,
                )

            result.duration_ms = (time.time() - start) * 1000
            result.agent_name = self.name

            logger.info(
                "Agent '%s' completed in %.1fms",
                self.name, result.duration_ms,
            )
            return result

        except Exception as exc:
            self._status = AgentStatus.FAILED
            duration = (time.time() - start) * 1000
            logger.error(
                "Agent '%s' failed after %.1fms: %s",
                self.name, duration, exc, exc_info=True,
            )
            return AgentResult(
                agent_name=self.name,
                success=False,
                error=str(exc),
                duration_ms=duration,
            )

    @abstractmethod
    def execute(self, **kwargs: Any) -> AgentResult:
        """Execute the agent's core logic.

        Subclasses must implement this method.

        Parameters
        ----------
        **kwargs
            Agent-specific arguments.

        Returns
        -------
        AgentResult
        """

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(name={self.name!r}, "
            f"status={self._status.value!r})"
        )
