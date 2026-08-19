from abc import ABC, abstractmethod
from .repository import AbstractUserRepository

class AbstractUnitOfWork(ABC):
    users: AbstractUserRepository

    def __enter__(self): return self
    def __exit__(self, *args): self.rollback()
    @abstractmethod
    def commit(self): ...
    @abstractmethod
    def rollback(self): ...
