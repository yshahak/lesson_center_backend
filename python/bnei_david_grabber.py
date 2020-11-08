# coding=utf-8
from __future__ import unicode_literals
from selenium import webdriver
import calendar
import urllib.request
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs
from pyluach.dates import HebrewDate
import traceback
import psycopg2.extras
from config import *
from sql_helper import *

postgres = psycopg2.connect(**postgres_con)
source_id = 1
lesson_template = 'https://www.bneidavid.org%s'
template_main = 'https://www.bneidavid.org/Web/He/VirtualTorah/Default.aspx'
template = 'https://www.bneidavid.org/Web/He/VirtualTorah/Lessons/Default.aspx?subject=&rabi=&name=&rfs=&rfh=&serie=%d'
template_id = 'https://www.bneidavid.org/Web/He/VirtualTorah/Lessons/Default.aspx?id=%d'

cursor = postgres.cursor()
cursor.execute('select originalid from lessons where sourceid = %s;', (source_id,))
exists_original_ids = [row[0] for row in cursor.fetchall()]
cursor.close()

subjectsIdMap = {
    'ללא': 1,
    'גמרא': 29,
    'אמונה': 30,
    'הלכה': 31,
    'הרצאות חול': 40,
    'כתבי הראי"ה': 44,
    'מוסר': 41,
    'פרשיות השבוע': 32,
    'שבת ומועדים': 33,
    'תנ"ך': 34,
    'תפילה': 27,
}

gimatria_map = {
    u'א': 1,
    u'ב': 2,
    u'ג': 3,
    u'ד': 4,
    u'ה': 5,
    u'ו': 6,
    u'ז': 7,
    u'ח': 8,
    u'ט': 9,
    u'י': 10,
    u'כ': 20,
    u'ך': 20,
    u'ל': 30,
    u'מ': 40,
    u'ם': 40,
    u'נ': 50,
    u'ן': 50,
    u'ס': 60,
    u'ע': 70,
    u'פ': 80,
    u'ף': 80,
    u'צ': 90,
    u'ץ': 90,
    u'ק': 100,
    u'ר': 200,
    u'ש': 300,
    u'ת': 400,
}

day_map = [
    u' ',
    u'א',
    u'ב',
    u'ג',
    u'ד',
    u'ה',
    u'ו',
    u'ז',
    u'ח',
    u'ט',
    u'י',
    u'יא',
    u'יב',
    u'יג',
    u'יד',
    u'טו',
    u'טז',
    u'יז',
    u'יח',
    u'יט',
    u'כ',
    u'כא',
    u'כב',
    u'כג',
    u'כד',
    u'כה',
    u'כו',
    u'כז',
    u'כח',
    u'כט',
    u'ל',
]

month_dict = {
    u'תשרי': 7,
    u'חשון': 8,
    u'חשוון': 8,
    u'כסלו': 9,
    u'טבת': 10,
    u'שבט': 11,
    u'אדר': 12,
    u'אדר א': 12,
    u'אדר ב': 13,
    u'ניסן': 1,
    u'אייר': 2,
    u'איר': 2,
    u'סיון': 3,
    u'סיוון': 3,
    u'תמוז': 4,
    u'אב': 5,
    u'אלול': 6,
}

now = get_timestamp()
counter = 0
series_map = {}
subjects_map = {}
ravs_map = {}
without_valid_content = set()

source = 'bnei_david'

driver = webdriver.PhantomJS()
driver.set_window_size(1120, 550)


def get_lesson(url, is_main_page=False):
    print('running on url {0}'.format(url))
    driver.get(url)
    grabbed_something = parse_lesson(driver.page_source, is_main_page)
    if grabbed_something and not is_main_page:
        page = 2
        while True:
            try:
                driver.find_element_by_xpath("//a[text()='%s']" % page).click()
                parse_lesson(driver.page_source, False)
                print('page %s grabbed successfully' % page)
                page = page + 1
            except:
                print('page %s not exists' % page)
                break


def parse_lesson(html_content, is_main_page=False):
    global counter, series_map, subjects_map, ravs_map, exists_original_ids, without_valid_content
    soup = BeautifulSoup(html_content, 'html.parser')
    tables = soup.findAll("div", {"class": 'tables_list'})
    grab_something = False
    cursor = postgres.cursor()
    for table in tables:
        rows = table.findAll("tr")
        for row in rows:
            try:
                lesson = {}
                if row.attrs and row.attrs['class'] and row.attrs['class'].__contains__('titles_list_info'):
                    continue
                lesson_id = row.find('span', id=lambda x: x and x.endswith('_lblId'))
                if lesson_id is None:
                    continue
                if is_main_page:
                    label = 'מומלצים - בני דוד' if lesson_id.attrs['id'].__contains__('Recommended') else 'אחרונים - בני דוד'
                else:
                    label = ''
                lesson['id'] = lesson_id.text
                original_id = int(lesson["id"])
                id = get_hash_for_id(source_id, original_id)
                if int(lesson['id']) in exists_original_ids and not is_main_page:
                    print('id exists', lesson['id'])
                    if is_main_page:
                        cursor.execute('''INSERT INTO labels (label,sourceid,lessonid) VALUES(%s,%s,%s);''',
                                       (label, source_id, id))
                    continue
                lesson['label'] = 'label'
                subject = row.find('span', id=lambda x: x and x.endswith('_lblSubject')).text
                lesson['subject'] = subject
                if subject in subjectsIdMap.keys():
                    lesson['subject_id'] = subjectsIdMap[subject]
                else:
                    lesson['subject_id'] = 1
                rav = row.find('span', id=lambda x: x and x.endswith('_lblRabi')).text
                lesson['rav'] = rav
                rav_id = row.find('span', id=lambda x: x and x.endswith('_lblRabiIdCol')).text
                lesson['rav_id'] = int(rav_id) if rav_id else -1
                name = row.find('a', id=lambda x: x and x.endswith('_hlName'))
                title = name.text
                lesson_url = lesson_template % name.attrs['href']
                # lesson['title'] = unicode(title)
                lesson['title'] = title
                lesson['lessonUrl'] = lesson_url
                sidra = row.find('a', id=lambda x: x and x.endswith('_hlSerieName'))
                sidre_name = sidra.text
                sidra_url = sidra.attrs['href'] if 'href' in sidra.attrs else ''
                lesson['series'] = sidre_name
                lesson['seriesUrl'] = sidra_url
                lesson['seriesId'] = sidra_url.split('serie=')[1] if sidra_url else -1
                date = row.find('span', id=lambda x: x and x.endswith('_lblDate')).text.strip()
                try:
                    timestamp = get_timestamp_for_date(date)
                except:
                    timestamp = now
                lesson['timestamp'] = timestamp
                lesson['dateStr'] = date
                length = row.find('span', id=lambda x: x and x.endswith('_lbllength')).text
                lesson['length'] = length
                lesson['duration'] = get_duration_in_seconds(length)
                video = row.find('a', id=lambda x: x and x.endswith('_hlVideo'))
                extracted = None
                video_url, audio_url = None, None
                has_link = False
                if video.attrs and 'href' in video.attrs:
                    has_link = True
                    video_url = video.attrs['href']
                    if video_url.endswith('/vf/audio/'):
                        video_url = None
                    else:
                        valid = validate_media_url(video_url)
                        if not valid:
                            extracted = extract_media(lesson_url)
                            video_url = extracted[0]
                lesson['videoUrl'] = video_url
                audio = row.find('a', id=lambda x: x and x.endswith('_hlAudio'))
                if audio.attrs and 'href' in audio.attrs:
                    has_link = True
                    audio_url = audio.attrs['href']
                    if audio_url.endswith('/vf/audio/'):
                        audio_url = None
                    else:
                        valid = validate_media_url(audio_url)
                        # print('valid={0} {1}'.format(valid, audio_url))
                        if not valid:
                            if not extracted:
                                extracted = extract_media(lesson_url)
                            audio_url = extracted[1]
                lesson['audioUrl'] = audio_url
                counter = counter + 1
                if not audio_url and not video_url:
                    print('no content for id={0}'.format(lesson['id']))
                    if has_link:
                        without_valid_content.add(int(lesson['id']))
                    continue
                original_subjectId = lesson["subject_id"]
                if original_subjectId not in subjects_map:
                    cursor.execute(
                        '''INSERT INTO categories(id,originalid,sourceid,category) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;'''
                        , (get_hash_for_id(source_id, original_subjectId), original_subjectId, source_id,
                           lesson['subject'],))
                    subjects_map[original_subjectId] = get_hash_for_id(source_id, original_subjectId)
                original_series_id = lesson["seriesId"]
                if original_series_id not in series_map:
                    cursor.execute(
                        '''INSERT INTO series(id,originalid,sourceid,serie) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;'''
                        , (get_hash_for_id(source_id, original_series_id), original_series_id, source_id,
                           lesson['series'],))
                    series_map[original_series_id] = get_hash_for_id(source_id, original_series_id)
                original_rav_id = lesson["rav_id"]
                if original_rav_id not in ravs_map:
                    cursor.execute(
                        '''INSERT INTO ravs(id,originalid,sourceid,rav) VALUES(%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;'''
                        , (get_hash_for_id(source_id, original_rav_id), original_rav_id, source_id, lesson['rav'],))
                    ravs_map[original_rav_id] = get_hash_for_id(source_id, original_rav_id)
                body = {
                    "id": id,
                    "sourceid": source_id,
                    "originalid": original_id,
                    "title": lesson["title"],
                    "categoryid": subjects_map[original_subjectId],
                    "seriesId": series_map[original_series_id],
                    "ravId": ravs_map[original_rav_id],
                    "dateStr": lesson["dateStr"],
                    "duration": lesson["duration"],
                    "videoUrl": lesson["videoUrl"],
                    "audioUrl": lesson["audioUrl"],
                    "timestamp": lesson["timestamp"],
                }
                grab_something = True
                add_lesson_to_db(cursor, body)
                if is_main_page:
                    cursor.execute('''INSERT INTO labels (label,sourceid,lessonid) VALUES(%s,%s,%s);''',
                                   (label, source_id, id))
                postgres.commit()
            except Exception as e:
                print( "Error !!! id={0}\ne={1}\n{2}".format(lesson_id, traceback.format_exc(), e))
                break
    return grab_something


def validate_media_url(url):
    try:
        response = urllib.request.urlopen(url)
        # print("response for %s is %s" % url, response.read())
        return True
    except:
        try:
            with eventlet.Timeout(5):
                return urllib.request.get(url).status_code < 400
        except:
            return False


template_media = 'http://iphone-il-1.media-line.co.il/BneiDavid/{0}'
template_audio = 'http://forest-flash-4.media-line.co.il/BneiDavid/{0}'


def extract_media(lesson_url):
    response = urllib.request.urlopen(lesson_url)
    soup = BeautifulSoup(response, 'html.parser')
    iframe = soup.find("iframe", {"name": "Media-Line-Player"})
    src = iframe.attrs['src']
    parsed = urlparse(src)
    query = parsed.query
    filename = parse_qs(query)['filename']
    if filename:
        filename = filename[0]
        # filename = filename[0].encode('utf-8')
        if filename.__contains__('mp4'):
            video_link = template_media.format(filename)
            valid = validate_media_url(video_link)
            if not valid:
                video_link = None

        else:
            video_link = None
        audio_link = template_media.format(filename).replace('/video', '').replace('mp4', 'mp3')
        valid = validate_media_url(audio_link)
        if not valid:
            audio_link = template_audio.format(filename).replace('/video', '').replace('mp4', 'mp3')
            valid = validate_media_url(audio_link)
            if not valid:
                audio_link = None
        print('extracted video={0} audio={1}'.format(video_link, audio_link))
        return video_link, audio_link
    print('extracted audio file name is {0}'.format(filename))
    return None, None


def get_timestamp_for_date(date_str):
    arr = convert_str_to_hebrew_date(date_str)
    day = day_map.index(arr[0]) if arr[0] in day_map else 1
    month = arr[1]
    if month[0] == u'ב':
        month = month[1:]
    month = month_dict.get(month)
    if not month:
        month = 1
    year = arr[2]
    if year[0] == u'ה':
        year = year[1:]
    year_as_int = 5000
    for char in year:
        year_as_int += gimatria_map.get(char)
    try:
        heb = HebrewDate(year_as_int, month, day)
        return calendar.timegm(heb.to_pydate().timetuple())
    except ValueError as e:
        if 'Given month' in str(e):
            heb = HebrewDate(year_as_int, month, 1)
            return calendar.timegm(heb.to_pydate().timetuple())
        return now


def convert_str_to_hebrew_date(date_str):
    arr = date_str.split(' ')
    parsed = []
    for word in arr:
        parsed_word = remove_non_letters(word)
        parsed.append(parsed_word)
    if len(parsed) == 4:  # shana meuberet
        parsed[1] = parsed[1] + ' ' + parsed[2]
        parsed[2] = parsed[3]
    return parsed


def remove_non_letters(word):
    parsed = ''
    for char in word:
        if char in gimatria_map.keys():
            parsed = parsed + char
    return parsed


def grab():
    global series_map, subjects_map, ravs_map, without_valid_content
    cursor = postgres.cursor()
    cursor.execute('select originalid,id from series where sourceid = 1')
    series_map = {row[0]: row[1] for row in cursor.fetchall()}
    cursor.execute('select originalid,id from categories where sourceid = 1')
    subjects_map = {row[0]: row[1] for row in cursor.fetchall()}
    cursor.execute('select originalid,id from ravs where sourceid = 1')
    ravs_map = {row[0]: row[1] for row in cursor.fetchall()}
    for i in range(1, 500):
        get_lesson(template % i)
    grab_main_page()
    # root_path = os.getcwd()
    print(without_valid_content)
    postgres.close()
    driver.quit()


def grab_main_page():
    # getting main page
    clear_labels(postgres, source_id)
    get_lesson(template_main, True)
    postgres.close()
    driver.quit()


if __name__ == "__main__":
    grab()
    # grab_main_page()