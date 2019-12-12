# coding=utf-8
from __future__ import unicode_literals
import eventlet
eventlet.monkey_patch()
from ftplib import FTP
import calendar
import urllib2
from bs4 import BeautifulSoup
from urlparse import urlparse, parse_qs
import requests
import json
from pyluach.dates import HebrewDate
import traceback
import datetime
import psycopg2.extras

postgres_con = {
    'host': 'localhost',
    'user': 'yaakov',
    'password': '1234',
    'port': '5432',
    'database': 'lessons'
}
postgres = psycopg2.connect(**postgres_con)

lesson_template = 'http://www.bneidavid.org%s'
template = 'http://www.bneidavid.org/Web/He/VirtualTorah/Lessons/Default.aspx?serie=%d'
template_id = 'http://www.bneidavid.org/Web/He/VirtualTorah/Lessons/Default.aspx?id=%d'

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

def get_timestamp():
    return int((datetime.datetime.utcnow() - datetime.datetime(1970, 1, 1)).total_seconds())

now = get_timestamp()
counter = 0


def get_lesson(_id):
    print('running on id {0}'.format(_id))
    global counter
    response = urllib2.urlopen(template % _id)
    soup = BeautifulSoup(response, 'html.parser')
    tables = soup.findAll("div", {"class": 'tables_list'})
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
                lesson['id'] = lesson_id.text
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
                lesson['rav_id'] = int(rav_id)
                name = row.find('a', id=lambda x: x and x.endswith('_hlName'))
                title = name.text
                lesson_url = lesson_template % name.attrs['href']
                lesson['title'] = unicode(title)
                lesson['lessonUrl'] = lesson_url
                sidra = row.find('a', id=lambda x: x and x.endswith('_hlSerieName'))
                sidre_name = sidra.text
                sidra_url = sidra.attrs['href']
                lesson['seriesId'] = _id
                lesson['series'] = sidre_name
                lesson['seriesUrl'] = sidra_url
                date = row.find('span', id=lambda x: x and x.endswith('_lblDate')).text.strip()
                timestamp = get_timestamp_for_date(date)
                lesson['timestamp'] = timestamp
                lesson['dateStr'] = date
                length = row.find('span', id=lambda x: x and x.endswith('_lbllength')).text
                lesson['length'] = length
                video = row.find('a', id=lambda x: x and x.endswith('_hlVideo'))
                extracted = None
                video_url, audio_url = None, None
                if video.attrs and 'href' in video.attrs:
                    video_url = video.attrs['href']
                    if video_url.endswith('/vf/audio/'):
                        video_url = None
                    else:
                        valid = validate_media_url(video_url)
                        # print('valid={0} {1}'.format(valid, video_url))
                        if not valid:
                            extracted = extract_media(lesson_url)
                            video_url = extracted[0]
                            # print ('restored {0}'.format(video_url))
                lesson['videoUrl'] = video_url
                audio = row.find('a', id=lambda x: x and x.endswith('_hlAudio'))
                if audio.attrs and 'href' in audio.attrs:
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
                            # print ('restored {0}'.format(audio_url))
                lesson['audioUrl'] = audio_url
                counter = counter + 1
                # print('counter={0}'.format(counter))
                # print('rav={0}\travId={1}'.format(lesson["rav"],lesson["rav_id"]))

                # print '{0}, audio={1} video={2}'.format(lesson['id'], lesson['audioUrl'], lesson['videoUrl'])
                if not audio_url and not video_url:
                    print('no content for id={0}'.format(lesson['id']))
                    continue
                # if  True:
                #     continue
                body = json.dumps({
                    "id": int(lesson["id"]),
                    "label": "myLabel",
                    "title": lesson["title"],
                    "subjectId": lesson["subject_id"],
                    "subject": lesson["subject"],
                    "seriesId": lesson["seriesId"],
                    "series": lesson["series"],
                    "seriesUrl": lesson["seriesUrl"],
                    "ravId": lesson["rav_id"],
                    "rav": lesson["rav"],
                    "dateStr": lesson["dateStr"],
                    "length": lesson["length"],
                    "videoUrl": lesson["videoUrl"],
                    "audioUrl": lesson["audioUrl"],
                    "lessonUrl": lesson["lessonUrl"],
                    "timestamp": lesson["timestamp"],
                }).encode('utf-8')
                body = {
                    "id": int(lesson["id"]),
                    "label": "myLabel",
                    "title": lesson["title"],
                    "subjectId": lesson["subject_id"],
                    "subject": lesson["subject"],
                    "seriesId": lesson["seriesId"],
                    "series": lesson["series"],
                    "seriesUrl": lesson["seriesUrl"],
                    "ravId": lesson["rav_id"],
                    "rav": lesson["rav"],
                    "dateStr": lesson["dateStr"],
                    "length": lesson["length"],
                    "videoUrl": lesson["videoUrl"],
                    "audioUrl": lesson["audioUrl"],
                    "lessonUrl": lesson["lessonUrl"],
                    "timestamp": lesson["timestamp"],
                    "source": 'bnei_david',
                }
                # print body
                cursor.execute('''
                insert into lessons(id,source,title,label,subjectid,subject,seriesid,series,datestr,ravid,rav,"length","videourl","audiourl","timestamp","insertedat","updatedat")
                values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(id)
                DO UPDATE SET
                updatedat = %s;
                ''', (body["id"],body["source"],body["title"],body["label"],body["subjectId"],body["subject"],body["seriesId"],body["series"],
                      body["dateStr"],body["ravId"],body["rav"],body["length"],body["videoUrl"],body["audioUrl"],body["timestamp"],now,now,now,))
                postgres.commit()
            except Exception as e:
                print("Error !!! id={0}\ne={1}".format(lesson['id'], traceback.format_exc()))
                break

def validate_media_url(url):
    try:
        response = urllib2.urlopen(url)
        # print("response for %s is %s" % url, response.read())
        return True
    except:
        try:
            with eventlet.Timeout(5):
                return requests.get(url).status_code < 400
        except:
            return False


template_media = 'http://iphone-il-1.media-line.co.il/BneiDavid/{0}'
template_audio = 'http://forest-flash-4.media-line.co.il/BneiDavid/{0}'


def extract_media(lesson_url):
    response = urllib2.urlopen(lesson_url)
    soup = BeautifulSoup(response, 'html.parser')
    iframe = soup.find("iframe", {"name": "Media-Line-Player"})
    src = iframe.attrs['src']
    parsed = urlparse(src)
    query = parsed.query
    filename = parse_qs(query)['filename']
    if filename:
        filename = filename[0].encode('utf-8')
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


def seed_url(_id):
    req = urllib2.Request('http://localhost:8888/seed')
    req.add_header('Content-Type', 'application/json')
    body = json.dumps({"url": template_id % _id}).encode('utf-8')
    req.add_header('Content-Length', len(body))
    r = urllib2.urlopen(req, body)
    pastebin_url = r.read()
    print("response is:%s" % pastebin_url)


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
    heb = HebrewDate(year_as_int, month, day)
    return calendar.timegm(heb.to_pydate().timetuple())


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


if __name__ == "__main__":
    pass
    for i in range(1, 500):
    # for i in range(1, 10):
        get_lesson(i)
    postgres.close()
