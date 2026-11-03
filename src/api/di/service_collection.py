import inspect
import threading
from typing import get_type_hints

from mediatorx import Mediator


class ServiceProvider:
    """Builds what was registered: a singleton once for the process, a scoped service at each resolve. The mediator resolves a handler per `send`, so once per request; handlers hold no state of their own."""

    SINGLETON, INSTANCE, SCOPED = "singleton", "instance", "scoped"

    def __init__(self, registrations: dict[type, tuple[str, object]], handlers: dict[type, type]):
        self._registrations = registrations
        self._singletons: dict[type, object] = {}
        self._lock = threading.RLock()
        self.mediator = Mediator(resolver=self)
        for message, handler in handlers.items():
            self.mediator.register(message, handler)

    def get(self, service: type) -> object:
        if service not in self._registrations:
            raise KeyError(f"no registration for {service.__name__}")
        lifetime, implementation = self._registrations[service]
        if lifetime == self.INSTANCE:
            return implementation
        if lifetime == self.SCOPED:
            return self._create(implementation)
        # FastAPI runs sync dependencies on worker threads: two first uses must still build one singleton.
        with self._lock:
            if service not in self._singletons:
                self._singletons[service] = self._create(implementation)
            return self._singletons[service]

    def resolve(self, t: type) -> object:
        """mediatorx's resolver protocol."""
        return self.get(t)

    def _create(self, implementation: type) -> object:
        if "__init__" not in vars(implementation):
            return implementation()
        hints = get_type_hints(implementation.__init__)
        names = [name for name in inspect.signature(implementation.__init__).parameters if name != "self"]
        return implementation(**{name: self.get(hints[name]) for name in names})


class ServiceCollection:
    """The explicit lifetimes, like `AddSingleton` and `AddScoped`. Constructor parameters are resolved by their type hints."""

    def __init__(self):
        self._registrations: dict[type, tuple[str, object]] = {}
        self._handlers: dict[type, type] = {}

    def add_singleton(self, service: type, implementation: type | None = None) -> "ServiceCollection":
        self._registrations[service] = (ServiceProvider.SINGLETON, implementation or service)
        return self

    def add_instance(self, service: type, instance: object) -> "ServiceCollection":
        self._registrations[service] = (ServiceProvider.INSTANCE, instance)
        return self

    def add_scoped(self, service: type, implementation: type | None = None) -> "ServiceCollection":
        self._registrations[service] = (ServiceProvider.SCOPED, implementation or service)
        return self

    def add_handler(self, message: type, handler: type) -> "ServiceCollection":
        """A command or query with its handler, which is scoped."""
        self._handlers[message] = handler
        return self.add_scoped(handler)

    def build(self) -> ServiceProvider:
        return ServiceProvider(self._registrations, self._handlers)
