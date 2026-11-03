from src.api.di.service_collection import ServiceCollection
from src.application.abstractions.i_file_text_extractor import IFileTextExtractor
from src.application.abstractions.i_file_thumbnails import IFileThumbnails
from src.application.abstractions.i_pdf_converter import IPdfConverter
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.application.commands.convert_to_pdf_command import ConvertToPdfCommand, ConvertToPdfHandler
from src.application.commands.convert_to_text_command import ConvertToTextCommand, ConvertToTextHandler
from src.application.queries.get_drive_item_content_query import GetDriveItemContentQuery, GetDriveItemContentHandler
from src.application.queries.get_drive_item_pdf_query import GetDriveItemPdfQuery, GetDriveItemPdfHandler
from src.application.queries.get_drive_item_query import GetDriveItemQuery, GetDriveItemHandler
from src.application.queries.get_drive_item_text_query import GetDriveItemTextQuery, GetDriveItemTextHandler
from src.application.queries.get_drive_thumbnail_query import GetDriveThumbnailQuery, GetDriveThumbnailHandler
from src.application.queries.get_shared_drive_item_pdf_query import GetSharedDriveItemPdfQuery, GetSharedDriveItemPdfHandler
from src.application.queries.get_shared_drive_item_text_query import GetSharedDriveItemTextQuery, GetSharedDriveItemTextHandler
from src.application.queries.get_shared_drive_thumbnail_query import GetSharedDriveThumbnailQuery, GetSharedDriveThumbnailHandler
from src.application.queries.list_drive_item_children_query import ListDriveItemChildrenQuery, ListDriveItemChildrenHandler
from src.application.queries.list_files_query import ListFilesQuery, ListFilesHandler
from src.application.queries.list_recent_files_query import ListRecentFilesQuery, ListRecentFilesHandler
from src.application.queries.list_shared_files_query import ListSharedFilesQuery, ListSharedFilesHandler
from src.application.services.account_image_reader import AccountImageReader
from src.application.services.drive_file_text_reader import DriveFileTextReader
from src.application.services.drive_item_checks import DriveItemChecks
from src.infrastructure.files.file_text_extractor import FileTextExtractor
from src.application.services.file_downloads import FileDownloads
from src.infrastructure.graph.file_thumbnails import FileThumbnails
from src.infrastructure.graph.pdf_converter import PdfConverter
from src.infrastructure.graph.teams_files import TeamsFiles


class FilesExtensions:
    @staticmethod
    def add_files(services: ServiceCollection) -> ServiceCollection:
        services.add_singleton(IFileThumbnails, FileThumbnails)
        services.add_singleton(IPdfConverter, PdfConverter)
        services.add_singleton(IFileTextExtractor, FileTextExtractor)
        services.add_singleton(ITeamsFiles, TeamsFiles)
        services.add_singleton(DriveItemChecks)
        services.add_singleton(FileDownloads)
        services.add_singleton(DriveFileTextReader)
        services.add_singleton(AccountImageReader)

        services.add_handler(ListFilesQuery, ListFilesHandler)
        services.add_handler(GetDriveThumbnailQuery, GetDriveThumbnailHandler)
        services.add_handler(GetSharedDriveThumbnailQuery, GetSharedDriveThumbnailHandler)
        services.add_handler(GetDriveItemPdfQuery, GetDriveItemPdfHandler)
        services.add_handler(GetSharedDriveItemPdfQuery, GetSharedDriveItemPdfHandler)
        services.add_handler(ConvertToPdfCommand, ConvertToPdfHandler)
        services.add_handler(GetSharedDriveItemTextQuery, GetSharedDriveItemTextHandler)
        services.add_handler(GetDriveItemTextQuery, GetDriveItemTextHandler)
        services.add_handler(ConvertToTextCommand, ConvertToTextHandler)
        services.add_handler(GetDriveItemQuery, GetDriveItemHandler)
        services.add_handler(ListDriveItemChildrenQuery, ListDriveItemChildrenHandler)
        services.add_handler(GetDriveItemContentQuery, GetDriveItemContentHandler)
        services.add_handler(ListSharedFilesQuery, ListSharedFilesHandler)
        services.add_handler(ListRecentFilesQuery, ListRecentFilesHandler)
        return services
