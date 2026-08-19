from sqlalchemy.orm import sessionmaker
from .sqlalchemy_repo import SqlAlchemyUserRepository
from src.domain.uow import AbstractUnitOfWork

class SqlAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self, session_factory: sessionmaker):
        self.session_factory = session_factory

    def __enter__(self):
        self.session = self.session_factory()
        self.users = SqlAlchemyUserRepository(self.session)
        return super().__enter__()

    def __exit__(self, exc_type, *args):
        if exc_type: self.rollback()
        self.session.close()
        super().__exit__(exc_type, *args)

    def commit(self): self.session.commit()
    def rollback(self): self.session.rollback()
