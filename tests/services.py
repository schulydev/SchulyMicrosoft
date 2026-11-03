"""What the tests reach into, resolved from the composition root: the same singletons the routes use, so a patch here is a patch there."""

import src.infrastructure.microsoft.account_cache as account_cache  # noqa: F401
from src.api.app import app
from src.api.http_headers import HttpHeaders as config  # noqa: F401
from src.application.abstractions.i_browser_sign_in import IBrowserSignIn
from src.application.abstractions.i_chat_sender import IChatSender
from src.application.abstractions.i_emoji_catalogue import IEmojiCatalogue
from src.application.abstractions.i_file_text_extractor import IFileTextExtractor
from src.application.abstractions.i_file_thumbnails import IFileThumbnails
from src.application.abstractions.i_gif_search import IGifSearch
from src.application.abstractions.i_graph_client_factory import IGraphClientFactory
from src.application.abstractions.i_graph_search import IGraphSearch
from src.application.abstractions.i_mail_folder_roles import IMailFolderRoles
from src.application.abstractions.i_microsoft_http_clients import IMicrosoftHttpClients
from src.application.abstractions.i_one_note import IOneNote
from src.application.abstractions.i_pdf_converter import IPdfConverter
from src.application.abstractions.i_profile_reader import IProfileReader
from src.application.abstractions.i_sign_in_store import ISignInStore
from src.application.abstractions.i_teams_chat import ITeamsChat
from src.application.abstractions.i_teams_files import ITeamsFiles
from src.application.options.password_sign_in_options import PasswordSignInOptions
from src.application.services.chat_html_sanitizer import ChatHtmlSanitizer
from src.application.services.onenote_html_sanitizer import OneNoteHtmlSanitizer
from src.application.services.warm_up_tracker import WarmUpTracker
from src.domain.chat.outgoing_message import OutgoingMessage  # noqa: F401
from src.domain.chat.upload import Upload  # noqa: F401
from src.domain.errors.file_fetch_error import FileFetchError  # noqa: F401
from src.domain.errors.resource_too_large import ResourceTooLarge  # noqa: F401
from src.domain.errors.send_error import SendError  # noqa: F401
from src.domain.errors.text_error import TextError  # noqa: F401
from src.domain.files.file_limits import FileLimits as app_module  # noqa: F401
from src.infrastructure.microsoft.account_runner import AccountRunner  # noqa: F401
from src.infrastructure.microsoft.broker_cache import BrokerCache as _BrokerCache  # noqa: F401
from src.infrastructure.password_signin.sign_in_job import SignInJob  # noqa: F401

services = app.state.services

outnote_client = services.get(IGraphClientFactory)
http_clients = services.get(IMicrosoftHttpClients)
browser_auth = services.get(IBrowserSignIn)
profile = services.get(IProfileReader)
folder_roles = services.get(IMailFolderRoles)
teams_chat = services.get(ITeamsChat)
chat_send = services.get(IChatSender)
emojis = services.get(IEmojiCatalogue)
file_pdf = services.get(IPdfConverter)
file_text = services.get(IFileTextExtractor)
file_thumbs = services.get(IFileThumbnails)
gifs = services.get(IGifSearch)
onenote = services.get(IOneNote)
search = services.get(IGraphSearch)
teams_files = services.get(ITeamsFiles)
chat_html = services.get(ChatHtmlSanitizer)
onenote_html = services.get(OneNoteHtmlSanitizer)
sign_in_store = services.get(ISignInStore)
sign_in_options = services.get(PasswordSignInOptions)
warm_up_tracker = services.get(WarmUpTracker)
