import defusedxml.ElementTree as parser
import re
from django.utils.dateparse import parse_datetime, parse_date
from django.utils import timezone


LINE_BREAK_PATTERN = re.compile(r'[ \t]*[\n\r]+[ \t]*')
NAMESPACES = {
    'dc': 'http://purl.org/dc/terms/',
    'dcterms': 'http://purl.org/dc/terms/',
    'dcam': 'http://purl.org/dc/dcam/',
    'marcrel': 'http://id.loc.gov/vocabulary/relators/',
    'pg': 'http://www.gutenberg.org/2009/pgterms/',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
}


def fix_subtitles(title):
    """
    This formats subtitles with (semi)colons instead of new lines. The first
    subtitle is introduced with a colon, and the rest are introduced with
    semicolons.

    >>> fix_subtitles(u'First Across ...\r\nThe Story of ... \r\n'
    ... 'Being an investigation into ...')
    u'First Across ...: The Story of ...; Being an investigation into ...'
    """

    new_title = LINE_BREAK_PATTERN.sub(': ', title, 1)
    return LINE_BREAK_PATTERN.sub('; ', new_title)


def get_book(id, xml_file_path):
    """ Based on https://gist.github.com/andreasvc/b3b4189120d84dec8857 """

    # Parse the XML.
    document = None
    try:
        document = parser.parse(xml_file_path)
    except:
        raise Exception('The XML file could not be parsed.')

    # Get the book node.
    root = document.getroot()
    book = root.find('{%(pg)s}ebook' % NAMESPACES)

    result = {
        'id': int(id),
        'title': None,
        'authors': [],
        'summaries': [],
        'editors': [],
        'translators': [],
        'type': None,
        'subjects': [],
        'languages': [],
        'added_date': None,
        'update_date': None,
        'formats': {},
        'downloads': None,
        'bookshelves': [],
        'copyright': None
    }

    # Authors
    creators = book.findall('.//{%(dc)s}creator' % NAMESPACES)
    for creator in creators:
        author = get_person(creator)
        if author is not None:
            result['authors'] += [author]

    # Editors
    editor_elements = book.findall('.//{%(marcrel)s}edt' % NAMESPACES)
    for editor_element in editor_elements:
        editor = get_person(editor_element)
        if editor is not None:
            result['editors'] += [editor]

    # Translators
    translator_elements = book.findall('.//{%(marcrel)s}trl' % NAMESPACES)
    for translator_element in translator_elements:
        translator = get_person(translator_element)
        if translator is not None:
            result['translators'] += [translator]

    # Title
    title = book.find('.//{%(dc)s}title' % NAMESPACES)
    if title is not None:
        result['title'] = fix_subtitles(
            safe_unicode(title.text, encoding='UTF-8')
        )

    # Subjects
    result['subjects'] = set()
    for subject in book.findall('.//{%(dc)s}subject' % NAMESPACES):
        subject_type = subject.find('.//{%(dcam)s}memberOf' % NAMESPACES)
        if subject_type is None:
            continue
        subject_type = subject_type.get('{%(rdf)s}resource' % NAMESPACES)
        value = subject.find('.//{%(rdf)s}value' % NAMESPACES)
        value = value.text
        if subject_type in ('%(dc)sLCSH' % NAMESPACES):
            result['subjects'].add(value)
    result['subjects'] = list(result['subjects'])
    result['subjects'].sort()

    # Book Shelves
    result['bookshelves'] = set()
    for bookshelf in book.findall('.//{%(pg)s}bookshelf' % NAMESPACES):
        value = bookshelf.find('.//{%(rdf)s}value' % NAMESPACES)
        if value is not None:
            result['bookshelves'].add(value.text)
    result['bookshelves'] = list(result['bookshelves'])

    # Copyright
    rights = book.find('.//{%(dc)s}rights' % NAMESPACES)
    if rights.text.startswith('Public domain in the USA.'):
        result['copyright'] = False
    elif rights.text.startswith('Copyrighted.'):
        result['copyright'] = True
    else:
        result['copyright'] = None

    # Formats (preferring image URLs to `noimages` URLs)
    for file in book.findall('.//{%(pg)s}file' % NAMESPACES):
        content_type = file.find('{%(dc)s}format//{%(rdf)s}value' % NAMESPACES)
        if (
            content_type.text not in result['formats']
            or 'noimages' in result['formats'][content_type.text]
        ):
            url = file.get('{%(rdf)s}about' % NAMESPACES)
            result['formats'][content_type.text] = url

    # Type
    book_type = book.find(
        './/{%(dc)s}type//{%(rdf)s}value' % NAMESPACES
    )
    result['type'] = 'Text' if book_type is None else book_type.text

    # Languages
    languages = book.findall(
        './/{%(dc)s}language//{%(rdf)s}value' % NAMESPACES
    )
    result['languages'] = [language.text for language in languages] or []

    # Added_date
    book_added_date = book.find(
        './/{%(dcterms)s}issued' % NAMESPACES
    )
    #result['added_date'] = None if book_added_date is None else book_added_date.text
    if book_added_date is not None and book_added_date.text:
        parsed_dt = parse_datetime(book_added_date.text)
        if parsed_dt is not None:
            # If it's naive, make it timezone-aware using Django's default timezone
            if timezone.is_naive(parsed_dt):
                result['added_date'] = timezone.make_aware(parsed_dt)
            else:
                result['added_date'] = parsed_dt
        else:
            # Fallback if it's just a date string (YYYY-MM-DD) instead of a full datetime
            parsed_date = parse_date(book_added_date.text)
            result['added_date'] = timezone.make_aware(
                datetime.combine(parsed_date, datetime.min.time())
            ) if parsed_date else None
    else:
        result['added_date'] = None

    # Update_date
    book_update_date = book.find(
        './/{%(dcterms)s}modified' % NAMESPACES
    )
    #result['update_date'] = None if book_update_date is None else book_update_date.text
    if book_update_date is not None and book_update_date.text:
        parsed_dt = parse_datetime(book_update_date.text)
        if parsed_dt is not None:
            # If it's naive, make it timezone-aware using Django's default timezone
            if timezone.is_naive(parsed_dt):
                result['update_date'] = timezone.make_aware(parsed_dt)
            else:
                result['update_date'] = parsed_dt
        else:
            # Fallback if it's just a date string (YYYY-MM-DD) instead of a full datetime
            parsed_date = parse_date(book_update_date.text)
            result['update_date'] = timezone.make_aware(
                datetime.combine(parsed_date, datetime.min.time())
            ) if parsed_date else None
    else:
        result['update_date'] = None

    # Download Count
    download_count = book.find('.//{%(pg)s}downloads' % NAMESPACES)
    if download_count is not None:
        result['downloads'] = int(download_count.text)
    
    # Summary
    summaries = book.findall('.//{%(pg)s}marc520' % NAMESPACES)
    result['summaries'] = [summary.text for summary in summaries]

    return result


def get_person(person_element):
    name = person_element.find('.//{%(pg)s}name' % NAMESPACES)

    if name is None:
        return None

    person = {
        'birth': None,
        'death': None,
        'name': safe_unicode(name.text, encoding='UTF-8'),
    }

    birth = person_element.find('.//{%(pg)s}birthdate' % NAMESPACES)

    if birth is not None:
        person['birth'] = int(birth.text)

    death = person_element.find('.//{%(pg)s}deathdate' % NAMESPACES)

    if death is not None:
        person['death'] = int(death.text)

    return person


def safe_unicode(arg, *args, **kwargs):
    """ Coerce argument to Unicode if it's not already. """
    return arg if isinstance(arg, str) else str(arg, *args, **kwargs)
