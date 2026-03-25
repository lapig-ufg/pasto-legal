from pydantic import BaseModel, Field
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, Union
from datetime import datetime

class Message(BaseModel, ABC):
    """Classe base comum para todas as mensagens."""
    id: Optional[str] = None
    role: Optional[str] = None
    created_at: Optional[int] = None
    from_history: Optional[bool] = None
    stop_after_tool_call: Optional[bool] = None

    @abstractmethod
    def to_component(self) -> None:
        """Método abstrato que deve ser implementado por todas as subclasses."""
        pass

    @property
    def formatted_date(self) -> str:
        """Converte o timestamp do JSON para uma data legível."""
        if self.created_at:
            return datetime.fromtimestamp(self.created_at).strftime('%d/%m/%Y %H:%M:%S')
        return "Data desconhecida"



class SystemMessage(Message):
    content: str

    def to_component(self) -> None:
        print(f"⚙️ [SYSTEM] {self.id}\n{self.content}\n{'-'*40}")


class UserMessage(Message):
    content: str

    def to_component(self) -> None:
        print(f"👤 [USER] {self.id}\n{self.content}\n{'-'*40}")


class AssistantMessage(Message):
    content: Optional[str] = None
    metrics: Optional[Dict[str, int]] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None

    def to_component(self) -> None:
        print(f"🤖 [ASSISTANT] {self.id}")
        if self.content:
            print(f"Content: {self.content}")
        if self.tool_calls:
            print(f"Tool Calls: {len(self.tool_calls)} request(s)")
        print('-'*40)


class ToolMessage(Message):
    tool_name: str
    content: Union[List[str], str]
    tool_calls: List[Dict[str, Any]]

    def to_component(self) -> None:
        print(f"🛠️ [TOOL: {self.tool_name}] {self.id}")
        content_str = self.content[0] if isinstance(self.content, list) and self.content else self.content
        print(f"Result: {content_str}\n{'-'*40}")