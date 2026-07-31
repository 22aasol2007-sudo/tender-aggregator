from app.parsers.base import ParsedTender, TenderParser
from app.parsers.commercial import B2BCenterParser, RoseltorgParser, RtsParser, SberAstParser
from app.parsers.extra_sources import get_extra_parsers
from app.parsers.zakupki import ZakupkiParser


def get_parsers() -> dict[str, TenderParser]:
    parsers: list[TenderParser] = [
        ZakupkiParser("44"),
        ZakupkiParser("223"),
        RtsParser(),
        RoseltorgParser(),
        SberAstParser(),
        B2BCenterParser(),
        *get_extra_parsers(),
    ]
    return {p.source: p for p in parsers}


def list_sources() -> list[dict[str, str]]:
    return [{"id": p.source, "name": p.display_name} for p in get_parsers().values()]


__all__ = ["ParsedTender", "TenderParser", "get_parsers", "list_sources"]
