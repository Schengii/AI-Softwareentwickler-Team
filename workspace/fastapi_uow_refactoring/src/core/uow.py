from abc import ABC, abstractmethod
from typing import Callable
from sqlalchemy.orm import Session

class AbstractUnitOfWork(ABC):
    users: "UserRepository"  # Protocol/Abstract Base Class
    
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()

    @abstractmethod
    def commit(self): ...
    @abstractmethod
    def rollback(self): ...
    @abstractmethod
    def close(self): ...

class SqlAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def __enter__(self):
        self.session = self.session_factory()
        self.users = SqlAlchemyUserRepository(self.session)
        return super().__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        super().__exit__(exc_type, exc_val, exc_tb)

    def commit(self):
        self.session.commit()

    def rollback(self):
        self.session.rollback()

    def close(self):
        self.session.close()
