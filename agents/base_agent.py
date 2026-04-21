"""
Base Agent Class - 所有Agent的抽象基类
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AgentMessage:
    """Agent间通信的消息格式"""
    def __init__(self, sender: str, receiver: str, msg_type: str, payload: Dict):
        self.sender = sender
        self.receiver = receiver
        self.msg_type = msg_type
        self.payload = payload
        self.timestamp = datetime.now()
    
    def __repr__(self):
        return f"AgentMessage({self.sender} -> {self.receiver}, type={self.msg_type})"


class BaseAgent(ABC):
    """Agent基类"""
    
    def __init__(self, name: str, config: Dict[str, Any]):
        self.name = name
        self.config = config
        self.logger = logging.getLogger(f"agent.{name}")
        self.message_queue: list = []
        
    @abstractmethod
    def run(self, **kwargs) -> Any:
        """Agent的主要执行逻辑"""
        pass
    
    def send_message(self, receiver: str, msg_type: str, payload: Dict) -> AgentMessage:
        """发送消息给其他Agent"""
        msg = AgentMessage(self.name, receiver, msg_type, payload)
        self.logger.debug(f"Sending message: {msg}")
        return msg
    
    def receive_message(self, message: AgentMessage) -> None:
        """接收消息"""
        if message.receiver == self.name:
            self.message_queue.append(message)
            self.logger.debug(f"Received message from {message.sender}")
    
    def log(self, level: str, message: str):
        """记录日志"""
        getattr(self.logger, level)(f"[{self.name}] {message}")
