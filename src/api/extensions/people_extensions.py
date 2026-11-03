from src.api.di.service_collection import ServiceCollection
from src.application.abstractions.i_people_photos import IPeoplePhotos
from src.application.queries.get_person_photo_query import GetPersonPhotoQuery, GetPersonPhotoHandler
from src.application.queries.get_user_photo_query import GetUserPhotoQuery, GetUserPhotoHandler
from src.infrastructure.graph.people_photos import PeoplePhotos


class PeopleExtensions:
    @staticmethod
    def add_people(services: ServiceCollection) -> ServiceCollection:
        services.add_singleton(IPeoplePhotos, PeoplePhotos)

        services.add_handler(GetPersonPhotoQuery, GetPersonPhotoHandler)
        services.add_handler(GetUserPhotoQuery, GetUserPhotoHandler)
        return services
