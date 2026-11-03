from src.api.di.service_collection import ServiceCollection
from src.application.abstractions.i_one_note import IOneNote
from src.application.abstractions.i_one_note_runner import IOneNoteRunner
from src.application.commands.create_one_note_page_command import CreateOneNotePageCommand, CreateOneNotePageHandler
from src.application.commands.delete_one_note_page_command import DeleteOneNotePageCommand, DeleteOneNotePageHandler
from src.application.commands.update_one_note_page_command import UpdateOneNotePageCommand, UpdateOneNotePageHandler
from src.application.queries.get_one_note_page_query import GetOneNotePageQuery, GetOneNotePageHandler
from src.application.queries.get_one_note_resource_query import GetOneNoteResourceQuery, GetOneNoteResourceHandler
from src.application.queries.get_one_note_sections_query import GetOneNoteSectionsQuery, GetOneNoteSectionsHandler
from src.application.queries.list_notebooks_query import ListNotebooksQuery, ListNotebooksHandler
from src.application.queries.list_one_note_notebooks_query import ListOneNoteNotebooksQuery, ListOneNoteNotebooksHandler
from src.application.queries.list_one_note_pages_query import ListOneNotePagesQuery, ListOneNotePagesHandler
from src.application.queries.search_one_note_query import SearchOneNoteQuery, SearchOneNoteHandler
from src.application.services.onenote_html_sanitizer import OneNoteHtmlSanitizer
from src.infrastructure.graph.onenote_client import OneNoteClient
from src.infrastructure.graph.onenote_runner import OneNoteRunner


class OneNoteExtensions:
    @staticmethod
    def add_one_note(services: ServiceCollection) -> ServiceCollection:
        services.add_singleton(OneNoteHtmlSanitizer)
        services.add_singleton(IOneNote, OneNoteClient)
        services.add_singleton(IOneNoteRunner, OneNoteRunner)

        services.add_handler(ListNotebooksQuery, ListNotebooksHandler)
        services.add_handler(ListOneNoteNotebooksQuery, ListOneNoteNotebooksHandler)
        services.add_handler(GetOneNoteSectionsQuery, GetOneNoteSectionsHandler)
        services.add_handler(ListOneNotePagesQuery, ListOneNotePagesHandler)
        services.add_handler(CreateOneNotePageCommand, CreateOneNotePageHandler)
        services.add_handler(GetOneNotePageQuery, GetOneNotePageHandler)
        services.add_handler(UpdateOneNotePageCommand, UpdateOneNotePageHandler)
        services.add_handler(DeleteOneNotePageCommand, DeleteOneNotePageHandler)
        services.add_handler(GetOneNoteResourceQuery, GetOneNoteResourceHandler)
        services.add_handler(SearchOneNoteQuery, SearchOneNoteHandler)
        return services
