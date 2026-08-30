"""The kinds of page developer documentation is made of."""

from enum import StrEnum


class DocType(StrEnum):
    """What kind of documentation page a document is.

    A closed set rather than a free string, so that an unrecognised kind cannot
    be stored at all — the acceptance criterion for this unit is that invalid
    values cannot be constructed, and a free string would not meet it.

    The cost is that adding a kind is a domain change. The list is therefore
    deliberately broad: the four Diátaxis categories, which describe what a
    page is *for*, plus the practical page types that recur across library
    documentation and do not fit those categories cleanly.

    Values are lowercase strings rather than integers so that a stored or
    published value is readable without a lookup table, and remains stable if
    members are ever reordered.
    """

    # What a page is for.
    TUTORIAL = "tutorial"
    HOW_TO = "how_to"
    REFERENCE = "reference"
    EXPLANATION = "explanation"

    # Reference material with a shape of its own.
    API_REFERENCE = "api_reference"
    CLI_REFERENCE = "cli_reference"
    CONFIGURATION = "configuration"
    SPECIFICATION = "specification"
    GLOSSARY = "glossary"

    # Getting something working.
    INSTALLATION = "installation"
    QUICKSTART = "quickstart"
    EXAMPLE = "example"
    COOKBOOK = "cookbook"

    # Moving between versions.
    CHANGELOG = "changelog"
    RELEASE_NOTES = "release_notes"
    MIGRATION_GUIDE = "migration_guide"
    DEPRECATION_NOTICE = "deprecation_notice"

    # When something is wrong.
    TROUBLESHOOTING = "troubleshooting"
    FAQ = "faq"

    # Around the documentation proper.
    README = "readme"
    OVERVIEW = "overview"
    ARCHITECTURE = "architecture"
    CONTRIBUTING = "contributing"
    BLOG_POST = "blog_post"
    OTHER = "other"
