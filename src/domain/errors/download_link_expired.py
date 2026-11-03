class DownloadLinkExpired(Exception):
    """SharePoint refused a pre-authorized link, which is what an old one gets: ask Graph for a new one."""
