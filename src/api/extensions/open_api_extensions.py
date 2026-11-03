from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.utils import generate_unique_id


class OpenApiExtensions:
    @staticmethod
    def use_plain_operation_names(app: FastAPI) -> None:
        """The controller decorator prefixes route names with the class name; operation ids and summaries stay what callers already see."""
        for route in app.routes:
            if isinstance(route, APIRoute):
                route.name = route.name.rsplit(".", 1)[-1]
                route.unique_id = route.operation_id or generate_unique_id(route)
