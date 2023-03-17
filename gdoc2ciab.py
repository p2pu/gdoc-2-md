from __future__ import print_function
import pickle
import os.path
import os
import logging
import yaml
import re
import requests
import shutil
from pprint import pprint

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


logger = logging.getLogger(__name__)

# If modifying these scopes, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/documents.readonly']


# The ID of the google doc with the course content.
#DOCUMENT_ID = '1kEk1FPgjX3gjoueXbodY-5CaEGM9ah69MRmjYbXT7Lo'
DOCUMENT_ID = '1RCNDh7k8HQVR3fobYCZnErLF4CVwenc-OvMK5_4mGno'

NEW_TAB_LINKS = [
    r'https://community.p2pu.org/t/introduce-yourself/1571/',
    r'https://docs.google.com/presentation/d/1_s0FFtAPG8MHxL8yRFrdxaI22obFrX_ZsONz-sIZJSY/edit#slide=id.g3c793ae459_0_0',
    r'https://www.p2pu.org/en/courses/',
    r'https://learningcircles.p2pu.org/en/accounts/register.*?',
    r'https://learningcircles.p2pu.org.*?',
    r'https://community.p2pu.org/t/what-topics-are-missing/2786',
]


def get_doc(document_id):
    """Shows basic usage of the Docs API.
    Prints the title of a sample document.
    """
    creds = None
    # The file token.pickle stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server()
        # Save the credentials for the next run
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('docs', 'v1', credentials=creds)

    # Retrieve the documents contents from the Docs service.
    document = service.documents().get(documentId=document_id).execute()
    #print('The title of the document is: {}'.format(document.get('title')))
    return document


# Image formats to embed
IMAGE_FORMATS = ['jpeg', 'jpg', 'png', 'svg'] 

def smart_link(text, url, embed=False):
    #print('' + url + (' embed' if embed else '') )
    if any(map(lambda x: re.match(x, url), NEW_TAB_LINKS)):
        return f'<a href="{url}" target="_blank">{text}</a>'
    if not embed:
        return f"[{text}]({url})"

    if url.split('.')[-1].lower() in IMAGE_FORMATS:
        return f"![{text}]({url})"

    return f"[{text}]({url})"



def convert_to_course_outline(document):
    # document is formatted doc > body > content
    # content is a list of structural elements, for now handle paragraph and table

    content = document.get('body').get('content')
    print(document.get('inlineObjects'))
    content = filter(lambda se: 'paragraph' in se, content)
    modules = []  # [{'title': '', 'md': ''}]
    intro = ''
    for se in content:
        paragraph = se['paragraph']
        page_break = any([True for e in paragraph['elements'] if 'pageBreak' in e])
        if page_break:
            # Stop processing the document after the first page break
            break
        text = ''
        elements = paragraph['elements']
        #elements = filter(lambda e: e.get('textRun','').strip('\n') == '', elements)
        for eidx, element in enumerate(elements):
            if 'textRun' in element:
                textRun = element.get('textRun')
                textContent = textRun['content'].strip('\n')
                bold = textRun['textStyle'].get('bold', False)
                italic = textRun['textStyle'].get('italic', False)
                link = textRun['textStyle'].get('link', {}).get('url')
                if not textContent:
                    if any([bold, italic, link]):
                        logger.warning(f'Ignoring empty textRun. bold: {bold} italic: {italic} link: {link}')
                    continue
                if bold:
                    textContent = f'**{textContent}**'
                if italic:
                    textContent = f'*{textContent}*'
                if link:
                    text += smart_link(textContent, link, embed=True)
                else:
                    text += textContent
            elif 'inlineObjectElement' in element:
                inlineObjectElement = element.get('inlineObjectElement')
                inlineObject = document.get('inlineObjects').get(inlineObjectElement.get('inlineObjectId'))
                imageUri = inlineObject.get('inlineObjectProperties', {}).get('embeddedObject', {}).get('imageProperties', {}).get('contentUri')
                if imageUri:
                    print('Found iamge, downloading the sucker!')
                    r = requests.get(imageUri, stream=True)
                    print(r.headers['content-type'])
                    ext = r.headers.get('content-type', 'image/jpg').split('/')[-1]
                    image_path = f'assets/uploads/{inlineObject["objectId"]}.{ext}'
                    if r.status_code == 200:
                        with open(image_path, 'wb') as f:
                            r.raw.decode_content = True
                            shutil.copyfileobj(r.raw, f)
                            text += f'![{inlineObject["objectId"]}]({image_path})'


        if paragraph.get('paragraphStyle',{}).get('namedStyleType') == 'HEADING_2':
            text = '## ' + text + '\n'

        if paragraph.get('paragraphStyle',{}).get('namedStyleType') == 'HEADING_3':
            text = '### ' + text

        if paragraph.get('paragraphStyle',{}).get('namedStyleType') == 'HEADING_4':
            text = '#### ' + text

        if 'bullet' in paragraph:
            bullet = paragraph['bullet']
            nesting_level = bullet.get('nestingLevel', 0)
            list_properties = document.get('lists', {}).get(bullet.get('listId'), {}).get('listProperties',{})
            style = list_properties.get('nestingLevels')[nesting_level]
            if 'glyphType' in style and not style['glyphType'] == 'GLYPH_TYPE_UNSPECIFIED':
                glyph = '1.'
            else:
                glyph = '-'

            text = '   '*nesting_level + glyph + ' ' + text

        # Start a new module when encountering HEADING 1 (H1)
        if paragraph.get('paragraphStyle',{}).get('namedStyleType') == 'HEADING_1':
            modules += [{'title': text, 'md': ''}]
            continue 

        if len(modules) == 0:
            intro += text + '\n'
            continue

        module = modules[-1]
        module['md'] += text + '\n'

    course_outline = {
        'modules': modules,
        'title': document.get('title'),
        'intro': intro,
    }
    return course_outline


def write_module(title, text, index):
    slug = title.replace(' ', '-').lower()
    path = os.path.join('_guide', f'{index+1:02}_{slug}.md')

    
    with open(path, 'w') as f:
        f.write('---\n')
        f.write(f'title: "{title}"\n')
        f.write('---\n')
        f.write(text)


def write_index(text_md):
    with open('./index.md', 'w') as f:
        f.write('---\n')
        f.write(f'layout: index\n')
        f.write('---\n')
        f.write(text_md)


def write_course(course_outline):
    for index, module in enumerate(course_outline.get('modules')):
        write_module(module['title'], module['md'], index)


if __name__ == '__main__':
    doc = get_doc(DOCUMENT_ID)
    course_outline = convert_to_course_outline(doc)
    write_course(course_outline)
