from src.api.di.service_collection import ServiceCollection
from src.application.abstractions.i_mail_folder_roles import IMailFolderRoles
from src.application.commands.create_mail_draft_command import CreateMailDraftCommand, CreateMailDraftHandler
from src.application.commands.delete_mail_command import DeleteMailCommand, DeleteMailHandler
from src.application.commands.flag_mail_command import FlagMailCommand, FlagMailHandler
from src.application.commands.forward_mail_command import ForwardMailCommand, ForwardMailHandler
from src.application.commands.mark_mail_read_command import MarkMailReadCommand, MarkMailReadHandler
from src.application.commands.move_mail_command import MoveMailCommand, MoveMailHandler
from src.application.commands.reply_mail_command import ReplyMailCommand, ReplyMailHandler
from src.application.commands.send_mail_command import SendMailCommand, SendMailHandler
from src.application.commands.send_mail_draft_command import SendMailDraftCommand, SendMailDraftHandler
from src.application.queries.get_mail_attachment_pdf_query import GetMailAttachmentPdfQuery, GetMailAttachmentPdfHandler
from src.application.queries.get_mail_attachment_query import GetMailAttachmentQuery, GetMailAttachmentHandler
from src.application.queries.get_mail_message_query import GetMailMessageQuery, GetMailMessageHandler
from src.application.queries.list_mail_attachments_query import ListMailAttachmentsQuery, ListMailAttachmentsHandler
from src.application.queries.list_mail_folders_query import ListMailFoldersQuery, ListMailFoldersHandler
from src.application.queries.list_mail_query import ListMailQuery, ListMailHandler
from src.application.services.mail_attachment_reader import MailAttachmentReader
from src.application.services.mail_folder_tree import MailFolderTree
from src.application.services.mail_message_builder import MailMessageBuilder
from src.infrastructure.graph.mail_folder_roles import MailFolderRoles


class MailExtensions:
    @staticmethod
    def add_mail(services: ServiceCollection) -> ServiceCollection:
        services.add_singleton(IMailFolderRoles, MailFolderRoles)
        services.add_singleton(MailFolderTree)
        services.add_singleton(MailMessageBuilder)
        services.add_singleton(MailAttachmentReader)

        services.add_handler(ListMailQuery, ListMailHandler)
        services.add_handler(ListMailFoldersQuery, ListMailFoldersHandler)
        services.add_handler(SendMailCommand, SendMailHandler)
        services.add_handler(CreateMailDraftCommand, CreateMailDraftHandler)
        services.add_handler(SendMailDraftCommand, SendMailDraftHandler)
        services.add_handler(GetMailMessageQuery, GetMailMessageHandler)
        services.add_handler(ListMailAttachmentsQuery, ListMailAttachmentsHandler)
        services.add_handler(GetMailAttachmentQuery, GetMailAttachmentHandler)
        services.add_handler(GetMailAttachmentPdfQuery, GetMailAttachmentPdfHandler)
        services.add_handler(ReplyMailCommand, ReplyMailHandler)
        services.add_handler(ForwardMailCommand, ForwardMailHandler)
        services.add_handler(MarkMailReadCommand, MarkMailReadHandler)
        services.add_handler(FlagMailCommand, FlagMailHandler)
        services.add_handler(MoveMailCommand, MoveMailHandler)
        services.add_handler(DeleteMailCommand, DeleteMailHandler)
        return services
