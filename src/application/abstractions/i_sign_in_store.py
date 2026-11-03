from abc import ABC, abstractmethod

from pydantic import SecretStr

from src.application.abstractions.i_sign_in_job import ISignInJob


class ISignInStore(ABC):
    """The in-memory password sign-in jobs and their rate limits. One per process."""

    @abstractmethod
    def start(self, user_id: str, username: str, password: SecretStr) -> ISignInJob: ...

    @abstractmethod
    def promote(self, job: ISignInJob) -> None: ...

    @abstractmethod
    def get(self, job_id: str, user_id: str) -> ISignInJob | None: ...

    @abstractmethod
    def remove(self, job_id: str, user_id: str) -> None: ...

    @abstractmethod
    def sweep(self) -> None: ...

    @abstractmethod
    def clear(self) -> None: ...

    @abstractmethod
    async def wait_settled(self, job: ISignInJob, after_version: int, timeout: float) -> None: ...
