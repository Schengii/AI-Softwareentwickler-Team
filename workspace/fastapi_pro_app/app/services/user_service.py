from app.domain.user import User
from app.infrastructure.user_repository import UserRepository
from app.schemas.user import UserCreate, UserResponse

class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository

    async def create_user(self, data: UserCreate) -> UserResponse:
        # Business Logik hier (z.B. Validierung, Hashing)
        user = User(email=data.email, password=data.password) 
        created_user = await self.repository.create(user)
        return UserResponse.model_validate(created_user)
